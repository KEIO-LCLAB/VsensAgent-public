"""
core/agent_core.py
Central orchestrator for all agent interactions.

AgentCore owns:
  - WorkingMemory         — scene state + plan + recent events
  - MemoryManager         — episodic (LanceDB) + semantic (YAML) + scene filter
  - ControlParser         — strip/parse LLM <control> blocks
  - SkillRegistry         — dispatch parsed actions to local handlers
  - AgentStatusBroadcaster— push agent_status to Unity on every state change
"""
import asyncio
import copy
import datetime
import json
import logging
import traceback
import uuid
from pathlib import Path

# Import scene_skills to trigger @register side-effects before first dispatch
import core.skills.scene_skills  # noqa: F401

from core.memory.working_memory import WorkingMemory
from core.memory.episodic_memory import EpisodicMemory
from core.memory.semantic_memory import SemanticMemory
from core.memory.scene_filter import SceneFilter
from core.memory.memory_manager import MemoryManager
from core.perception.scene_diff import compute_diff, as_text as diff_as_text
from core.query_first import QueryFirstCoordinator
from core.avatar_review.review_packet import build_avatar_review_packet
from core.skills.control_parser import ControlParser
from core.skills.skill_registry import SkillRegistry
from core.agent_status import AgentStatusBroadcaster
from core.agent_status import (
    IDLE, TRANSCRIBING, THINKING, SPEAKING,
)
from core.protocol.messages import (
    build_clarification_request,
    build_conversation_reply,
    build_proposal_ready,
)
from core.protocol.visual_review import parse_visual_review
from monitor_stats import monitor_stats

logger = logging.getLogger(__name__)

_AVATAR_ACTIONS = {
    "spawn_avatar",
    "remove_avatar",
    "set_avatar_transform",
    "load_avatar_motion",
    "play_avatar_motion",
    "pause_avatar_motion",
    "stop_avatar_motion",
    "clear_avatar_motion",
}

_AVATAR_VISUAL_REVIEW_PROMPT = """You are reviewing validation screenshots for a Unity avatar task.
Decide whether the current avatar placement and motion setup should be accepted or retried.

You will be given exactly two screenshots:
- `avatar_eye`: what the avatar sees from its eye-level logical forward view
- `user_camera`: what the current runtime user camera sees

Consider:
- whether the avatar appears inside the room and near the intended target
- whether the avatar seems to face and approach the target naturally
- whether the target remains visible enough to support the task
- whether the avatar looks embedded, too far away, badly framed, or obviously misplaced

Return JSON only with this exact schema:
{
  "decision": "accept" | "retry",
  "issues": ["too_far", "bad_facing", "embedded", "out_of_room", "target_not_visible", "awkward_framing"],
  "reason": "short explanation"
}
"""

_AVATAR_VISUAL_RETRY_LIMIT = 3


# -----------------------------------------------------------------------
# Lightweight no-op fallbacks — used when full memory hasn't been wired yet
# -----------------------------------------------------------------------

class _NoopEpisodicMemory:
    """Drop-in when LanceDB hasn't been configured (e.g. unit tests)."""
    def store(self, *_, **__): pass
    def retrieve(self, *_, **__): return []
    def count(self): return 0


class _NoopSemanticMemory:
    def get(self, *_, **__): return None
    def as_text(self): return ""

# Path helpers
_PROJECT_ROOT = Path(__file__).parent.parent          # VsensPython/
_AUDIO_OUT_DIR = (
    _PROJECT_ROOT.parent / "VsensAgent" / "AudioRecordings" / "Response"
)


class AgentCore:
    """
    Single orchestrator for all agent interactions.

    Parameters
    ----------
    agent       : VsensOpenAI instance (LLM + TTS + STT)
    broadcaster : AgentStatusBroadcaster wired to the server's broadcast fn
    """

    def __init__(
        self,
        agent,
        broadcaster: AgentStatusBroadcaster,
        episodic: EpisodicMemory = None,
        semantic: SemanticMemory = None,
        client_id: str | None = None,
        username: str = "",
        us: str = "",
    ):
        self.agent = agent
        self.memory = WorkingMemory()
        self.broadcaster = broadcaster
        self.client_id = client_id
        self.username = username
        self.us = us

        # Phase 2 — memory subsystems
        self.scene_filter = SceneFilter(agent.client)
        self.memory_manager = MemoryManager(
            working=self.memory,
            episodic=episodic if episodic is not None else _NoopEpisodicMemory(),
            semantic=semantic if semantic is not None else _NoopSemanticMemory(),
            scene_filter=self.scene_filter,
        )

        # Set by VsensServer after HeartbeatHandler is constructed so that
        # user-commanded control actions can suppress the resulting heartbeat events.
        self.heartbeat_handler = None

    # ------------------------------------------------------------------
    # Voice interaction
    # ------------------------------------------------------------------

    async def handle_voice(self, audio_path: str, scene_snapshot: dict, query_executor=None, object_selector=None) -> dict:
        """
        Full voice pipeline:
          transcribe → update memory → LLM → parse → dispatch → TTS → idle
        """
        if not audio_path or not Path(audio_path).exists():
            return {"type": "error", "message": f"Audio file not found: {audio_path}"}

        try:
            # 1. Transcribe
            await self.broadcaster.set_state(TRANSCRIBING)
            user_text = self.agent.transcribe_audio(audio_path)
            logger.info("[STT] %s", user_text)

            # 2. Update working memory with latest scene
            self.memory.update_scene(scene_snapshot)

            # 3. Build prompt + call LLM
            await self.broadcaster.set_state(THINKING)
            prompt = self._build_prompt(user_text)
            reply_text, structured, query_context = await self._run_query_first_completion(
                user_text,
                prompt,
                query_executor=query_executor,
                object_selector=object_selector,
            )
            logger.info("[GPT] %s", reply_text[:200])

            # 4. Parse final LLM reply
            spoken_text = structured["spoken_text"]
            actions = structured["actions"]

            # 5. Dispatch skills → collect Unity-bound control commands
            control_output = self._dispatch_actions(actions)
            spoken_text, control_output, avatar_visual_review_handled = await self._run_avatar_visual_review_loop(
                spoken_text,
                control_output,
                user_text=user_text,
                query_context=query_context,
                query_executor=query_executor,
            )
            if not avatar_visual_review_handled:
                control_output = await self._enforce_avatar_validation_contract(
                control_output,
                query_context=query_context,
                query_executor=query_executor,
                )
            self._notify_agent_touch(actions)

            # 6. Generate TTS audio
            await self.broadcaster.set_state(SPEAKING)
            audio_reply_path = self._generate_tts(spoken_text)

            # 7. Record stats
            self._record_stats(user_text, spoken_text, "voice")

            # 8. Store episode in episodic memory (non-blocking — errors are swallowed)
            self.memory_manager.store_interaction(
                session_id=self.memory.session_id,
                user_input=user_text,
                agent_reply=spoken_text,
                scene_snapshot=self.memory.scene,
                control_actions=control_output,
            )

            await self.broadcaster.set_state(IDLE)

            return self._build_response_message(
                transcription=user_text,
                spoken_text=spoken_text,
                audio_path=audio_reply_path,
                control_output=control_output,
                structured=structured,
            )

        except asyncio.CancelledError:
            logger.info("[AgentCore] handle_voice cancelled.")
            raise
        except Exception:
            logger.error("[AgentCore] Voice interaction error:\n%s", traceback.format_exc())
            await self.broadcaster.reset()
            return {
                "type": "error",
                "message": traceback.format_exc().splitlines()[-1],
                "details": traceback.format_exc(),
            }

    # ------------------------------------------------------------------
    # Text interaction
    # ------------------------------------------------------------------

    async def handle_text(self, message: str, scene_snapshot: dict, query_executor=None, object_selector=None) -> dict:
        """
        Text-only pipeline (no STT, no TTS):
          update memory → LLM → parse → dispatch → idle
        """
        try:
            # 1. Update working memory
            self.memory.update_scene(scene_snapshot)

            # 2. Build prompt + call LLM
            await self.broadcaster.set_state(THINKING)
            prompt = self._build_prompt(message)
            reply_text, structured, query_context = await self._run_query_first_completion(
                message,
                prompt,
                query_executor=query_executor,
                object_selector=object_selector,
            )
            logger.info("[GPT] %s", reply_text[:200])

            # 3. Parse final LLM reply
            spoken_text = structured["spoken_text"]
            actions = structured["actions"]

            # 4. Dispatch skills
            control_output = self._dispatch_actions(actions)
            spoken_text, control_output, avatar_visual_review_handled = await self._run_avatar_visual_review_loop(
                spoken_text,
                control_output,
                user_text=message,
                query_context=query_context,
                query_executor=query_executor,
            )
            if not avatar_visual_review_handled:
                control_output = await self._enforce_avatar_validation_contract(
                control_output,
                query_context=query_context,
                query_executor=query_executor,
                )
            self._notify_agent_touch(actions)

            # 5. Record stats
            self._record_stats(message, spoken_text, "text")

            # 6. Store episode in episodic memory (non-blocking — errors are swallowed)
            self.memory_manager.store_interaction(
                session_id=self.memory.session_id,
                user_input=message,
                agent_reply=spoken_text,
                scene_snapshot=self.memory.scene,
                control_actions=control_output,
            )

            await self.broadcaster.set_state(IDLE)

            return self._build_response_message(
                transcription=None,
                spoken_text=spoken_text,
                audio_path=None,
                control_output=control_output,
                structured=structured,
            )

        except asyncio.CancelledError:
            logger.info("[AgentCore] handle_text cancelled.")
            raise
        except Exception:
            logger.error("[AgentCore] Text interaction error:\n%s", traceback.format_exc())
            await self.broadcaster.reset()
            return {
                "type": "error",
                "message": traceback.format_exc().splitlines()[-1],
                "details": traceback.format_exc(),
            }

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset conversation history and working memory scene."""
        self.agent.reset_conversation(client_id=self.client_id)
        self.memory.replace_scene({})
        self.memory.last_scene = {}   # clear so next call sends full snapshot
        self.memory.clear_plan()
        self.memory.recent_events.clear()
        logger.info("[AgentCore] Reset complete (session %s)", self.memory.session_id[:8])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, user_text: str) -> str:
        """
        Build the user-turn prompt (Phase 3).
          - Always inject the latest scene memory so the LLM can see current
            objects from heartbeat/session snapshots.
          - Also include the compact diff since the last update when available.
          - Memory context (past episodes, active plan, recent events) is always
            prepended so the LLM can recall prior interactions.
        """
        # 1. Scene context — current snapshot first, diff as supplemental context.
        scene_sections = [
            "Current scene (from latest heartbeat/session memory):\n"
            + json.dumps(self.memory.scene or {}, indent=2, ensure_ascii=False)
        ]
        if self.memory.last_scene:
            changes = compute_diff(self.memory.last_scene, self.memory.scene)
            if changes:
                scene_sections.append(
                    "[Scene changes since last interaction]\n"
                    + diff_as_text(changes)
                )
            else:
                scene_sections.append("[Scene unchanged since last interaction]")
        scene_context = "\n\n".join(scene_sections)

        # 2. Build memory context (past episodes + plan + recent events)
        context = self.memory_manager.build_context(user_text)

        # 3. Compose final prompt
        parts: list[str] = []
        if context:
            parts.append(context)
            parts.append("")
        parts.append(f'The user just said:\n"{user_text}"')
        parts.append("")
        parts.append(scene_context)
        parts.append("")
        return "\n".join(parts)

    async def _run_query_first_completion(
        self,
        user_text: str,
        prompt: str,
        query_executor=None,
        object_selector=None,
    ) -> tuple[str, dict, dict | None]:
        reply_text = self.agent.send_message(prompt, persist=False)
        structured = ControlParser.extract_structured_reply(reply_text)

        query_payload = structured.get("query")
        if not query_payload or query_executor is None:
            self._persist_final_exchange(prompt, reply_text)
            return reply_text, structured, None

        coordinator = QueryFirstCoordinator(query_executor=query_executor)
        try:
            query_result = await coordinator.execute_query(query_payload)
        except asyncio.TimeoutError:
            fallback_text = self._build_query_fallback_reply()
            self._persist_final_exchange(prompt, fallback_text)
            return fallback_text, self._build_plain_structured_reply(fallback_text), None
        except Exception:
            logger.warning("[AgentCore] Query-first lookup failed:\n%s", traceback.format_exc())
            fallback_text = self._build_query_fallback_reply()
            self._persist_final_exchange(prompt, fallback_text)
            return fallback_text, self._build_plain_structured_reply(fallback_text), None

        if query_result.get("type") == "scene.error":
            fallback_text = self._build_query_fallback_reply()
            self._persist_final_exchange(prompt, fallback_text)
            return fallback_text, self._build_plain_structured_reply(fallback_text), None

        query_result = await self._maybe_request_object_selection(
            user_text=user_text,
            query_payload=query_payload,
            query_result=query_result,
            object_selector=object_selector,
        )

        follow_up_prompt = self._build_query_follow_up_prompt(
            user_text=user_text,
            query_payload=query_payload,
            query_result=query_result,
        )
        final_reply_text = self.agent.send_message(follow_up_prompt, persist=False)
        final_structured = ControlParser.extract_structured_reply(final_reply_text)
        self._persist_final_exchange(prompt, final_reply_text)
        return final_reply_text, final_structured, {
            "initial_query": query_payload,
            "initial_query_result": query_result,
        }

    def _build_query_follow_up_prompt(self, *, user_text: str, query_payload: dict, query_result: dict) -> str:
        base_prompt = self._build_prompt(user_text)
        query_method = query_payload.get("method", "")
        query_reason = query_payload.get("reason", "")
        query_result_text = json.dumps(query_result, indent=2, ensure_ascii=False)
        selected_object = query_result.get("selected_object")
        selected_text = ""
        if isinstance(selected_object, dict):
            selected_text = (
                "[Selected object]\n"
                + json.dumps(selected_object, indent=2, ensure_ascii=False)
                + "\n\n"
            )

        return (
            f"{base_prompt}\n"
            "[Query-first follow-up]\n"
            f"The previous step requested {query_method}.\n"
            f"Reason: {query_reason}\n"
            "Use the query result below to produce the final user-facing reply.\n"
            "Do not emit another <query> block unless absolutely necessary.\n\n"
            f"{selected_text}"
            f"{query_result_text}\n"
        )

    async def _maybe_request_object_selection(
        self,
        *,
        user_text: str,
        query_payload: dict,
        query_result: dict,
        object_selector=None,
    ) -> dict:
        if object_selector is None:
            return query_result
        if query_payload.get("method") != "scene.query_objects":
            return query_result

        objects = query_result.get("objects")
        if not isinstance(objects, list) or len(objects) <= 1:
            return query_result
        if not self._query_needs_single_scene_target(user_text):
            return query_result

        candidates = self._prefer_object_candidates_for_task(user_text, objects)
        if len(candidates) <= 1:
            return {**query_result, "objects": candidates}

        candidate_aliases = [
            str(obj.get("alias") or obj.get("id") or "").strip()
            for obj in candidates
            if isinstance(obj, dict) and str(obj.get("alias") or obj.get("id") or "").strip()
        ]
        if not candidate_aliases:
            return query_result

        selection_request = {
            "type": "object_selection.request",
            "selection_id": f"sel_{uuid.uuid4().hex}",
            "prompt": f"Select the target object for: {user_text}",
            "mode": "object",
            "candidate_aliases": candidate_aliases,
            "allow_cancel": True,
        }
        selection = await object_selector(selection_request)
        if not isinstance(selection, dict) or selection.get("cancelled"):
            return query_result

        selected_id = str(selection.get("selected_object_id") or "").strip()
        selected_alias = str(selection.get("selected_alias") or selected_id).strip()
        selected = next(
            (
                obj for obj in candidates
                if isinstance(obj, dict)
                and (
                    str(obj.get("id") or "").strip() == selected_id
                    or str(obj.get("alias") or "").strip() == selected_alias
                )
            ),
            None,
        )
        if selected is None:
            selected = {
                "id": selected_id or selected_alias,
                "alias": selected_alias or selected_id,
                "position": selection.get("world_position"),
            }

        return {
            **query_result,
            "objects": [selected],
            "candidate_objects": candidates,
            "selected_object": selected,
            "selection": selection,
        }

    @staticmethod
    def _query_needs_single_scene_target(user_text: str) -> bool:
        text = (user_text or "").lower()
        action_terms = (
            "place", "put", "attach", "mount", "bind", "move", "set", "create",
            "sensor", "detect", "record", "collect", "opening", "open", "close",
            "放", "放置", "安装", "绑定", "移动", "设置", "创建", "传感器", "检测", "采集", "开关",
        )
        inspection_terms = (
            "what", "which", "list", "show", "有没有", "有哪些", "是什么", "看看", "查询",
        )
        return any(term in text for term in action_terms) and not any(term in text for term in inspection_terms)

    @staticmethod
    def _prefer_object_candidates_for_task(user_text: str, objects: list[dict]) -> list[dict]:
        text = (user_text or "").lower()
        if not any(term in text for term in ("door", "opening", "open", "close", "门", "开关")):
            return objects

        preferred = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            alias = str(obj.get("alias") or obj.get("id") or "").lower()
            tags = {str(tag).lower() for tag in obj.get("tags") or []}
            state = obj.get("state") if isinstance(obj.get("state"), dict) else {}
            available = state.get("available") if isinstance(state, dict) else None
            has_open_closed_state = (
                "with_state" in tags
                or "state_object" in tags
                or (
                    isinstance(available, list)
                    and {"open", "closed"}.issubset({str(item).lower() for item in available})
                )
            )
            if "door" in alias and has_open_closed_state:
                preferred.append(obj)
        return preferred or objects

    @staticmethod
    def _build_plain_structured_reply(spoken_text: str) -> dict:
        return {
            "spoken_text": spoken_text,
            "actions": [],
            "proposal": None,
            "clarification": None,
            "query": None,
            "experiment": None,
        }

    @staticmethod
    def _build_query_fallback_reply() -> str:
        return (
            "I couldn't retrieve the latest scene details from Unity just now. "
            "Please specify the target object or area, or try again."
        )

    def _persist_final_exchange(self, prompt: str, reply_text: str) -> None:
        append_exchange = getattr(self.agent, "append_exchange", None)
        if callable(append_exchange):
            append_exchange(prompt, reply_text)

    async def _run_avatar_visual_review_loop(
        self,
        spoken_text: str,
        control_output: list[dict],
        *,
        user_text: str,
        query_context: dict | None,
        query_executor,
    ) -> tuple[str, list[dict], bool]:
        if query_executor is None:
            return spoken_text, control_output, False

        review_validation_images = getattr(self.agent, "review_validation_images", None)
        if not callable(review_validation_images):
            return spoken_text, control_output, False

        initial_query = (query_context or {}).get("initial_query") or {}
        initial_query_result = (query_context or {}).get("initial_query_result") or {}
        if initial_query_result.get("method") != "scene.query_avatar_candidates":
            return spoken_text, control_output, False

        if not any((action or {}).get("action") in _AVATAR_ACTIONS for action in control_output):
            synthesized = self._synthesize_avatar_control_from_candidates(
                initial_query_result=initial_query_result,
                initial_query=(query_context or {}).get("initial_query") or {},
            )
            if synthesized:
                logger.info(
                    "[AvatarVisualReview] Synthesized default avatar control plan from candidate query result."
                )
                control_output = synthesized

        pose_action = self._find_avatar_pose_action(control_output)
        if pose_action is None:
            return spoken_text, control_output, False

        query_params = dict(initial_query.get("params") or {})
        target_object_id = initial_query_result.get("target_object_id") or query_params.get("target_object_id") or ""
        target_alias = query_params.get("target_alias") or ""
        task_hint = initial_query_result.get("task_hint") or query_params.get("task_hint") or ""
        avatar_id = (pose_action.get("target") or "avatar_main").strip() or "avatar_main"
        motion_json = self._extract_avatar_motion_json(control_output)
        motion_name = self._extract_avatar_motion_name(control_output)
        candidates = list(initial_query_result.get("candidates") or [])
        if not candidates:
            return spoken_text, control_output, False

        control_output = self._ensure_avatar_motion_actions(
            control_output,
            avatar_id=avatar_id,
            task_hint=task_hint,
            spoken_text=spoken_text,
            user_text=user_text,
        )

        coordinator = QueryFirstCoordinator(query_executor=query_executor)
        avatars_query_result = await coordinator.execute_query({
            "method": "scene.query_avatars",
            "params": {},
            "reason": "Check whether avatar pose is currently controlled by the user.",
        })
        pose_authority = self._resolve_avatar_pose_authority(avatars_query_result, avatar_id)
        allow_pose_override = self._user_explicitly_requests_avatar_pose_adjustment(
            user_text=user_text,
            task_hint=task_hint,
            spoken_text=spoken_text,
        )
        if pose_authority == "manual" and not allow_pose_override:
            logger.info(
                "[AvatarVisualReview] avatar_id=%s is manual-authority; preserving current pose and only applying motion controls.",
                avatar_id,
            )
            current_scene_version = avatars_query_result.get("scene_version", initial_query_result.get("scene_version"))
            motion_only_actions = self._strip_avatar_pose_actions(control_output)
            if not motion_only_actions:
                fallback_text = (
                    "The avatar pose is currently under manual control, so I left the position unchanged. "
                    "Ask me to optimize or reposition it if you want me to take over placement again."
                )
                return fallback_text, [], True
            return await self._execute_single_avatar_review_attempt(
                spoken_text=spoken_text,
                candidate_actions=motion_only_actions,
                candidate_id="manual_pose",
                pose_position=None,
                pose_rotation=None,
                validation=None,
                validator_context=f"manual_pose_{uuid.uuid4().hex[:8]}",
                target_object_id=target_object_id,
                target_alias=target_alias,
                task_hint=task_hint,
                avatar_id=avatar_id,
                motion_name=motion_name,
                current_scene_version=current_scene_version,
                coordinator=coordinator,
                review_validation_images=review_validation_images,
                allow_retry=False,
            )

        selected_candidate_id = self._match_avatar_candidate_id(
            candidates,
            (pose_action.get("parameters") or {}).get("position"),
            (pose_action.get("parameters") or {}).get("rotation"),
        )
        ordered_candidates = self._ordered_avatar_candidates(candidates, selected_candidate_id)
        motion_json = self._extract_avatar_motion_json(control_output)
        motion_name = self._extract_avatar_motion_name(control_output)
        current_scene_version = avatars_query_result.get("scene_version", initial_query_result.get("scene_version"))

        last_review = None
        attempted = 0
        for candidate in ordered_candidates:
            if attempted >= _AVATAR_VISUAL_RETRY_LIMIT:
                break
            attempted += 1

            candidate_actions = copy.deepcopy(control_output)
            self._apply_avatar_candidate(candidate_actions, candidate)
            pose_action_for_attempt = self._find_avatar_pose_action(candidate_actions)
            pose_params = (pose_action_for_attempt or {}).get("parameters") or {}
            position = pose_params.get("position")
            rotation = pose_params.get("rotation")
            if position is None or rotation is None:
                continue

            validation_result = await coordinator.execute_query({
                "method": "scene.validate_avatar_placement",
                "params": {
                    "target_object_id": target_object_id,
                    "target_alias": target_alias,
                    "task_hint": task_hint,
                    "position": position,
                    "rotation": rotation,
                    "motion_json": motion_json or "",
                },
                "reason": "Validate avatar placement before executing avatar control actions.",
            })

            validation = validation_result.get("validation") or {}
            logger.info(
                "[AvatarVisualReview] attempt=%s candidate_id=%s pose=%s rotation=%s validation=%s",
                attempted,
                candidate.get("candidate_id", ""),
                pose_params.get("position"),
                pose_params.get("rotation"),
                json.dumps(
                    {
                        "valid": validation.get("valid"),
                        "collision_free": validation.get("collision_free"),
                        "grounded": validation.get("grounded"),
                        "endpoint_valid": validation.get("endpoint_valid"),
                        "trajectory_valid": validation.get("trajectory_valid"),
                        "motion_mode": validation.get("motion_mode"),
                        "distance_to_target": validation.get("distance_to_target"),
                        "facing_score": validation.get("facing_score"),
                        "issues": validation.get("issues"),
                    },
                    ensure_ascii=False,
                ),
            )
            if not validation.get("valid", False):
                suggested_position = self._vector_dict_to_list(validation.get("suggested_position"))
                suggested_rotation = self._vector_dict_to_list(validation.get("suggested_rotation"))
                if suggested_position is not None:
                    pose_params["position"] = suggested_position
                if suggested_rotation is not None:
                    pose_params["rotation"] = suggested_rotation
                if suggested_position is None and suggested_rotation is None:
                    continue

            attempt_scene_version = current_scene_version
            if attempt_scene_version is None:
                attempt_scene_version = validation_result.get("scene_version")

            logger.info(
                "[AvatarVisualReview] attempt=%s candidate_id=%s executing_actions=%s scene_version=%s",
                attempted,
                candidate.get("candidate_id", ""),
                json.dumps(
                    [
                        {
                            "target": (action or {}).get("target"),
                            "action": (action or {}).get("action"),
                            "parameter_keys": sorted(list(((action or {}).get("parameters") or {}).keys())),
                        }
                        for action in candidate_actions
                    ],
                    ensure_ascii=False,
                ),
                attempt_scene_version,
            )
            execute_result = await coordinator.execute_query({
                "method": "scene.execute_actions",
                "params": self._build_scene_execute_actions_params(
                    candidate_actions,
                    scene_version=attempt_scene_version,
                ),
                "reason": "Execute avatar placement and motion for visual validation.",
            })
            if execute_result.get("status") != "success":
                logger.warning(
                    "[AvatarVisualReview] attempt=%s candidate_id=%s execute_failed=%s",
                    attempted,
                    candidate.get("candidate_id", ""),
                    json.dumps(execute_result, ensure_ascii=False),
                )
                continue
            current_scene_version = execute_result.get("scene_version_after", current_scene_version)

            validator_context = validation.get("validator_id") or f"avatar_validation_{uuid.uuid4().hex[:8]}"
            capture_result = await coordinator.execute_query({
                "method": "scene.capture_validation_views",
                "params": {
                    "validator_context": validator_context,
                    "avatar_id": avatar_id,
                    "target_object_id": target_object_id,
                    "target_alias": target_alias,
                },
                "reason": "Capture validation screenshots for visual review.",
            })

            packet = build_avatar_review_packet(
                task_hint=task_hint,
                target_alias=target_alias or target_object_id,
                candidate_id=candidate.get("candidate_id", ""),
                avatar_position=pose_params.get("position"),
                avatar_rotation=pose_params.get("rotation"),
                motion_name=motion_name,
                motion_mode=validation.get("motion_mode") or "static",
                validation_summary=validation,
                artifacts=capture_result.get("artifacts") or [],
            )
            logger.info(
                "[AvatarVisualReview] attempt=%s candidate_id=%s artifacts=%s",
                attempted,
                candidate.get("candidate_id", ""),
                packet["artifacts"],
            )
            current_scene_version = capture_result.get("scene_version", current_scene_version)
            if not packet["artifacts"]:
                last_review = {
                    "decision": "retry",
                    "issues": ["capture_missing"],
                    "reason": "No validation screenshots were captured.",
                }
                logger.warning(
                    "[AvatarVisualReview] attempt=%s candidate_id=%s rejected_before_review reason=%s",
                    attempted,
                    candidate.get("candidate_id", ""),
                    last_review["reason"],
                )
                continue

            review_raw = review_validation_images(
                review_prompt=_AVATAR_VISUAL_REVIEW_PROMPT,
                context_text=packet["context_text"],
                image_paths=packet["artifacts"],
            )
            review = parse_visual_review(review_raw)
            logger.info(
                "[AvatarVisualReview] attempt=%s candidate_id=%s raw_review=%s parsed_review=%s",
                attempted,
                candidate.get("candidate_id", ""),
                review_raw,
                json.dumps(review, ensure_ascii=False),
            )
            last_review = review
            if review.get("decision") == "accept":
                logger.info(
                    "[AvatarVisualReview] accepted attempt=%s candidate_id=%s reason=%s",
                    attempted,
                    candidate.get("candidate_id", ""),
                    review.get("reason", ""),
                )
                return spoken_text, [], True
            logger.warning(
                "[AvatarVisualReview] retrying attempt=%s candidate_id=%s issues=%s reason=%s",
                attempted,
                candidate.get("candidate_id", ""),
                review.get("issues", []),
                review.get("reason", ""),
            )

        fallback_text = (
            "I tried several avatar placements, but none of them looked natural enough to accept yet. "
            "Please try a different target area or adjust the scene and try again."
        )
        if last_review and last_review.get("reason"):
            fallback_text = (
                "I tried several avatar placements, but the visual review still rejected them. "
                f"Last review: {last_review['reason']}"
            )
        logger.warning(
            "[AvatarVisualReview] failed_all_candidates attempts=%s last_review=%s",
            attempted,
            json.dumps(last_review or {}, ensure_ascii=False),
        )
        return fallback_text, [], True

    async def _execute_single_avatar_review_attempt(
        self,
        *,
        spoken_text: str,
        candidate_actions: list[dict],
        candidate_id: str,
        pose_position,
        pose_rotation,
        validation: dict | None,
        validator_context: str,
        target_object_id: str,
        target_alias: str,
        task_hint: str,
        avatar_id: str,
        motion_name: str,
        current_scene_version: int | None,
        coordinator,
        review_validation_images,
        allow_retry: bool,
    ) -> tuple[str, list[dict], bool]:
        logger.info(
            "[AvatarVisualReview] candidate_id=%s executing_actions=%s scene_version=%s manual_mode=%s",
            candidate_id,
            json.dumps(
                [
                    {
                        "target": (action or {}).get("target"),
                        "action": (action or {}).get("action"),
                        "parameter_keys": sorted(list(((action or {}).get("parameters") or {}).keys())),
                    }
                    for action in candidate_actions
                ],
                ensure_ascii=False,
            ),
            current_scene_version,
            not allow_retry,
        )
        execute_result = await coordinator.execute_query({
            "method": "scene.execute_actions",
            "params": self._build_scene_execute_actions_params(
                candidate_actions,
                scene_version=current_scene_version,
            ),
            "reason": "Execute avatar placement and motion for visual validation.",
        })
        if execute_result.get("status") != "success":
            logger.warning(
                "[AvatarVisualReview] candidate_id=%s execute_failed=%s",
                candidate_id,
                json.dumps(execute_result, ensure_ascii=False),
            )
            fallback_text = "I couldn't execute the avatar motion sequence in Unity just now."
            return fallback_text, [], True

        current_scene_version = execute_result.get("scene_version_after", current_scene_version)
        capture_result = await coordinator.execute_query({
            "method": "scene.capture_validation_views",
            "params": {
                "validator_context": validator_context,
                "avatar_id": avatar_id,
                "target_object_id": target_object_id,
                "target_alias": target_alias,
            },
            "reason": "Capture validation screenshots for visual review.",
        })
        packet = build_avatar_review_packet(
            task_hint=task_hint,
            target_alias=target_alias or target_object_id,
            candidate_id=candidate_id,
            avatar_position=pose_position,
            avatar_rotation=pose_rotation,
            motion_name=motion_name,
            motion_mode=(validation or {}).get("motion_mode") or "static",
            validation_summary=validation or {},
            artifacts=capture_result.get("artifacts") or [],
        )
        logger.info(
            "[AvatarVisualReview] candidate_id=%s artifacts=%s",
            candidate_id,
            packet["artifacts"],
        )
        if not packet["artifacts"]:
            fallback_text = "I executed the avatar sequence, but no validation screenshots were captured."
            return fallback_text, [], True

        review_raw = review_validation_images(
            review_prompt=_AVATAR_VISUAL_REVIEW_PROMPT,
            context_text=packet["context_text"],
            image_paths=packet["artifacts"],
        )
        review = parse_visual_review(review_raw)
        logger.info(
            "[AvatarVisualReview] candidate_id=%s raw_review=%s parsed_review=%s",
            candidate_id,
            review_raw,
            json.dumps(review, ensure_ascii=False),
        )
        if review.get("decision") == "accept":
            return spoken_text, [], True

        if not allow_retry:
            fallback_text = (
                "I kept your manual avatar pose, but the screenshot review still thinks it looks off. "
                f"Review: {review.get('reason', 'No reason provided.')}"
            )
            return fallback_text, [], True

        return "", [], False

    async def _enforce_avatar_validation_contract(
        self,
        control_output: list[dict],
        *,
        query_context: dict | None,
        query_executor,
    ) -> list[dict]:
        if not control_output or query_executor is None:
            return control_output

        if not any((action or {}).get("action") in _AVATAR_ACTIONS for action in control_output):
            return control_output

        initial_query = (query_context or {}).get("initial_query") or {}
        initial_query_result = (query_context or {}).get("initial_query_result") or {}
        if initial_query_result.get("method") != "scene.query_avatar_candidates":
            return control_output

        pose_action = self._find_avatar_pose_action(control_output)
        if pose_action is None:
            return control_output

        query_params = dict(initial_query.get("params") or {})
        target_object_id = initial_query_result.get("target_object_id") or query_params.get("target_object_id") or ""
        target_alias = query_params.get("target_alias") or ""
        task_hint = initial_query_result.get("task_hint") or query_params.get("task_hint") or ""
        avatar_id = (pose_action.get("target") or "avatar_main").strip() or "avatar_main"

        pose_params = pose_action.setdefault("parameters", {})
        position = pose_params.get("position")
        rotation = pose_params.get("rotation")
        if position is None or rotation is None:
            first_candidate = ((initial_query_result.get("candidates") or [{}])[:1] or [{}])[0]
            if position is None:
                position = self._vector_dict_to_list(first_candidate.get("position"))
                if position is not None:
                    pose_params["position"] = position
            if rotation is None:
                rotation = self._vector_dict_to_list(first_candidate.get("rotation"))
                if rotation is not None:
                    pose_params["rotation"] = rotation

        motion_json = self._extract_avatar_motion_json(control_output)
        if position is None or rotation is None:
            return control_output

        coordinator = QueryFirstCoordinator(query_executor=query_executor)
        validation_result = await coordinator.execute_query({
            "method": "scene.validate_avatar_placement",
            "params": {
                "target_object_id": target_object_id,
                "target_alias": target_alias,
                "task_hint": task_hint,
                "position": position,
                "rotation": rotation,
                "motion_json": motion_json or "",
            },
            "reason": "Validate avatar placement before executing avatar control actions.",
        })

        validation = validation_result.get("validation") or {}
        if not validation.get("valid"):
            suggested_position = self._vector_dict_to_list(validation.get("suggested_position"))
            suggested_rotation = self._vector_dict_to_list(validation.get("suggested_rotation"))
            if suggested_position is not None:
                pose_params["position"] = suggested_position
            if suggested_rotation is not None:
                pose_params["rotation"] = suggested_rotation

        validator_context = validation.get("validator_id") or f"avatar_validation_{uuid.uuid4().hex[:8]}"
        self._attach_avatar_validation_metadata(
            control_output,
            avatar_id=avatar_id,
            validator_context=validator_context,
            target_object_id=target_object_id,
            target_alias=target_alias,
            task_hint=task_hint,
            attempted_candidate_id=self._match_avatar_candidate_id(
                initial_query_result.get("candidates") or [],
                pose_params.get("position"),
                pose_params.get("rotation"),
            ),
            candidates=initial_query_result.get("candidates") or [],
        )
        return control_output

    @staticmethod
    def _find_avatar_pose_action(control_output: list[dict]) -> dict | None:
        for action in control_output:
            if (action or {}).get("action") in {"spawn_avatar", "set_avatar_transform"}:
                return action
        return None

    @staticmethod
    def _extract_avatar_motion_json(control_output: list[dict]) -> str:
        for action in control_output:
            if (action or {}).get("action") == "load_avatar_motion":
                return (action.get("parameters") or {}).get("motion_json") or ""
        return ""

    @staticmethod
    def _extract_avatar_motion_name(control_output: list[dict]) -> str:
        for action in control_output:
            if (action or {}).get("action") == "load_avatar_motion":
                return (action.get("parameters") or {}).get("motion_name") or "avatar_motion"
        return "avatar_motion"

    @staticmethod
    def _vector_dict_to_list(value):
        if isinstance(value, dict) and all(axis in value for axis in ("x", "y", "z")):
            return [value["x"], value["y"], value["z"]]
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return [value[0], value[1], value[2]]
        return None

    @classmethod
    def _match_avatar_candidate_id(cls, candidates: list[dict], position, rotation) -> str:
        normalized_position = cls._vector_dict_to_list(position)
        normalized_rotation = cls._vector_dict_to_list(rotation)
        if not candidates:
            return ""

        if normalized_position is None or normalized_rotation is None:
            return candidates[0].get("candidate_id", "")

        for candidate in candidates:
            candidate_position = cls._vector_dict_to_list(candidate.get("position"))
            candidate_rotation = cls._vector_dict_to_list(candidate.get("rotation"))
            if candidate_position == normalized_position and candidate_rotation == normalized_rotation:
                return candidate.get("candidate_id", "")

        return candidates[0].get("candidate_id", "")

    @staticmethod
    def _ordered_avatar_candidates(candidates: list[dict], selected_candidate_id: str) -> list[dict]:
        if not candidates:
            return []
        if not selected_candidate_id:
            return list(candidates)

        selected_index = next(
            (index for index, candidate in enumerate(candidates) if candidate.get("candidate_id") == selected_candidate_id),
            0,
        )
        return list(candidates[selected_index:]) + list(candidates[:selected_index])

    @classmethod
    def _apply_avatar_candidate(cls, control_output: list[dict], candidate: dict) -> None:
        pose_action = cls._find_avatar_pose_action(control_output)
        if pose_action is None:
            return

        pose_params = pose_action.setdefault("parameters", {})
        position = cls._vector_dict_to_list(candidate.get("position"))
        rotation = cls._vector_dict_to_list(candidate.get("rotation"))
        if position is not None:
            pose_params["position"] = position
        if rotation is not None:
            pose_params["rotation"] = rotation

    @staticmethod
    def _build_scene_execute_actions_params(control_output: list[dict], *, scene_version: int | None = None) -> dict:
        actions = []
        for action in control_output:
            actions.append({
                "target_id": action.get("target", ""),
                "action_type": action.get("action", ""),
                "parameters": dict(action.get("parameters") or {}),
                "preconditions": [],
            })

        return {
            "scene_version": int(scene_version if scene_version is not None else -1),
            "strict": True,
            "actions": actions,
        }

    @staticmethod
    def _has_avatar_action(control_output: list[dict], action_name: str) -> bool:
        return any((action or {}).get("action") == action_name for action in control_output)

    @staticmethod
    def _avatar_motion_requested(*, user_text: str, spoken_text: str, task_hint: str, control_output: list[dict]) -> bool:
        if any((action or {}).get("action") in {"load_avatar_motion", "play_avatar_motion"} for action in control_output):
            return True

        haystack = " ".join(filter(None, [user_text, spoken_text, task_hint])).lower()
        motion_terms = (
            " play ",
            " start ",
            " motion",
            " animate",
            " animation",
            " perform",
            " walk",
        )
        padded = f" {haystack} "
        return any(term in padded for term in motion_terms)

    def _ensure_avatar_motion_actions(
        self,
        control_output: list[dict],
        *,
        avatar_id: str,
        task_hint: str,
        spoken_text: str,
        user_text: str,
    ) -> list[dict]:
        if not self._avatar_motion_requested(
            user_text=user_text,
            spoken_text=spoken_text,
            task_hint=task_hint,
            control_output=control_output,
        ):
            return control_output

        motion_description = (task_hint or "").replace("_", " ").strip()
        if not motion_description:
            return control_output

        motion_name = (task_hint or "avatar_motion").strip() or "avatar_motion"
        patched_actions = list(control_output)
        has_load = self._has_avatar_action(patched_actions, "load_avatar_motion")
        has_play = self._has_avatar_action(patched_actions, "play_avatar_motion")

        if not has_load:
            logger.info(
                "[AvatarVisualReview] Synthesizing load_avatar_motion from task_hint='%s' for avatar_id=%s",
                task_hint,
                avatar_id,
            )
            synthetic_load = SkillRegistry.dispatch(
                action="load_avatar_motion",
                target=avatar_id,
                parameters={
                    "motion_description": motion_description,
                    "motion_name": motion_name,
                },
            )
            if synthetic_load.get("status") in {"unknown_skill", "skill_validation_error", "skill_error"}:
                logger.warning(
                    "[AvatarVisualReview] Failed to synthesize load_avatar_motion for task '%s': %s",
                    task_hint,
                    synthetic_load,
                )
                return control_output

            inserted = False
            next_actions = []
            for action in patched_actions:
                if not inserted and (action or {}).get("action") == "play_avatar_motion":
                    next_actions.append(synthetic_load)
                    inserted = True
                next_actions.append(action)
            if not inserted:
                next_actions.append(synthetic_load)
            patched_actions = next_actions
            has_load = True

        if not has_play:
            synthetic_play = SkillRegistry.dispatch(
                action="play_avatar_motion",
                target=avatar_id,
                parameters={"speed": 1.0, "loop": False},
            )
            if synthetic_play.get("status") in {"unknown_skill", "skill_validation_error", "skill_error"}:
                logger.warning(
                    "[AvatarVisualReview] Failed to synthesize play_avatar_motion for task '%s': %s",
                    task_hint,
                    synthetic_play,
                )
                return patched_actions

            inserted = False
            next_actions = []
            for action in patched_actions:
                next_actions.append(action)
                if not inserted and (action or {}).get("action") == "load_avatar_motion":
                    next_actions.append(synthetic_play)
                    inserted = True
            if not inserted:
                next_actions.append(synthetic_play)
            patched_actions = next_actions

        return patched_actions

    def _synthesize_avatar_control_from_candidates(
        self,
        *,
        initial_query_result: dict,
        initial_query: dict,
    ) -> list[dict]:
        candidates = list(initial_query_result.get("candidates") or [])
        first_candidate = (candidates[:1] or [None])[0]
        if not first_candidate:
            return []

        position = self._vector_dict_to_list(first_candidate.get("position"))
        rotation = self._vector_dict_to_list(first_candidate.get("rotation"))
        if position is None or rotation is None:
            return []

        query_params = dict(initial_query.get("params") or {})
        avatar_id = (query_params.get("avatar_id") or "avatar_main").strip() or "avatar_main"
        task_hint = (
            initial_query_result.get("task_hint")
            or query_params.get("task_hint")
            or "avatar_motion"
        )

        synthesized: list[dict] = []
        spawn_action = SkillRegistry.dispatch(
            action="spawn_avatar",
            target=avatar_id,
            parameters={
                "prefab_key": "smplx_male",
                "position": position,
                "rotation": rotation,
            },
        )
        if spawn_action.get("status") in {"unknown_skill", "skill_validation_error", "skill_error"}:
            logger.warning(
                "[AvatarVisualReview] Failed to synthesize spawn_avatar from candidate query: %s",
                spawn_action,
            )
            return []
        synthesized.append(spawn_action)

        load_action = SkillRegistry.dispatch(
            action="load_avatar_motion",
            target=avatar_id,
            parameters={
                "motion_description": str(task_hint).replace("_", " ").strip(),
                "motion_name": str(task_hint).strip() or "avatar_motion",
            },
        )
        if load_action.get("status") not in {"unknown_skill", "skill_validation_error", "skill_error"}:
            synthesized.append(load_action)
            play_action = SkillRegistry.dispatch(
                action="play_avatar_motion",
                target=avatar_id,
                parameters={"speed": 1.0, "loop": False},
            )
            if play_action.get("status") not in {"unknown_skill", "skill_validation_error", "skill_error"}:
                synthesized.append(play_action)
        else:
            logger.warning(
                "[AvatarVisualReview] Failed to synthesize load_avatar_motion from candidate query: %s",
                load_action,
            )

        return synthesized

    @staticmethod
    def _attach_avatar_validation_metadata(
        control_output: list[dict],
        *,
        avatar_id: str,
        validator_context: str,
        target_object_id: str,
        target_alias: str,
        task_hint: str,
        attempted_candidate_id: str,
        candidates: list[dict],
    ) -> None:
        for action in control_output:
            if (action or {}).get("action") not in _AVATAR_ACTIONS:
                continue

            params = action.setdefault("parameters", {})
            params.setdefault("avatar_id", avatar_id)
            params["validator_context"] = validator_context
            params["validation_target_object_id"] = target_object_id
            params["validation_target_alias"] = target_alias
            params["validation_task_hint"] = task_hint
            params["validation_candidate_id"] = attempted_candidate_id
            params["validation_candidates"] = candidates
            if action.get("action") == "play_avatar_motion":
                params["capture_validation_views"] = True

    @staticmethod
    def _resolve_avatar_pose_authority(query_result: dict, avatar_id: str) -> str:
        avatars = list((query_result or {}).get("avatars") or [])
        for avatar in avatars:
            if (avatar or {}).get("avatar_id") == avatar_id:
                return str((avatar or {}).get("pose_authority") or "agent").strip().lower() or "agent"
        return "agent"

    @staticmethod
    def _strip_avatar_pose_actions(control_output: list[dict]) -> list[dict]:
        return [
            action for action in control_output
            if (action or {}).get("action") not in {"spawn_avatar", "set_avatar_transform"}
        ]

    @staticmethod
    def _user_explicitly_requests_avatar_pose_adjustment(*, user_text: str, task_hint: str, spoken_text: str) -> bool:
        haystack = " ".join(filter(None, [user_text, task_hint, spoken_text])).lower()
        override_terms = (
            "optimize",
            "reposition",
            "adjust",
            "move the avatar",
            "move avatar",
            "refine pose",
            "improve pose",
            "fix pose",
        )
        return any(term in haystack for term in override_terms)

    def _dispatch_actions(self, actions: list[dict]) -> list[dict]:
        """Run each parsed action through the SkillRegistry."""
        results = []
        for action_item in actions:
            result = SkillRegistry.dispatch(
                action=action_item.get("action", ""),
                target=action_item.get("target", ""),
                parameters=action_item.get("parameters", {}),
            )
            if result.get("status") in {"unknown_skill", "skill_validation_error", "skill_error"}:
                logger.warning(
                    "[AgentCore] Dropping non-executable control result for action '%s': %s",
                    action_item.get("action", ""),
                    result,
                )
                continue
            results.append(result)
        return results

    def _notify_agent_touch(self, actions: list[dict]) -> None:
        """
        Tell HeartbeatHandler about every object the agent just modified so
        that the resulting heartbeat diff events are suppressed for one
        cooldown window.  No-op when no HeartbeatHandler is wired.
        """
        if not self.heartbeat_handler or not actions:
            return
        targets = [a.get("target", "") for a in actions if a.get("target")]
        self.heartbeat_handler.mark_agent_touched(targets, actions=actions)

    def _generate_tts(self, text: str) -> str:
        """Generate TTS audio and return the absolute path."""
        _AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
        file_name = f"reply_audio_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        output_path = str(_AUDIO_OUT_DIR / file_name)
        self.agent.speak_text(text, output_path=output_path)
        return output_path

    def _record_stats(self, user_input: str, agent_reply: str, interaction_type: str) -> None:
        """Forward token stats to monitor_stats if available."""
        if not hasattr(self.agent, "_last_token_stats"):
            return
        s = self.agent._last_token_stats
        monitor_stats.add_interaction(
            user_input=user_input,
            agent_reply=agent_reply,
            prompt_tokens=s["prompt_tokens"],
            completion_tokens=s["completion_tokens"],
            total_tokens=s["total_tokens"],
            cached_tokens=s["cached_tokens"],
            interaction_type=interaction_type,
            client_id=self.client_id,
            username=self.username,
            us=self.us,
        )

    def _build_response_message(
        self,
        *,
        transcription: str | None,
        spoken_text: str,
        audio_path: str | None,
        control_output: list[dict],
        structured: dict,
    ) -> dict:
        clarification = structured.get("clarification")
        if clarification:
            return build_clarification_request(
                question_id=clarification.get("question_id") or uuid.uuid4().hex,
                prompt=clarification.get("prompt") or spoken_text or "Please choose an option.",
                options=clarification.get("options") or [],
                selection_mode=clarification.get("selection_mode") or "single",
                reply=spoken_text,
                transcription=transcription,
                audio_path=audio_path,
                control=control_output,
            )

        proposal = structured.get("proposal")
        if proposal:
            return build_proposal_ready(
                proposal_id=proposal.get("proposal_id") or uuid.uuid4().hex,
                title=proposal.get("title") or "Proposal",
                summary=proposal.get("summary") or spoken_text,
                options=proposal.get("options") or [],
                reply=spoken_text,
                transcription=transcription,
                audio_path=audio_path,
                control=control_output,
            )

        message = build_conversation_reply(
            reply=spoken_text,
            transcription=transcription,
            audio_path=audio_path,
            control=control_output,
        )
        experiment = structured.get("experiment")
        if experiment:
            message["experiment"] = experiment
        return message
