"""
Statistics collector for agent monitoring.
This module collects aggregate and per-client statistics about agent
interactions, agent state transitions, and server log messages.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional


@dataclass
class InteractionRecord:
    """Record of a single interaction."""
    timestamp: datetime
    user_input: str
    agent_reply: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    interaction_type: str = "voice"
    client_id: Optional[str] = None
    username: str = ""
    us: str = ""


@dataclass
class ClientRecord:
    """Runtime metadata for one connected client."""
    client_id: str
    username: str
    us: str
    connected_at: datetime
    is_connected: bool = True
    agent_state: str = "idle"


class MonitorStats:
    """Thread-safe statistics collector for agent monitoring."""

    def __init__(self):
        self._lock = Lock()
        self.interactions: List[InteractionRecord] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cached_tokens = 0
        self.conversation_round = 0
        self.server_start_time = datetime.now()
        self.is_server_running = False
        self.current_clients = 0
        self.agent_state: str = "idle"
        self._clients: Dict[str, ClientRecord] = {}
        self._log_entries: List[str] = []
        self._client_logs: Dict[str, List[str]] = {}
        self._max_log_entries: int = 500

    def _recompute_totals(self) -> None:
        self.total_prompt_tokens = sum(record.prompt_tokens for record in self.interactions)
        self.total_completion_tokens = sum(record.completion_tokens for record in self.interactions)
        self.total_tokens = sum(record.total_tokens for record in self.interactions)
        self.total_cached_tokens = sum(record.cached_tokens for record in self.interactions)
        self.conversation_round = len(self.interactions)

    def register_client(
        self,
        client_id: str,
        *,
        username: str = "anonymous",
        us: str = "anonymous",
        connected_at: Optional[datetime] = None,
    ) -> None:
        with self._lock:
            existing = self._clients.get(client_id)
            self._clients[client_id] = ClientRecord(
                client_id=client_id,
                username=username or (existing.username if existing is not None else "anonymous"),
                us=us or (existing.us if existing is not None else "anonymous"),
                connected_at=connected_at or (existing.connected_at if existing is not None else datetime.now()),
                is_connected=True,
                agent_state=existing.agent_state if existing is not None else "idle",
            )
            self.current_clients = sum(1 for record in self._clients.values() if record.is_connected)

    def update_client_identity(self, client_id: str, *, username: str, us: str) -> None:
        with self._lock:
            record = self._clients.get(client_id)
            if record is None:
                self._clients[client_id] = ClientRecord(
                    client_id=client_id,
                    username=username or "anonymous",
                    us=us or "anonymous",
                    connected_at=datetime.now(),
                )
            else:
                record.username = username or "anonymous"
                record.us = us or "anonymous"

    def unregister_client(self, client_id: str) -> None:
        with self._lock:
            record = self._clients.get(client_id)
            if record is not None:
                record.is_connected = False
            self.current_clients = sum(1 for record in self._clients.values() if record.is_connected)

    def add_interaction(
        self,
        user_input: str,
        agent_reply: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cached_tokens: int = 0,
        interaction_type: str = "voice",
        client_id: Optional[str] = None,
        username: str = "",
        us: str = "",
    ) -> None:
        with self._lock:
            if client_id:
                record = self._clients.get(client_id)
                if record is not None:
                    username = username or record.username
                    us = us or record.us
            self.interactions.append(
                InteractionRecord(
                    timestamp=datetime.now(),
                    user_input=user_input,
                    agent_reply=agent_reply,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cached_tokens=cached_tokens,
                    interaction_type=interaction_type,
                    client_id=client_id,
                    username=username,
                    us=us,
                )
            )
            self._recompute_totals()

    def reset_conversation(self, client_id: Optional[str] = None) -> None:
        with self._lock:
            if client_id:
                self.interactions = [record for record in self.interactions if record.client_id != client_id]
            else:
                self.interactions.clear()
            self._recompute_totals()

    def set_server_running(self, running: bool) -> None:
        with self._lock:
            self.is_server_running = running
            if running:
                self.server_start_time = datetime.now()

    def set_client_count(self, count: int) -> None:
        with self._lock:
            self.current_clients = count

    def set_agent_state(self, state: str, *, client_id: Optional[str] = None) -> None:
        with self._lock:
            if client_id:
                record = self._clients.get(client_id)
                if record is not None:
                    record.agent_state = state
            else:
                self.agent_state = state

    def add_log(self, message: str, *, client_id: Optional[str] = None) -> None:
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            prefix = f"[client={client_id}] " if client_id else ""
            line = f"[{ts}] {prefix}{message}"
            self._log_entries.append(line)
            if len(self._log_entries) > self._max_log_entries:
                self._log_entries = self._log_entries[-self._max_log_entries:]
            if client_id:
                bucket = self._client_logs.setdefault(client_id, [])
                bucket.append(line)
                if len(bucket) > self._max_log_entries:
                    self._client_logs[client_id] = bucket[-self._max_log_entries:]

    def get_stats_snapshot(self, client_id: Optional[str] = None) -> Dict:
        with self._lock:
            if client_id:
                interactions = [record for record in self.interactions if record.client_id == client_id]
                prompt_tokens = sum(record.prompt_tokens for record in interactions)
                completion_tokens = sum(record.completion_tokens for record in interactions)
                total_tokens = sum(record.total_tokens for record in interactions)
                cached_tokens = sum(record.cached_tokens for record in interactions)
                client_record = self._clients.get(client_id)
                agent_state = client_record.agent_state if client_record is not None else "idle"
                recent_logs = list(self._client_logs.get(client_id, [])[-200:])
                round_count = len(interactions)
            else:
                interactions = list(self.interactions)
                prompt_tokens = self.total_prompt_tokens
                completion_tokens = self.total_completion_tokens
                total_tokens = self.total_tokens
                cached_tokens = self.total_cached_tokens
                agent_state = self.agent_state
                recent_logs = list(self._log_entries[-200:])
                round_count = self.conversation_round

            clients = [
                {
                    "client_id": record.client_id,
                    "username": record.username,
                    "us": record.us,
                    "connected_at": record.connected_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_connected": record.is_connected,
                    "agent_state": record.agent_state,
                }
                for record in sorted(self._clients.values(), key=lambda item: item.connected_at)
                if record.is_connected
            ]

            return {
                "conversation_round": round_count,
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "total_cached_tokens": cached_tokens,
                "cache_hit_rate": (cached_tokens / prompt_tokens * 100 if prompt_tokens > 0 else 0),
                "is_server_running": self.is_server_running,
                "current_clients": self.current_clients,
                "server_uptime": (datetime.now() - self.server_start_time).total_seconds(),
                "recent_interactions": interactions[-10:] if interactions else [],
                "agent_state": agent_state,
                "recent_logs": recent_logs,
                "clients": clients,
            }

    def export_log(self, log_dir: str, client_id: Optional[str] = None) -> str:
        import os

        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"vsens_log_{client_id}_{ts}.txt" if client_id else f"vsens_log_{ts}.txt"
        filepath = os.path.join(log_dir, filename)

        snapshot = self.get_stats_snapshot(client_id=client_id)
        sep = "=" * 80
        thin = "-" * 80
        lines = [
            sep,
            "  VSENS AGENT SESSION LOG",
            sep,
            f"  Exported at     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Conv. rounds    : {snapshot['conversation_round']}",
            f"  Total tokens    : {snapshot['total_tokens']:,}",
            f"    Prompt        : {snapshot['total_prompt_tokens']:,}",
            f"    Completion    : {snapshot['total_completion_tokens']:,}",
            f"    Cached        : {snapshot['total_cached_tokens']:,}",
            f"  Cache hit rate  : {snapshot['cache_hit_rate']:.1f}%",
            sep,
            "",
            "INTERACTIONS",
            thin,
        ]

        if snapshot["recent_interactions"]:
            for index, record in enumerate(snapshot["recent_interactions"], 1):
                lines.extend([
                    f"[{index}] {record.timestamp.strftime('%Y-%m-%d %H:%M:%S')}  type={record.interaction_type}  tokens={record.total_tokens:,}  cached={record.cached_tokens:,}",
                    f"CLIENT: {record.client_id or 'n/a'}  USERNAME: {record.username or 'n/a'}  US: {record.us or 'n/a'}",
                    f"USER : {record.user_input}",
                    f"AGENT: {record.agent_reply}",
                    thin,
                ])
        else:
            lines.append("(no interactions recorded)")

        lines.extend(["", "SERVER / AGENT LOG", thin])
        lines.extend(snapshot["recent_logs"] if snapshot["recent_logs"] else ["(empty)"])
        lines.append(sep)

        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        return filepath


monitor_stats = MonitorStats()


class MonitorLogHandler(logging.Handler):
    """Attach to any logger to forward records into monitor_stats log buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            monitor_stats.add_log(msg)
        except Exception:
            pass


def install_log_handler(level: int = logging.DEBUG) -> None:
    """
    Install the MonitorLogHandler on the root logger so all module loggers
    feed into the GUI log panel automatically.
    """
    handler = MonitorLogHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
