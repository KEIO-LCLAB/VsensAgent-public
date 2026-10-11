import asyncio
import base64
import inspect
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import websockets
except ModuleNotFoundError:  # pragma: no cover - local test fallback
    class _ConnectionClosed(Exception):
        pass

    class _WebsocketExceptions:
        ConnectionClosed = _ConnectionClosed

    class _WebsocketsFallback:
        exceptions = _WebsocketExceptions()

    websockets = _WebsocketsFallback()

from core.agent_core import AgentCore
from core.agent_status import AgentStatusBroadcaster, EXECUTING, IDLE, WAITING_SUBAGENT
from core.delegation import (
    ClaudeWorkerRunner,
    DelegatedSubagentSessionManager,
    DelegatedTaskWorkspaceManager,
)
from core.data_analysis.service import analyze_recordings
from core.experiments import ExperimentPreflightResolver, ExperimentRunner
from core.jobs.job_manager import JobManager
from core.memory.episodic_memory import EpisodicMemory
from core.memory.semantic_memory import SemanticMemory
from core.perception.heartbeat_handler import HeartbeatHandler
from core.perception.perception_config import load as _load_perception_cfg
from core.protocol.messages import (
    build_clarification_request,
    build_conversation_reply,
    build_delegated_task_artifacts_snapshot,
    build_delegated_task_result,
)
from core.protocol.user_turns import build_clarification_reply_turn, build_proposal_select_turn
from core.skills.skill_registry import SkillRegistry
from core.workspace.recording_resolver import resolve_recording_paths
from monitor_stats import monitor_stats
from vsens_openai import VsensOpenAI

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_DEFAULT_WEBSOCKET_MAX_SIZE_BYTES = 64 * 1024 * 1024


def _sanitize_segment(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (value or "anonymous").strip())
    return safe.strip("_") or "anonymous"


class SessionTranscriptWriter:
    def __init__(self, *, base_dir: Path, connected_at: datetime, client_id: str):
        self._base_dir = base_dir
        self._connected_at = connected_at
        self._client_id = client_id
        self._username = "anonymous"
        self._us = "anonymous"
        self._path: Path | None = None
        self._buffer: list[dict] = []

    @property
    def path(self) -> Path | None:
        return self._path

    def configure_identity(self, *, username: str, us: str) -> None:
        self._username = username or "anonymous"
        self._us = us or "anonymous"
        timestamp = self._connected_at.strftime("%Y%m%d_%H%M%S")
        parent = self._base_dir / _sanitize_segment(us) / _sanitize_segment(username)
        parent.mkdir(parents=True, exist_ok=True)
        self._path = parent / f"{timestamp}_{self._client_id}.jsonl"
        if self._buffer:
            with self._path.open("a", encoding="utf-8") as handle:
                for event in self._buffer:
                    handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._buffer.clear()

    def append(self, message: str) -> None:
        if message.startswith("recv "):
            self.append_raw_message("recv", message[5:])
            return
        if message.startswith("send "):
            self.append_raw_message("send", message[5:])
            return
        self.append_event(
            direction="internal",
            event_kind="server",
            message_type=None,
            payload=None,
            summary=message,
        )

    def append_lifecycle(self, event_name: str, *, summary: str = "", payload=None) -> None:
        self.append_event(
            direction="lifecycle",
            event_kind="lifecycle",
            message_type=None,
            payload=payload,
            summary=summary or event_name,
        )

    def append_raw_message(self, direction: str, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
            message_type = payload.get("type") if isinstance(payload, dict) else None
        except json.JSONDecodeError as exc:
            payload = {"raw": raw_message, "parse_error": str(exc)}
            message_type = None
        self.append_message(direction, payload, message_type=message_type)

    def append_message(self, direction: str, payload, *, message_type: str | None = None, summary: str = "") -> None:
        inferred_type = message_type
        if inferred_type is None and isinstance(payload, dict):
            inferred_type = payload.get("type")
        self.append_event(
            direction=direction,
            event_kind="message",
            message_type=inferred_type,
            payload=payload,
            summary=summary or f"{direction} {inferred_type or 'message'}",
        )

    def append_event(
        self,
        *,
        direction: str,
        event_kind: str,
        message_type: str | None = None,
        payload=None,
        summary: str = "",
    ) -> None:
        now = datetime.now()
        event = {
            "schema_version": 1,
            "timestamp": now.isoformat(timespec="microseconds"),
            "elapsed_ms": max(0, int((now - self._connected_at).total_seconds() * 1000)),
            "client_id": self._client_id,
            "username": self._username,
            "us": self._us,
            "direction": direction,
            "event_kind": event_kind,
            "message_type": message_type,
            "payload": payload,
            "summary": summary,
        }
        if self._path is None:
            self._buffer.append(event)
            return
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


class UnityActionLogWriter:
    def __init__(self, *, base_dir: Path, connected_at: datetime, client_id: str):
        self._base_dir = base_dir
        self._connected_at = connected_at
        self._client_id = client_id
        self._path: Path | None = None
        self._buffer: list[str] = []

    def configure_identity(self, *, username: str, us: str) -> None:
        timestamp = self._connected_at.strftime("%Y%m%d_%H%M%S")
        parent = self._base_dir / _sanitize_segment(us) / _sanitize_segment(username)
        parent.mkdir(parents=True, exist_ok=True)
        self._path = parent / f"{timestamp}_{self._client_id}.log"
        if self._buffer:
            with self._path.open("a", encoding="utf-8") as handle:
                for line in self._buffer:
                    handle.write(line + "\n")
            self._buffer.clear()

    def append_record(self, payload: dict) -> None:
        line = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"unity.scene_action {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        if self._path is None:
            self._buffer.append(line)
            return
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


@dataclass
class ClientSession:
    client_id: str
    websocket: object
    connected_at: datetime
    connected_at_iso: str
    username: str = "anonymous"
    us: str = "anonymous"
    agent: VsensOpenAI | None = None
    broadcaster: AgentStatusBroadcaster | None = None
    agent_core: AgentCore | None = None
    job_manager: JobManager | None = None
    heartbeat_handler: HeartbeatHandler | None = None
    _active_task: asyncio.Task | None = None
    _pending_queries: dict[str, asyncio.Future] = field(default_factory=dict)
    _query_timeout_s: float = 5.0
    transcript: SessionTranscriptWriter | None = None
    unity_action_log: UnityActionLogWriter | None = None
    _pending_delegated_task_questions: dict[str, dict] = field(default_factory=dict)
    _delegated_task_job_id: str | None = None
    _delegated_task_future: asyncio.Task | None = None
    _delegated_task_waiting_for_user: bool = False
    _experiment_task: asyncio.Task | None = None
    _recording_snapshot_waiters: list[asyncio.Future] = field(default_factory=list)
    _recent_recording_snapshots: list[dict] = field(default_factory=list)
    _pending_object_selections: dict[str, asyncio.Future] = field(default_factory=dict)
    _pending_experiment_confirmations: dict[str, dict] = field(default_factory=dict)


class VsensWebSocketServer:
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.websocket_max_size_bytes = self._load_websocket_max_size_bytes()
        self._perception_cfg = _load_perception_cfg()
        self.clients: set = set()
        self.sessions: dict[str, ClientSession] = {}
        self._recording_storage_root = Path(__file__).parent / "data" / "recordings" / "sessions"
        self._unity_action_log_root = Path(__file__).parent / "data" / "logs_unity_action" / "sessions"
        self._delegated_task_workspace_manager = DelegatedTaskWorkspaceManager(
            root=Path(__file__).parent / "data" / "tasks"
        )
        self._delegated_subagent_session_manager = DelegatedSubagentSessionManager()
        self._delegated_task_runner = ClaudeWorkerRunner()

        self.handlers = {
            "client.hello": self._handle_client_hello,
            "transcribe_and_reply": self._handle_transcribe_and_reply,
            "text_chat": self._handle_text_chat,
            "conversation.ask": self._handle_text_chat,
            "conversation.transcribe": self._handle_transcribe_and_reply,
            "clarification.reply": self._handle_clarification_reply,
            "proposal.select": self._handle_proposal_select,
            "job.start": self._handle_job_start,
            "job.status": self._handle_job_status,
            "job.cancel": self._handle_job_cancel,
            "reset": self._handle_reset,
            "agent_interrupt": self._handle_agent_interrupt,
            "plan_interrupt": self._handle_plan_interrupt,
            "sensor.recording_snapshot": self._handle_sensor_recording_snapshot,
            "task.start": self._handle_delegated_task_start,
            "data.analysis_start": self._handle_delegated_task_start,
            "unity.scene_action": self._handle_unity_scene_action,
            "object_selection.reply": self._handle_object_selection_reply,
        }

    @staticmethod
    def _load_websocket_max_size_bytes() -> int:
        raw = (os.environ.get("VSENS_WEBSOCKET_MAX_SIZE_BYTES") or "").strip()
        if not raw:
            return _DEFAULT_WEBSOCKET_MAX_SIZE_BYTES
        try:
            value = int(raw)
        except ValueError:
            logger.warning(
                "[Server] Ignoring invalid VSENS_WEBSOCKET_MAX_SIZE_BYTES=%r; using %d",
                raw,
                _DEFAULT_WEBSOCKET_MAX_SIZE_BYTES,
            )
            return _DEFAULT_WEBSOCKET_MAX_SIZE_BYTES
        return max(value, 1024 * 1024)

    def _make_session(self, websocket) -> ClientSession:
        client_id = f"client_{uuid.uuid4().hex[:8]}"
        connected_at = datetime.now()

        agent = VsensOpenAI()
        transcript = SessionTranscriptWriter(
            base_dir=Path(__file__).parent / "data" / "logs" / "sessions",
            connected_at=connected_at,
            client_id=client_id,
        )
        session_ref: dict[str, ClientSession] = {}

        async def _send_bound_to_session(message: dict, ws=websocket) -> None:
            bound_session = session_ref.get("session")
            if bound_session is None:
                await self._send_to_websocket(ws, message)
                return
            await self._send_to_session(bound_session, ws, message)

        broadcaster = AgentStatusBroadcaster(
            lambda message, ws=websocket: _send_bound_to_session(message, ws),
            client_id=client_id,
        )

        data_root = Path(__file__).parent / "data" / "memory"
        episodic = EpisodicMemory(
            db_path=str(data_root / "episodes"),
            openai_client=agent.client,
        )
        semantic = SemanticMemory(
            knowledge_dir=str(data_root / "knowledge"),
        )
        agent_core = AgentCore(
            agent,
            broadcaster,
            episodic=episodic,
            semantic=semantic,
            client_id=client_id,
            username="anonymous",
            us="anonymous",
        )
        heartbeat_handler = HeartbeatHandler(
            working_memory=agent_core.memory,
            memory_manager=agent_core.memory_manager,
            agent=agent,
            broadcaster=broadcaster,
            broadcast_fn=lambda message, ws=websocket: _send_bound_to_session(message, ws),
            perception_cfg=self._perception_cfg,
        )
        agent_core.heartbeat_handler = heartbeat_handler

        session = ClientSession(
            client_id=client_id,
            websocket=websocket,
            connected_at=connected_at,
            connected_at_iso=connected_at.isoformat(timespec="seconds"),
            agent=agent,
            broadcaster=broadcaster,
            agent_core=agent_core,
            job_manager=JobManager(),
            heartbeat_handler=heartbeat_handler,
            transcript=transcript,
            unity_action_log=UnityActionLogWriter(
                base_dir=self._unity_action_log_root,
                connected_at=connected_at,
                client_id=client_id,
            ),
        )
        session_ref["session"] = session
        monitor_stats.register_client(client_id, connected_at=connected_at)
        return session

    async def _send_to_websocket(self, websocket, message: dict) -> None:
        await websocket.send(json.dumps(message))

    async def _send_to_session(self, session, websocket, message: dict) -> None:
        await self._send_to_websocket(websocket, message)
        transcript = getattr(session, "transcript", None)
        if transcript is not None:
            transcript.append_message("send", message)

    async def handler(self, websocket):
        session = self._make_session(websocket)
        self.sessions[session.client_id] = session
        self.clients.add(websocket)
        monitor_stats.set_client_count(len(self.sessions))
        connect_line = f"[Server] Client connected: {session.client_id} {getattr(websocket, 'remote_address', '')}"
        monitor_stats.add_log(connect_line, client_id=session.client_id)
        session.transcript.append_lifecycle(
            "connect",
            summary=connect_line,
            payload={"remote_address": str(getattr(websocket, "remote_address", ""))},
        )

        try:
            await self._send_to_session(
                session,
                websocket,
                {
                    "type": "server_config",
                    "heartbeat_interval_s": self._perception_cfg.heartbeat.interval_s,
                    "tts_in_push": self._perception_cfg.agent_push.tts_enabled,
                    "attention_threshold": self._perception_cfg.attention.threshold,
                },
            )
        except Exception as exc:
            logger.warning("[Server] Failed to send server_config on connect: %s", exc)

        try:
            async for raw_message in websocket:
                monitor_stats.add_log(f"[Server] Received: {raw_message[:120]}", client_id=session.client_id)
                session.transcript.append_raw_message("recv", raw_message)
                response = await self.process_message(raw_message, websocket, session=session)
                if response is not None:
                    await self._send_to_session(session, websocket, response)
        except websockets.exceptions.ConnectionClosed:
            disconnect_line = f"[Server] Client disconnected: {session.client_id}"
            monitor_stats.add_log(disconnect_line, client_id=session.client_id)
            session.transcript.append_lifecycle("disconnect", summary=disconnect_line)
        finally:
            self.clients.discard(websocket)
            self.sessions.pop(session.client_id, None)
            monitor_stats.unregister_client(session.client_id)
            monitor_stats.set_client_count(len(self.sessions))

    async def process_message(self, raw_message: str, websocket=None, session=None) -> dict | None:
        try:
            msg = json.loads(raw_message)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON message."}

        session = session or self
        msg_type = msg.get("type")

        if msg_type in {"scene.query_response", "scene.execute_actions_response", "scene.validate_actions_response"}:
            await self._handle_scene_request_response(session, msg)
            return None
        if msg_type == "scene.error" and msg.get("request_id"):
            await self._handle_scene_error(session, msg)
            return None
        if msg_type == "scene_heartbeat":
            return await self._handle_heartbeat(msg, websocket=websocket, session=session)
        if self._should_block_for_waiting_subagent(session=session, msg_type=msg_type, msg=msg):
            return {
                "type": "error",
                "message": "A delegated task is still running. Please wait for the worker to finish or answer the pending clarification first.",
            }

        handler = self.handlers.get(msg_type)
        if not handler:
            return {"error": f"Unsupported message type: {msg_type}"}

        async_turn_types = {
            "transcribe_and_reply",
            "conversation.transcribe",
            "text_chat",
            "conversation.ask",
            "clarification.reply",
            "proposal.select",
        }

        if websocket is not None and msg_type in async_turn_types:
            if getattr(session, "_active_task", None) and not session._active_task.done():
                return {"type": "error", "message": "Agent is busy"}

            session._turn_generation = self._current_turn_generation(session) + 1
            msg["_turn_generation"] = session._turn_generation
            session._active_task = asyncio.create_task(
                self._run_handler_and_reply(handler, msg, websocket, session)
            )
            return None

        if websocket is not None and msg_type == "sensor.recording_snapshot" and hasattr(websocket, "send"):
            active_task = asyncio.ensure_future(handler(msg, websocket=websocket, session=session))
            session._active_task = active_task
            try:
                result = await active_task
                if result is not None:
                    await self._send_to_session(session, websocket, result)
                    if result.get("type") == "sensor.recording_snapshot_ack" and not result.get("handled_by_experiment"):
                        await self._send_recording_analysis_reminder(session, websocket, result)
                return None
            except asyncio.CancelledError:
                logger.info("[Server] Handler for '%s' was cancelled.", msg_type)
                return None
            finally:
                if getattr(session, "_active_task", None) is active_task:
                    session._active_task = None

        active_task = asyncio.ensure_future(handler(msg, websocket=websocket, session=session))
        session._active_task = active_task
        try:
            return await active_task
        except asyncio.CancelledError:
            logger.info("[Server] Handler for '%s' was cancelled.", msg_type)
            return None
        finally:
            if getattr(session, "_active_task", None) is active_task:
                session._active_task = None

    async def _handle_client_hello(self, msg: dict, websocket=None, session=None) -> dict:
        username = (msg.get("username") or "anonymous").strip() or "anonymous"
        us = (msg.get("us") or "anonymous").strip() or "anonymous"
        session.username = username
        session.us = us
        if session.agent_core is not None:
            session.agent_core.username = username
            session.agent_core.us = us
        monitor_stats.update_client_identity(session.client_id, username=username, us=us)
        if session.transcript is not None:
            session.transcript.configure_identity(username=username, us=us)
            session.transcript.append_lifecycle(
                "hello",
                summary=f"hello username={username} us={us}",
                payload={"username": username, "us": us},
            )
        if session.unity_action_log is not None:
            session.unity_action_log.configure_identity(username=username, us=us)
        monitor_stats.add_log(
            f"[Server] Client hello accepted username={username} us={us}",
            client_id=session.client_id,
        )
        return {
            "type": "client.hello_ack",
            "client_id": session.client_id,
            "username": username,
            "us": us,
            "connected_at": session.connected_at_iso,
        }

    async def _handle_transcribe_and_reply(self, msg: dict, websocket=None, session=None) -> dict:
        audio_path = msg.get("audio_path")
        scene_snapshot = msg.get("scene_snapshot", {})

        if audio_path:
            audio_path_obj = Path(audio_path)
            if not audio_path_obj.is_absolute():
                audio_path_str = str(audio_path)
                if not audio_path_str.startswith("VsensAgent/"):
                    audio_path_obj = _PROJECT_ROOT / "VsensAgent" / audio_path_str
                else:
                    audio_path_obj = _PROJECT_ROOT / audio_path_str
            audio_path = str(audio_path_obj)

        if websocket is None:
            return await session.agent_core.handle_voice(audio_path, scene_snapshot)

        query_executor = self._make_query_executor(session, websocket)
        return await self._call_agent_handle_voice(
            session.agent_core,
            audio_path,
            scene_snapshot,
            query_executor=query_executor,
            object_selector=lambda request: self._request_object_selection(session, websocket, request),
        )

    async def _handle_text_chat(self, msg: dict, websocket=None, session=None) -> dict:
        message = msg.get("message", "")
        scene_snapshot = msg.get("scene_snapshot", {})
        if websocket is None:
            return await session.agent_core.handle_text(message, scene_snapshot)

        query_executor = self._make_query_executor(session, websocket)
        return await self._call_agent_handle_text(
            session.agent_core,
            message,
            scene_snapshot,
            query_executor=query_executor,
            object_selector=lambda request: self._request_object_selection(session, websocket, request),
        )

    async def _handle_clarification_reply(self, msg: dict, websocket=None, session=None) -> dict:
        question_id = msg.get("question_id")
        if not question_id:
            return {"type": "error", "message": "clarification.reply requires question_id"}
        pending_experiments = getattr(session, "_pending_experiment_confirmations", None)
        if not isinstance(pending_experiments, dict):
            pending_experiments = {}
            session._pending_experiment_confirmations = pending_experiments
        if question_id in pending_experiments:
            return await self._handle_experiment_confirmation_reply(
                msg=msg,
                websocket=websocket,
                session=session,
                pending=pending_experiments[question_id],
            )
        pending_questions = getattr(session, "_pending_delegated_task_questions", None)
        if not isinstance(pending_questions, dict):
            pending_questions = {}
            session._pending_delegated_task_questions = pending_questions
        pending = pending_questions.get(question_id)
        if pending is not None:
            return await self._resume_delegated_task_from_clarification(
                msg=msg,
                websocket=websocket,
                session=session,
                pending=pending,
            )

        message = build_clarification_reply_turn(
            question_id=question_id,
            selected_ids=msg.get("selected_ids") or [],
            free_text=msg.get("free_text") or "",
        )
        scene_snapshot = msg.get("scene_snapshot", {})
        if websocket is None:
            return await session.agent_core.handle_text(message, scene_snapshot)

        query_executor = self._make_query_executor(session, websocket)
        return await self._call_agent_handle_text(
            session.agent_core,
            message,
            scene_snapshot,
            query_executor=query_executor,
            object_selector=lambda request: self._request_object_selection(session, websocket, request),
        )

    async def _handle_proposal_select(self, msg: dict, websocket=None, session=None) -> dict:
        proposal_id = msg.get("proposal_id")
        if not proposal_id:
            return {"type": "error", "message": "proposal.select requires proposal_id"}

        message = build_proposal_select_turn(
            proposal_id=proposal_id,
            selected_option_ids=msg.get("selected_option_ids") or [],
            note=msg.get("note") or "",
        )
        scene_snapshot = msg.get("scene_snapshot", {})
        if websocket is None:
            return await session.agent_core.handle_text(message, scene_snapshot)

        query_executor = self._make_query_executor(session, websocket)
        return await self._call_agent_handle_text(
            session.agent_core,
            message,
            scene_snapshot,
            query_executor=query_executor,
            object_selector=lambda request: self._request_object_selection(session, websocket, request),
        )

    async def _handle_job_start(self, msg: dict, websocket=None, session=None) -> dict:
        job_kind = msg.get("job_kind")
        if not job_kind:
            return {"type": "error", "message": "job.start requires job_kind"}
        return session.job_manager.start_job(job_kind, msg.get("payload") or {})

    @staticmethod
    async def _call_agent_handle_text(
        agent_core,
        message: str,
        scene_snapshot: dict,
        *,
        query_executor=None,
        object_selector=None,
    ) -> dict:
        try:
            return await agent_core.handle_text(
                message,
                scene_snapshot,
                query_executor=query_executor,
                object_selector=object_selector,
            )
        except TypeError as exc:
            if "object_selector" not in str(exc):
                raise
            return await agent_core.handle_text(
                message,
                scene_snapshot,
                query_executor=query_executor,
            )

    @staticmethod
    async def _call_agent_handle_voice(
        agent_core,
        audio_path: str,
        scene_snapshot: dict,
        *,
        query_executor=None,
        object_selector=None,
    ) -> dict:
        try:
            return await agent_core.handle_voice(
                audio_path,
                scene_snapshot,
                query_executor=query_executor,
                object_selector=object_selector,
            )
        except TypeError as exc:
            if "object_selector" not in str(exc):
                raise
            return await agent_core.handle_voice(
                audio_path,
                scene_snapshot,
                query_executor=query_executor,
            )

    async def _handle_job_status(self, msg: dict, websocket=None, session=None) -> dict:
        job_id = msg.get("job_id")
        if not job_id:
            return {"type": "error", "message": "job.status requires job_id"}
        try:
            return session.job_manager.get_job(job_id)
        except KeyError:
            return {"type": "error", "message": f"Unknown job_id: {job_id}"}

    async def _handle_job_cancel(self, msg: dict, websocket=None, session=None) -> dict:
        job_id = msg.get("job_id")
        if not job_id:
            return {"type": "error", "message": "job.cancel requires job_id"}
        try:
            return session.job_manager.cancel_job(job_id, reason=msg.get("reason", ""))
        except KeyError:
            return {"type": "error", "message": f"Unknown job_id: {job_id}"}

    async def _handle_reset(self, msg: dict, websocket=None, session=None) -> dict:
        await self._set_waiting_subagent(session=session, enabled=False)
        session.agent_core.reset()
        return {"type": "reset_ack", "status": "conversation reset"}

    async def _handle_agent_interrupt(self, msg: dict, websocket=None, session=None) -> dict:
        session._turn_generation = self._current_turn_generation(session) + 1
        if getattr(session, "_active_task", None) and not session._active_task.done():
            session._active_task.cancel()
            logger.info("[Server] Agent interrupt: cancelled active task for %s.", getattr(session, "client_id", "legacy"))

        delegated_future = getattr(session, "_delegated_task_future", None)
        delegated_job_id = getattr(session, "_delegated_task_job_id", None)
        if delegated_future is not None and not delegated_future.done():
            delegated_future.cancel()
        if delegated_job_id and getattr(session, "job_manager", None) is not None:
            try:
                session.job_manager.cancel_job(delegated_job_id, reason="Interrupted by user")
            except KeyError:
                pass
        experiment_task = getattr(session, "_experiment_task", None)
        if experiment_task is not None and not experiment_task.done():
            experiment_task.cancel()
        pending_questions = getattr(session, "_pending_delegated_task_questions", None)
        if pending_questions is not None:
            pending_questions.clear()
        await self._set_waiting_subagent(session=session, enabled=False)

        session.agent_core.memory.clear_plan()
        await session.broadcaster.reset()
        return {"type": "interrupt_ack", "message": "Stopped."}

    async def _handle_plan_interrupt(self, msg: dict, websocket=None, session=None) -> dict:
        await self._set_waiting_subagent(session=session, enabled=False)
        session.agent_core.memory.clear_plan()
        await session.broadcaster.set_state(IDLE, detail="Plan interrupted.")
        return {"type": "interrupt_ack", "message": "Plan cleared."}

    async def _handle_delegated_task_start(self, msg: dict, websocket=None, session=None) -> dict:
        task_type = (msg.get("task_type") or "analysis").strip().lower()
        goal = (msg.get("goal") or "").strip()
        if not goal:
            return {"type": "error", "message": "task.start requires goal"}
        selector = (msg.get("selector") or "recent_n").strip().lower()
        timestamp_label = (msg.get("timestamp_label") or "").strip() or None
        recent_n_raw = msg.get("recent_n", 3)
        try:
            recent_n = int(recent_n_raw)
        except (TypeError, ValueError):
            return {"type": "error", "message": "task.start recent_n must be an integer"}
        if recent_n <= 0:
            return {"type": "error", "message": "task.start recent_n must be > 0"}
        if selector not in {"latest", "all", "recent_n", "by_label"}:
            return {"type": "error", "message": "task.start selector must be latest|all|recent_n|by_label"}
        if selector == "by_label" and not timestamp_label:
            return {"type": "error", "message": "task.start with selector=by_label requires timestamp_label"}

        skill_result = SkillRegistry.dispatch(
            action="delegate_task",
            target="",
            parameters={
                "task_type": task_type,
                "goal": goal,
                "selector": selector,
                "recent_n": recent_n,
                "timestamp_label": timestamp_label,
            },
        )
        if skill_result.get("status") in {"unknown_skill", "skill_validation_error", "skill_error"}:
            return {
                "type": "error",
                "message": f"task.start failed: {skill_result.get('message', skill_result.get('status'))}",
            }

        if task_type == "analysis":
            resolved = resolve_recording_paths(
                root=self._recording_storage_root,
                us=getattr(session, "us", "anonymous"),
                username=getattr(session, "username", "anonymous"),
                selector=selector,
                timestamp_label=timestamp_label,
                recent_n=recent_n,
            )
            if not resolved.resolved_paths:
                return {
                    "type": "error",
                    "message": (
                        f"No recordings found for selector '{selector}' under "
                        f"{resolved.us}/{resolved.username}."
                    ),
                }
            recording_keys = [f"{resolved.us}/{resolved.username}/{path.name}" for path in resolved.resolved_paths]
            recording_paths = [str(path) for path in resolved.resolved_paths]
        else:
            return {"type": "error", "message": f"Unsupported task_type: {task_type}"}

        if getattr(session, "job_manager", None) is None:
            return {"type": "error", "message": "task.start failed: job manager is unavailable for this session"}

        job_payload = {
            "task_type": task_type,
            "goal": goal,
            "selector": selector,
            "recent_n": recent_n,
            "timestamp_label": timestamp_label,
            "recording_count": len(recording_paths),
            "recording_keys": recording_keys,
            "recording_paths": recording_paths,
        }
        started = session.job_manager.start_job("delegated_task", job_payload)
        started["recording_count"] = len(recording_paths)
        started["recording_keys"] = recording_keys
        await self._set_waiting_subagent(
            session=session,
            enabled=True,
            job_id=started["job_id"],
            waiting_for_user=False,
            detail="Waiting for delegated worker",
        )
        if websocket is not None and hasattr(websocket, "send"):
            await self._send_to_session(session, websocket, started)
            delegated_task = asyncio.create_task(
                self._run_delegated_task_job(
                    websocket=websocket,
                    session=session,
                    job_id=started["job_id"],
                    job_payload=job_payload,
                )
            )
            session._delegated_task_future = delegated_task
            return None
        return started

    async def _run_delegated_task_job(
        self,
        *,
        websocket,
        session,
        job_id: str,
        job_payload: dict,
    ) -> None:
        try:
            scene_context = getattr(
                getattr(getattr(session, "agent_core", None), "memory", None),
                "scene",
                {},
            ) or {}
            if not isinstance(scene_context, dict):
                scene_context = {}
            workspace_manager = getattr(self, "_delegated_task_workspace_manager", None)
            if workspace_manager is None:
                workspace_manager = DelegatedTaskWorkspaceManager(
                    root=Path(__file__).parent / "data" / "tasks"
                )
                self._delegated_task_workspace_manager = workspace_manager
            workspace = workspace_manager.create_workspace(
                job_id=job_id,
                task_payload=job_payload,
                scene_context=scene_context,
            )
            session_manager = getattr(self, "_delegated_subagent_session_manager", None)
            if session_manager is None:
                session_manager = DelegatedSubagentSessionManager()
                self._delegated_subagent_session_manager = session_manager
            session_state = session_manager.ensure_session(
                workspace=workspace,
                job_id=job_id,
                task_payload=job_payload,
            )
            result = await self._maybe_await_runner(
                self._delegated_task_runner.run(
                    workspace=workspace,
                    task_payload=job_payload,
                    session_state=session_state,
                )
            )
            assistant_note = (result.get("report_text") or "").strip()
            if assistant_note:
                session_manager.append_history(
                    workspace=workspace,
                    role="assistant",
                    content=assistant_note,
                )
            elif result.get("questions_for_agent"):
                session_manager.append_history(
                    workspace=workspace,
                    role="assistant",
                    content="\n".join(result.get("questions_for_agent") or []),
                )
            if result.get("status") == "needs_agent_input":
                await self._handle_delegated_task_questions(
                    websocket=websocket,
                    session=session,
                    job_id=job_id,
                    job_payload=job_payload,
                    workspace=workspace,
                    result=result,
                )
                return
            completed_payload = {
                **job_payload,
                "workspace_path": str(workspace),
                "latest_summary": result.get("report_text", ""),
                "artifacts": self._normalize_delegated_task_artifacts(
                    workspace=workspace,
                    artifacts=result.get("artifacts") or [],
                ),
            }
            session_manager.mark_completed(workspace=workspace)
            completed = session.job_manager.complete_job(job_id, payload=completed_payload)
            result_message = build_delegated_task_result(
                job_id=job_id,
                task_type=job_payload.get("task_type", ""),
                status=result.get("status", "completed"),
                reply=result.get("report_text", ""),
                questions_for_agent=result.get("questions_for_agent") or [],
                artifacts=completed_payload["artifacts"],
            )
            artifacts_snapshot_message = self._build_delegated_task_artifacts_snapshot_message(
                workspace=workspace,
                job_id=job_id,
                task_type=job_payload.get("task_type", ""),
                artifacts=completed_payload["artifacts"],
            )
            if getattr(session, "agent_core", None) is not None and getattr(session.agent_core, "memory", None) is not None:
                session.agent_core.memory.add_event(
                    {
                        "summary": result.get("report_text", ""),
                        "delegated_task": {
                            "job_id": job_id,
                            "task_type": job_payload.get("task_type", ""),
                            "recording_keys": job_payload.get("recording_keys", []),
                        },
                    }
                )
            if getattr(session, "transcript", None) is not None:
                session.transcript.append_event(
                    direction="internal",
                    event_kind="task",
                    message_type="task.completed",
                    payload={
                        "job_id": job_id,
                        "task_type": job_payload.get("task_type", ""),
                        "recording_keys": job_payload.get("recording_keys", []),
                    },
                    summary=(
                        f"delegated task completed job_id={job_id} "
                        f"task_type={job_payload.get('task_type', '')} "
                        f"recordings={len(job_payload.get('recording_keys', []))}"
                    ),
                )
            await self._set_waiting_subagent(session=session, enabled=False)
            await self._send_to_session(session, websocket, completed)
            await self._send_to_session(session, websocket, result_message)
            if artifacts_snapshot_message is not None:
                await self._send_to_session(session, websocket, artifacts_snapshot_message)
        except asyncio.CancelledError:
            logger.info("[Server] delegated_task job cancelled")
            await self._set_waiting_subagent(session=session, enabled=False)
            raise
        except Exception as exc:
            logger.exception("[Server] delegated_task job failed")
            workspace_path = job_payload.get("workspace_path")
            if workspace_path:
                session_manager = getattr(self, "_delegated_subagent_session_manager", None)
                if session_manager is not None:
                    session_manager.mark_failed(workspace=Path(workspace_path), error=str(exc))
            if getattr(session, "transcript", None) is not None:
                session.transcript.append_event(
                    direction="internal",
                    event_kind="task",
                    message_type="task.failed",
                    payload={"job_id": job_id, "reason": str(exc)},
                    summary=f"delegated task failed job_id={job_id} reason={exc}",
                )
            failed = session.job_manager.fail_job(job_id, reason=str(exc))
            await self._set_waiting_subagent(session=session, enabled=False)
            await self._send_to_session(session, websocket, failed)
        finally:
            current_task = asyncio.current_task()
            if getattr(session, "_delegated_task_future", None) is current_task:
                session._delegated_task_future = None

    @staticmethod
    async def _maybe_await_runner(result):
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _handle_delegated_task_questions(
        self,
        *,
        websocket,
        session,
        job_id: str,
        job_payload: dict,
        workspace: Path,
        result: dict,
    ) -> None:
        questions = [str(item).strip() for item in (result.get("questions_for_agent") or []) if str(item).strip()]
        if not questions:
            raise ValueError("Delegated task requested agent input without any questions")
        resolved_reply = self._try_resolve_delegated_task_questions(
            session=session,
            job_payload=job_payload,
            questions=questions,
        )
        if resolved_reply is not None:
            await self._set_waiting_subagent(
                session=session,
                enabled=True,
                job_id=job_id,
                waiting_for_user=False,
                detail="Waiting for delegated worker",
            )
            resumed_payload = {
                **job_payload,
                "workspace_path": str(workspace),
                "blocking_reason": "",
                "pending_question_id": None,
                "questions_for_agent": [],
            }
            self._delegated_subagent_session_manager.record_user_reply(
                workspace=workspace,
                reply_text=resolved_reply,
            )
            running = session.job_manager.update_job(
                job_id,
                status="running",
                payload=resumed_payload,
                reason="",
            )
            await self._send_to_session(session, websocket, running)
            await self._run_delegated_task_job(
                websocket=websocket,
                session=session,
                job_id=job_id,
                job_payload=resumed_payload,
            )
            return
        agent_reply = await self._ask_main_agent_for_delegated_task_questions(
            session=session,
            job_payload=job_payload,
            questions=questions,
        )
        if agent_reply is not None:
            await self._set_waiting_subagent(
                session=session,
                enabled=True,
                job_id=job_id,
                waiting_for_user=False,
                detail="Waiting for delegated worker",
            )
            resumed_payload = {
                **job_payload,
                "workspace_path": str(workspace),
                "blocking_reason": "",
                "pending_question_id": None,
                "questions_for_agent": [],
            }
            self._delegated_subagent_session_manager.record_user_reply(
                workspace=workspace,
                reply_text=agent_reply,
            )
            running = session.job_manager.update_job(
                job_id,
                status="running",
                payload=resumed_payload,
                reason="",
            )
            await self._send_to_session(session, websocket, running)
            await self._run_delegated_task_job(
                websocket=websocket,
                session=session,
                job_id=job_id,
                job_payload=resumed_payload,
            )
            return
        question_id = f"delegated_task:{job_id}:{uuid.uuid4().hex[:8]}"
        session_manager = self._delegated_subagent_session_manager
        session_manager.mark_waiting_on_user(
            workspace=workspace,
            question_id=question_id,
            questions=questions,
        )
        waiting_payload = {
            **job_payload,
            "workspace_path": str(workspace),
            "blocking_reason": "waiting_for_user_input",
            "pending_question_id": question_id,
            "questions_for_agent": questions,
        }
        waiting = session.job_manager.update_job(
            job_id,
            status="waiting_on_user",
            payload=waiting_payload,
        )
        pending = getattr(session, "_pending_delegated_task_questions", None)
        if pending is None:
            pending = {}
            session._pending_delegated_task_questions = pending
        pending[question_id] = {
            "job_id": job_id,
            "job_payload": waiting_payload,
            "workspace_path": str(workspace),
        }
        await self._set_waiting_subagent(
            session=session,
            enabled=False,
            waiting_for_user=True,
        )
        clarification = build_clarification_request(
            question_id=question_id,
            prompt="\n".join(questions),
            options=[],
            selection_mode="free_text",
            reply=questions[0],
        )
        await self._send_to_session(session, websocket, waiting)
        await self._send_to_session(session, websocket, clarification)

    async def _resume_delegated_task_from_clarification(self, *, msg: dict, websocket, session, pending: dict) -> dict | None:
        question_id = msg.get("question_id")
        pending_questions = getattr(session, "_pending_delegated_task_questions", None) or {}
        pending_questions.pop(question_id, None)
        workspace = Path(pending["workspace_path"])
        reply_text = self._format_clarification_reply_text(msg)
        await self._set_waiting_subagent(
            session=session,
            enabled=True,
            job_id=pending["job_id"],
            waiting_for_user=False,
            detail="Waiting for delegated worker",
        )
        self._delegated_subagent_session_manager.record_user_reply(
            workspace=workspace,
            reply_text=reply_text,
        )
        resumed_payload = {
            **(pending.get("job_payload") or {}),
            "workspace_path": str(workspace),
            "blocking_reason": "",
            "pending_question_id": None,
        }
        running = session.job_manager.update_job(
            pending["job_id"],
            status="running",
            payload=resumed_payload,
            reason="",
        )
        if websocket is not None:
            await self._send_to_session(session, websocket, running)
            await self._run_delegated_task_job(
                websocket=websocket,
                session=session,
                job_id=pending["job_id"],
                job_payload=resumed_payload,
            )
            return None
        return running

    @staticmethod
    def _format_clarification_reply_text(msg: dict) -> str:
        selected_ids = [str(item).strip() for item in (msg.get("selected_ids") or []) if str(item).strip()]
        free_text = (msg.get("free_text") or "").strip()
        parts: list[str] = []
        if selected_ids:
            parts.append("Selected: " + ", ".join(selected_ids))
        if free_text:
            parts.append(free_text)
        return "\n".join(parts) or "(no clarification provided)"

    @staticmethod
    def _try_resolve_delegated_task_questions(*, session, job_payload: dict, questions: list[str]) -> str | None:
        lowered = " ".join(question.lower() for question in questions)
        recording_keys = [str(item).strip() for item in (job_payload.get("recording_keys") or []) if str(item).strip()]
        if recording_keys and any(token in lowered for token in {"which recordings", "what recordings", "recordings should be compared"}):
            lines = ["Use these recordings for the current analysis:"]
            lines.extend(f"- {key}" for key in recording_keys)
            return "\n".join(lines)

        scene = getattr(getattr(getattr(session, "agent_core", None), "memory", None), "scene", {}) or {}
        if scene and any(token in lowered for token in {"current scene", "scene context", "objects in scene"}):
            scene_names = sorted(str(name) for name in scene.keys())
            if scene_names:
                return "Current scene objects:\n" + "\n".join(f"- {name}" for name in scene_names[:20])
        return None

    async def _ask_main_agent_for_delegated_task_questions(self, *, session, job_payload: dict, questions: list[str]) -> str | None:
        agent_core = getattr(session, "agent_core", None)
        if agent_core is None or not hasattr(agent_core, "handle_text"):
            return None
        scene_snapshot = getattr(getattr(agent_core, "memory", None), "scene", {}) or {}
        recording_keys = [str(item).strip() for item in (job_payload.get("recording_keys") or []) if str(item).strip()]
        prompt = (
            "This is an internal coordination request from a delegated subagent.\n"
            "Answer the subagent's question directly using the current task goal, available recordings, scene context, and conversation memory.\n"
            "Do not ask the user a question unless the answer is genuinely unavailable.\n"
            "If you cannot answer reliably, reply with exactly: NEED_USER.\n\n"
            f"Task goal:\n{job_payload.get('goal', '')}\n\n"
            f"Recording keys:\n{json.dumps(recording_keys, ensure_ascii=False, indent=2)}\n\n"
            f"Subagent questions:\n{json.dumps(questions, ensure_ascii=False, indent=2)}\n"
        )
        response = await self._maybe_await_runner(agent_core.handle_text(prompt, scene_snapshot))
        if not isinstance(response, dict):
            return None
        if response.get("type") != "conversation.reply":
            return None
        reply = (response.get("reply") or "").strip()
        if not reply or reply.upper() == "NEED_USER":
            return None
        return reply

    @staticmethod
    def _is_delegated_clarification_reply(session, msg: dict) -> bool:
        question_id = (msg.get("question_id") or "").strip()
        if not question_id:
            return False
        pending_questions = getattr(session, "_pending_delegated_task_questions", None) or {}
        return question_id in pending_questions

    def _should_block_for_waiting_subagent(self, *, session, msg_type: str, msg: dict) -> bool:
        if not getattr(session, "_delegated_task_job_id", None):
            return False
        if getattr(session, "_delegated_task_waiting_for_user", False):
            if msg_type == "clarification.reply":
                return not self._is_delegated_clarification_reply(session, msg)
            return msg_type in {
                "transcribe_and_reply",
                "conversation.transcribe",
                "text_chat",
                "conversation.ask",
                "proposal.select",
            }
        return msg_type in {
            "transcribe_and_reply",
            "conversation.transcribe",
            "text_chat",
            "conversation.ask",
            "proposal.select",
            "clarification.reply",
        }

    async def _set_waiting_subagent(
        self,
        *,
        session,
        enabled: bool,
        job_id: str | None = None,
        waiting_for_user: bool | None = None,
        detail: str = "",
    ) -> None:
        if enabled:
            session._delegated_task_job_id = job_id or getattr(session, "_delegated_task_job_id", None)
        elif waiting_for_user:
            session._delegated_task_job_id = getattr(session, "_delegated_task_job_id", None) or job_id
        else:
            session._delegated_task_job_id = None

        if waiting_for_user is not None:
            session._delegated_task_waiting_for_user = waiting_for_user
        elif not enabled:
            session._delegated_task_waiting_for_user = False

        broadcaster = getattr(session, "broadcaster", None)
        if broadcaster is None:
            return
        if enabled:
            await broadcaster.set_state(WAITING_SUBAGENT, detail=detail or "Waiting for delegated worker")
        elif waiting_for_user:
            await broadcaster.set_state(IDLE, detail="Need your answer")
        else:
            await broadcaster.set_state(IDLE)

    @staticmethod
    def _infer_delegated_artifact_kind(path: Path, raw_kind: str | None = None) -> str:
        if raw_kind:
            return str(raw_kind).strip()
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            return "image"
        if suffix in {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}:
            return "text"
        return "file"

    def _resolve_delegated_artifact_path(self, *, workspace: Path, artifact: object) -> Path | None:
        raw_path = ""
        if isinstance(artifact, str):
            raw_path = artifact.strip()
        elif isinstance(artifact, dict):
            raw_path = str(artifact.get("path") or artifact.get("file_name") or "").strip()
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        return candidate.resolve()

    def _normalize_delegated_task_artifacts(self, *, workspace: Path, artifacts: list[object]) -> list[dict]:
        normalized: list[dict] = []
        for artifact in artifacts or []:
            resolved = self._resolve_delegated_artifact_path(workspace=workspace, artifact=artifact)
            if resolved is None:
                continue
            raw_kind = artifact.get("kind") if isinstance(artifact, dict) else None
            raw_label = artifact.get("label") if isinstance(artifact, dict) else None
            normalized.append(
                {
                    "path": str(resolved),
                    "kind": self._infer_delegated_artifact_kind(resolved, raw_kind),
                    "label": str(raw_label).strip() if raw_label else resolved.stem,
                    "file_name": resolved.name,
                    "server_path": str(resolved),
                }
            )
        return normalized

    def _build_delegated_task_artifacts_snapshot_message(
        self,
        *,
        workspace: Path,
        job_id: str,
        task_type: str,
        artifacts: list[dict],
    ) -> dict | None:
        serialized: list[dict] = []
        for artifact in artifacts or []:
            resolved = self._resolve_delegated_artifact_path(workspace=workspace, artifact=artifact)
            if resolved is None or not resolved.exists() or not resolved.is_file():
                continue
            try:
                content_base64 = base64.b64encode(resolved.read_bytes()).decode("ascii")
            except OSError as exc:
                logger.warning("[Server] Failed to read delegated artifact %s: %s", resolved, exc)
                continue
            serialized.append(
                {
                    "file_name": artifact.get("file_name") or resolved.name,
                    "kind": artifact.get("kind") or self._infer_delegated_artifact_kind(resolved),
                    "label": artifact.get("label") or resolved.stem,
                    "server_path": artifact.get("server_path") or str(resolved),
                    "content_base64": content_base64,
                }
            )
        if not serialized:
            return None
        return build_delegated_task_artifacts_snapshot(
            job_id=job_id,
            task_type=task_type,
            artifacts=serialized,
        )

    async def _handle_sensor_recording_snapshot(self, msg: dict, websocket=None, session=None) -> dict:
        timestamp_label = (msg.get("timestamp_label") or "").strip()
        local_export_directory = (msg.get("local_export_directory") or "").strip()
        files = msg.get("files")
        if not timestamp_label:
            return {"type": "error", "message": "sensor.recording_snapshot requires timestamp_label"}
        if not isinstance(files, list) or not files:
            return {"type": "error", "message": "sensor.recording_snapshot requires non-empty files"}

        target_dir = self._recording_storage_root / _sanitize_segment(session.us) / _sanitize_segment(session.username) / _sanitize_segment(timestamp_label)
        target_dir.mkdir(parents=True, exist_ok=True)

        saved_files: list[str] = []
        for file_info in files:
            if not isinstance(file_info, dict):
                return {"type": "error", "message": "sensor.recording_snapshot files must be objects"}
            file_name = (file_info.get("file_name") or "").strip()
            csv_content = file_info.get("csv_content")
            if not file_name or not isinstance(csv_content, str):
                return {"type": "error", "message": "sensor.recording_snapshot file entries require file_name and csv_content"}

            safe_name = _sanitize_recording_file_name(file_name)
            (target_dir / safe_name).write_text(csv_content, encoding="utf-8")
            saved_files.append(safe_name)

        saved_directory = str(target_dir)
        file_names = sorted(saved_files)
        summary = f"Recording snapshot saved: {timestamp_label} at {saved_directory}"
        if session.agent_core is not None and getattr(session.agent_core, "memory", None) is not None:
            session.agent_core.memory.add_event(
                {
                    "summary": summary,
                    "recording_snapshot": {
                        "timestamp_label": timestamp_label,
                        "saved_directory": saved_directory,
                        "file_names": file_names,
                        "local_export_directory": local_export_directory,
                    },
                }
            )
        if session.transcript is not None:
            session.transcript.append_event(
                direction="internal",
                event_kind="recording",
                message_type="sensor.recording_snapshot",
                payload={
                    "timestamp_label": timestamp_label,
                    "saved_directory": saved_directory,
                    "file_names": file_names,
                    "local_export_directory": local_export_directory,
                },
                summary=(
                    f"recording snapshot saved timestamp={timestamp_label} "
                    f"saved_directory={saved_directory} files={','.join(file_names)}"
                ),
            )
        monitor_stats.add_log(
            f"[Server] Recording snapshot saved: {timestamp_label} -> {saved_directory} ({len(file_names)} files)",
            client_id=session.client_id,
        )
        waiters = list(getattr(session, "_recording_snapshot_waiters", None) or [])
        experiment_task = getattr(session, "_experiment_task", None)
        experiment_active = experiment_task is not None and not experiment_task.done()
        ack = {
            "type": "sensor.recording_snapshot_ack",
            "timestamp_label": timestamp_label,
            "saved_directory": saved_directory,
            "saved_files": file_names,
            "saved_file_count": len(file_names),
            "handled_by_experiment": any(not waiter.done() for waiter in waiters) or experiment_active,
        }
        recent_snapshots = getattr(session, "_recent_recording_snapshots", None)
        if not isinstance(recent_snapshots, list):
            recent_snapshots = []
            session._recent_recording_snapshots = recent_snapshots
        recent_snapshots.append(dict(ack))
        del recent_snapshots[:-5]
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(ack)
        return ack

    async def _send_recording_analysis_reminder(self, session, websocket, ack: dict) -> None:
        file_count = int(ack.get("saved_file_count") or len(ack.get("saved_files") or []))
        noun = "recording file" if file_count == 1 else "recording files"
        verb = "has" if file_count == 1 else "have"
        reply = (
            f"The latest {file_count} {noun} {verb} been synced to the server. "
            "If useful, I can analyze or compare these recordings to see which one best fits the current collection goal."
        )
        await self._send_to_session(
            session,
            websocket,
            build_conversation_reply(reply=reply),
        )

    async def _handle_unity_scene_action(self, msg: dict, websocket=None, session=None) -> dict | None:
        record = msg.get("record")
        if not isinstance(record, dict):
            return {"type": "error", "message": "unity.scene_action requires record"}

        action_id = (record.get("actionId") or "").strip()
        action_type = (record.get("actionType") or "").strip()
        target_id = (record.get("targetId") or "").strip()
        timestamp_utc = (record.get("timestampUtc") or "").strip()
        if not action_id or not action_type or not target_id or not timestamp_utc:
            return {
                "type": "error",
                "message": "unity.scene_action record requires actionId, actionType, targetId, and timestampUtc",
            }

        payload = {
            "client_id": getattr(session, "client_id", ""),
            "username": getattr(session, "username", "anonymous"),
            "us": getattr(session, "us", "anonymous"),
            "scene_name": (msg.get("scene_name") or "").strip() or "unknown",
            "record": record,
        }

        if getattr(session, "unity_action_log", None) is not None:
            session.unity_action_log.append_record(payload)
        if getattr(session, "transcript", None) is not None:
            session.transcript.append_event(
                direction="internal",
                event_kind="unity_action",
                message_type="unity.scene_action",
                payload=payload,
                summary=(
                    "unity action "
                    f"source={record.get('source') or 'unknown'} "
                    f"action={action_type} "
                    f"target={target_id}"
                ),
            )
        return None

    async def _handle_object_selection_reply(self, msg: dict, websocket=None, session=None) -> dict | None:
        session = session or self
        selection_id = str(msg.get("selection_id") or "").strip()
        if not selection_id:
            return {"type": "error", "message": "object_selection.reply requires selection_id"}

        waiters = getattr(session, "_pending_object_selections", None)
        if waiters is None:
            waiters = {}
            session._pending_object_selections = waiters
        future = waiters.pop(selection_id, None)
        if future is not None and not future.done():
            future.set_result(dict(msg))

        if getattr(session, "transcript", None) is not None:
            session.transcript.append_event(
                direction="internal",
                event_kind="server",
                message_type="object_selection.reply",
                payload=msg,
                summary=f"object selection reply selection_id={selection_id}",
            )
        return None

    async def _handle_heartbeat(self, msg: dict, websocket=None, session=None) -> dict | None:
        push = await session.heartbeat_handler.handle(msg.get("scene_snapshot", {}))
        if push and websocket is not None:
            await self._send_to_session(session, websocket, push)
        return None

    async def _handle_scene_request_response(self, session_or_msg, maybe_msg: dict | None = None) -> None:
        if maybe_msg is None:
            session = self
            msg = session_or_msg
        else:
            session = session_or_msg
            msg = maybe_msg
        request_id = msg.get("request_id")
        if not request_id:
            return
        future = session._pending_queries.get(request_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_scene_error(self, session_or_msg, maybe_msg: dict | None = None) -> None:
        if maybe_msg is None:
            session = self
            msg = session_or_msg
        else:
            session = session_or_msg
            msg = maybe_msg
        request_id = msg.get("request_id")
        if not request_id:
            return
        future = session._pending_queries.get(request_id)
        if future and not future.done():
            future.set_result(msg)

    async def _execute_scene_query(self, session_or_websocket, websocket_or_query_request, maybe_query_request: dict | None = None) -> dict:
        if maybe_query_request is None:
            session = self
            websocket = session_or_websocket
            query_request = websocket_or_query_request
        else:
            session = session_or_websocket
            websocket = websocket_or_query_request
            query_request = maybe_query_request

        request_id = query_request.get("request_id")
        if not request_id:
            raise ValueError("scene query request requires request_id")

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        session._pending_queries[request_id] = future

        try:
            await websocket.send(json.dumps(query_request))
            transcript = getattr(session, "transcript", None)
            if transcript is not None:
                transcript.append_message("send", query_request)
            timeout_s = getattr(session, "_query_timeout_s", 5.0)
            return await asyncio.wait_for(future, timeout=timeout_s)
        finally:
            session._pending_queries.pop(request_id, None)

    def _make_query_executor(self, session, websocket):
        async def _executor(query_request: dict) -> dict:
            return await self._execute_scene_query(session, websocket, query_request)

        return _executor

    async def _request_experiment_confirmation_from_reply(self, *, result: dict, websocket, session) -> None:
        experiment = result.get("experiment")
        if not isinstance(experiment, dict):
            return

        question_id = f"experiment_confirm:{uuid.uuid4().hex}"
        pending = getattr(session, "_pending_experiment_confirmations", None)
        if not isinstance(pending, dict):
            pending = {}
            session._pending_experiment_confirmations = pending
        pending[question_id] = {
            "reply": dict(result),
            "experiment": experiment,
        }
        await self._send_to_session(
            session,
            websocket,
            build_clarification_request(
                question_id=question_id,
                prompt=self._format_experiment_confirmation_prompt(experiment),
                options=[
                    {
                        "id": "run_experiment",
                        "label": "Run experiment",
                        "description": "Start the planned setup, recording phases, and optional analysis.",
                    },
                    {
                        "id": "cancel_experiment",
                        "label": "Cancel",
                        "description": "Do not start this experiment.",
                    },
                ],
                selection_mode="single",
            ),
        )

    async def _handle_experiment_confirmation_reply(self, *, msg: dict, websocket, session, pending: dict) -> dict | None:
        question_id = msg.get("question_id")
        confirmations = getattr(session, "_pending_experiment_confirmations", None)
        if not isinstance(confirmations, dict):
            confirmations = {}
            session._pending_experiment_confirmations = confirmations
        confirmations.pop(question_id, None)

        selected_ids = msg.get("selected_ids") or []
        if "run_experiment" not in selected_ids:
            await self._send_to_session(
                session,
                websocket,
                build_conversation_reply(reply="Experiment cancelled. I will not start that plan."),
            )
            return None

        reply = pending.get("reply") or {}
        experiment = pending.get("experiment")
        if not isinstance(experiment, dict):
            await self._send_to_session(
                session,
                websocket,
                build_conversation_reply(reply="I could not start the experiment because the stored plan was missing."),
            )
            return None
        self._start_experiment_from_reply(result={**reply, "experiment": experiment}, websocket=websocket, session=session)
        return None

    @staticmethod
    def _format_experiment_confirmation_prompt(experiment: dict) -> str:
        goal = str(experiment.get("goal") or "Untitled experiment").strip()
        sensors = ", ".join(str(item) for item in (experiment.get("recording") or {}).get("sensors") or []) or "default sensors"
        actor_mode = str(experiment.get("actor_mode") or ("avatar" if experiment.get("requires_avatar") else "manual/object")).strip()
        repeat = int(experiment.get("repeat") or 1)
        lines = [
            f"Confirm experiment plan: {goal}",
            f"Actor mode: {actor_mode}",
            f"Sensors: {sensors}",
            f"Repeat: {repeat}",
            "Phases:",
        ]
        for phase in experiment.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            label = str(phase.get("label") or "phase").strip()
            duration = phase.get("duration_s")
            target = phase.get("target_alias") or phase.get("anchor_alias")
            target_suffix = f" near {target}" if target else ""
            lines.append(f"- {label}: {duration}s{target_suffix}")
        analysis = experiment.get("analysis") or {}
        if analysis.get("run_after"):
            lines.append(f"Analysis after recording: {analysis.get('goal') or 'enabled'}")
        return "\n".join(lines)

    def _start_experiment_from_reply(self, *, result: dict, websocket, session) -> None:
        experiment = result.get("experiment")
        if not isinstance(experiment, dict):
            return
        if getattr(session, "job_manager", None) is None:
            return
        started = session.job_manager.start_job(
            "experiment.run",
            {
                "goal": experiment.get("goal", ""),
                "experiment": experiment,
                "message": f"Experiment planned: {experiment.get('goal', '')}",
            },
        )
        task = asyncio.create_task(
            self._run_experiment_job(
                websocket=websocket,
                session=session,
                job_id=started["job_id"],
                plan=experiment,
                started_message=started,
            )
        )
        session._experiment_task = task

    async def _run_experiment_job(
        self,
        *,
        websocket,
        session,
        job_id: str,
        plan: dict,
        started_message: dict,
    ) -> None:
        await self._set_agent_status(
            session,
            EXECUTING,
            f"Running experiment: {plan.get('goal', '')}".strip(),
        )
        await self._send_to_session(session, websocket, started_message)
        query_executor = self._make_query_executor(session, websocket)

        async def on_event(event: dict) -> None:
            message = self._describe_experiment_event(event)
            if getattr(session, "transcript", None) is not None:
                session.transcript.append_event(
                    direction="internal",
                    event_kind="task",
                    message_type=event.get("event") or "experiment.event",
                    payload={"job_id": job_id, **event},
                    summary=f"experiment event job_id={job_id} event={event.get('event', '')} message={message}",
                )
            if event.get("event") in {
                "phase.started",
                "phase.completed",
                "recording.started",
                "recording.stopped",
                "recording.snapshot_saved",
                "analysis.started",
                "analysis.completed",
            }:
                status = session.job_manager.update_job(
                    job_id,
                    status="running",
                    payload={
                        "goal": plan.get("goal", ""),
                        "experiment": plan,
                        "event": event,
                        "message": message,
                    },
                )
                await self._send_to_session(session, websocket, status)
                await self._set_agent_status(session, EXECUTING, message)

        memory = getattr(getattr(session, "agent_core", None), "memory", None)
        resolver = ExperimentPreflightResolver(
            query_executor=query_executor,
            object_selector=lambda request: self._request_object_selection(session, websocket, request),
            scene_snapshot=getattr(memory, "scene", {}) if memory is not None else {},
        )
        runner = ExperimentRunner(
            query_executor=query_executor,
            wait_for_snapshot=lambda: self._wait_for_next_recording_snapshot(session),
            run_analysis=lambda snapshot, current_plan: self._run_experiment_analysis(
                snapshot=snapshot,
                plan=current_plan,
                session=session,
            ),
            on_event=on_event,
            action_preparer=self._prepare_experiment_action,
        )
        try:
            plan = await resolver.resolve(plan)
            result = await runner.run(plan)
            completed = session.job_manager.complete_job(
                job_id,
                payload={
                    "goal": plan.get("goal", ""),
                    "experiment": plan,
                    "result": result,
                },
            )
            await self._send_to_session(session, websocket, completed)
            analysis = result.get("analysis") if isinstance(result, dict) else None
            if isinstance(analysis, dict) and analysis.get("reply"):
                await self._send_to_session(
                    session,
                    websocket,
                    build_conversation_reply(reply=str(analysis.get("reply") or "")),
                )
            elif not (plan.get("analysis") or {}).get("run_after"):
                await self._send_to_session(
                    session,
                    websocket,
                    build_conversation_reply(
                        reply=(
                            "The experiment recording has been synced to the server. "
                            "If useful, I can analyze or compare it next."
                        )
                    ),
                )
            elif not (result or {}).get("snapshot"):
                await self._send_to_session(
                    session,
                    websocket,
                    build_conversation_reply(
                        reply=(
                            "The experiment actions finished, but I did not receive a recording upload to analyze."
                        )
                    ),
                )
        except asyncio.CancelledError:
            try:
                cancelled = session.job_manager.cancel_job(job_id, reason="Interrupted by user")
                await self._send_to_session(session, websocket, cancelled)
            except KeyError:
                pass
            raise
        except Exception as exc:
            logger.exception("[Server] experiment job failed")
            failed = session.job_manager.fail_job(job_id, reason=str(exc))
            await self._send_to_session(session, websocket, failed)
            await self._send_to_session(
                session,
                websocket,
                build_conversation_reply(
                    reply=self._format_experiment_failure_reply(exc)
                ),
            )
        finally:
            await self._set_agent_status(session, IDLE, "Experiment finished.")
            if getattr(session, "_experiment_task", None) is asyncio.current_task():
                session._experiment_task = None

    @staticmethod
    async def _set_agent_status(session, state: str, detail: str = "") -> None:
        broadcaster = getattr(session, "broadcaster", None)
        setter = getattr(broadcaster, "set_state", None)
        if setter is None:
            return
        result = setter(state, detail=detail)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _describe_experiment_event(event: dict) -> str:
        event_name = str(event.get("event") or "experiment.event")
        phase = str(event.get("phase") or "").strip()
        repeat_index = event.get("repeat_index")
        duration = event.get("duration_s")
        if event_name == "experiment.started":
            return "Starting experiment setup"
        if event_name == "recording.started":
            return f"Started sensor recording for phase {phase}" if phase else "Started sensor recording"
        if event_name == "phase.started":
            repeat_text = f" repeat {int(repeat_index) + 1}" if repeat_index is not None else ""
            duration_text = f" for {duration:g}s" if isinstance(duration, (int, float)) else ""
            return f"Recording phase {phase}{repeat_text}{duration_text}".strip()
        if event_name == "phase.completed":
            return f"Completed phase {phase}" if phase else "Completed experiment phase"
        if event_name == "recording.stopped":
            return "Stopped sensor recording and waiting for upload"
        if event_name == "recording.snapshot_saved":
            snapshot = event.get("snapshot") or {}
            label = snapshot.get("timestamp_label") if isinstance(snapshot, dict) else ""
            return f"Recording uploaded: {label}" if label else "Recording upload finished"
        if event_name == "analysis.started":
            return "Analyzing collected recording"
        if event_name == "analysis.completed":
            return "Analysis completed"
        if event_name == "experiment.completed":
            return "Experiment completed"
        return event_name.replace(".", " ")

    @staticmethod
    def _format_experiment_failure_reply(exc: Exception) -> str:
        reason = str(exc).strip()
        if isinstance(exc, asyncio.TimeoutError):
            reason = "Timed out waiting for the recording upload."
        if not reason:
            reason = exc.__class__.__name__
        return f"The experiment stopped before completion: {reason}"

    async def _request_object_selection(self, session, websocket, request: dict, timeout_s: float = 60.0) -> dict:
        selection_id = str(request.get("selection_id") or f"sel_{uuid.uuid4().hex}").strip()
        message = dict(request)
        message["type"] = "object_selection.request"
        message["selection_id"] = selection_id

        waiters = getattr(session, "_pending_object_selections", None)
        if waiters is None:
            waiters = {}
            session._pending_object_selections = waiters

        future = asyncio.get_running_loop().create_future()
        waiters[selection_id] = future
        await self._send_to_session(session, websocket, message)
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        finally:
            if waiters.get(selection_id) is future:
                waiters.pop(selection_id, None)

    @staticmethod
    def _prepare_experiment_action(action: dict) -> dict:
        if (action or {}).get("action") != "load_avatar_motion":
            return action
        parameters = dict((action or {}).get("parameters") or {})
        if parameters.get("motion_json"):
            return action
        return SkillRegistry.dispatch(
            action="load_avatar_motion",
            target=(action or {}).get("target", ""),
            parameters=parameters,
        )

    async def _wait_for_next_recording_snapshot(self, session, timeout_s: float = 30.0) -> dict | None:
        recent_snapshots = getattr(session, "_recent_recording_snapshots", None)
        if not isinstance(recent_snapshots, list):
            recent_snapshots = []
            session._recent_recording_snapshots = recent_snapshots
        if recent_snapshots:
            return recent_snapshots.pop(0)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        waiters = getattr(session, "_recording_snapshot_waiters", None)
        if waiters is None:
            waiters = []
            session._recording_snapshot_waiters = waiters
        waiters.append(future)
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        finally:
            if future in waiters:
                waiters.remove(future)

    async def _run_experiment_analysis(self, *, snapshot: dict, plan: dict, session) -> dict:
        saved_directory = str((snapshot or {}).get("saved_directory") or "").strip()
        timestamp_label = str((snapshot or {}).get("timestamp_label") or "").strip()
        if not saved_directory:
            return {"reply": "The recording finished, but I could not find the saved recording directory to analyze."}
        recording_key = "/".join(
            part for part in [
                str(getattr(session, "us", "") or "").strip(),
                str(getattr(session, "username", "") or "").strip(),
                timestamp_label,
            ] if part
        )
        analysis = analyze_recordings(
            recording_paths=[saved_directory],
            recording_keys=[recording_key or timestamp_label or saved_directory],
            analysis_focus="threshold",
            scene_context=getattr(getattr(getattr(session, "agent_core", None), "memory", None), "scene", {}) or {},
        )
        return analysis

    async def _run_handler_and_reply(self, handler, msg: dict, websocket, session) -> None:
        try:
            result = await handler(msg, websocket=websocket, session=session)
            if result is not None:
                if self._is_stale_turn(session=session, msg=msg):
                    self._record_stale_turn_drop(session=session, msg=msg, result=result)
                    return
                await self._execute_reliable_reply_actions(result=result, websocket=websocket, session=session)
                if self._is_stale_turn(session=session, msg=msg):
                    self._record_stale_turn_drop(session=session, msg=msg, result=result)
                    return
                await self._send_to_session(session, websocket, result)
                await self._request_experiment_confirmation_from_reply(
                    result=result,
                    websocket=websocket,
                    session=session,
                )
        except asyncio.CancelledError:
            logger.info("[Server] Background handler for '%s' was cancelled.", msg.get("type"))
        finally:
            if getattr(session, "_active_task", None) is asyncio.current_task():
                session._active_task = None

    @staticmethod
    def _current_turn_generation(session) -> int:
        raw = getattr(session, "__dict__", {}).get("_turn_generation", 0)
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _is_stale_turn(*, session, msg: dict) -> bool:
        generation = (msg or {}).get("_turn_generation")
        if generation is None:
            return False
        try:
            return int(generation) != VsensWebSocketServer._current_turn_generation(session)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _record_stale_turn_drop(*, session, msg: dict, result: dict) -> None:
        transcript = getattr(session, "transcript", None)
        if transcript is None:
            return
        transcript.append_event(
            direction="internal",
            event_kind="server",
            message_type="turn.stale_dropped",
            payload={
                "turn_generation": (msg or {}).get("_turn_generation"),
                "current_generation": getattr(session, "_turn_generation", None),
                "message_type": (msg or {}).get("type"),
                "reply_type": (result or {}).get("type") if isinstance(result, dict) else None,
            },
            summary="dropped stale turn reply/actions",
        )

    async def _execute_reliable_reply_actions(self, *, result: dict, websocket, session) -> None:
        if not isinstance(result, dict) or result.get("type") != "conversation.reply":
            return
        control = result.get("control")
        if not isinstance(control, dict):
            return
        actions = control.get("actions")
        if not isinstance(actions, list) or not actions:
            return

        has_reliable_action = any(self._is_reliable_reply_action(action) for action in actions)
        if not has_reliable_action:
            return

        scene_version = await self._query_current_scene_version(session=session, websocket=websocket)
        request = {
            "type": "scene.execute_actions",
            "request_id": f"reliable_{uuid.uuid4().hex}",
            "scene_version": int(scene_version),
            "strict": True,
            "actions": [
                {
                    "target_id": str((action or {}).get("target") or "").strip(),
                    "action_type": str((action or {}).get("action") or "").strip(),
                    "parameters": dict((action or {}).get("parameters") or {}),
                    "preconditions": [],
                }
                for action in actions
            ],
        }
        response = await self._execute_scene_query(session, websocket, request)
        if (response or {}).get("type") == "scene.error" or (response or {}).get("status") == "failed":
            errors = (response or {}).get("errors") or (response or {}).get("message") or "unknown error"
            result["reply"] = f"{result.get('reply') or ''}\n\nI tried to execute the sensor action, but Unity reported: {errors}".strip()
            control["actions"] = []
            return

        control["actions"] = []
        if session.transcript is not None:
            session.transcript.append_event(
                direction="internal",
                event_kind="server",
                message_type="reliable_control.executed",
                payload={
                    "request_id": request["request_id"],
                    "actions": request["actions"],
                    "response": response,
                },
                summary=f"executed {len(actions)} reliable reply control action(s)",
            )

    async def _query_current_scene_version(self, *, session, websocket) -> int:
        request = {
            "type": "scene.query_summary",
            "request_id": f"reliable_{uuid.uuid4().hex}",
        }
        response = await self._execute_scene_query(session, websocket, request)
        try:
            return int((response or {}).get("scene_version"))
        except (TypeError, ValueError):
            raise RuntimeError("scene.query_summary did not return scene_version")

    @staticmethod
    def _is_reliable_reply_action(action: dict) -> bool:
        if not isinstance(action, dict):
            return False
        return str(action.get("action") or "").strip() in {"set_sensor", "remove_sensor"}

    async def start(self):
        message = f"[Server] Starting WebSocket server on ws://{self.host}:{self.port}"
        print(message)
        monitor_stats.add_log(message)
        monitor_stats.set_server_running(True)
        async with websockets.serve(
            self.handler,
            self.host,
            self.port,
            max_size=self.websocket_max_size_bytes,
        ):
            await asyncio.Future()


def _sanitize_recording_file_name(value: str) -> str:
    candidate = Path(value).name
    stem = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in candidate)
    return stem.strip("._") or "recording.csv"
