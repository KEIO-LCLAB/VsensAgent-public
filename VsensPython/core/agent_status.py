"""
core/agent_status.py
AgentStatusBroadcaster centralizes agent state and pushes agent_status
messages to the owning Unity client on every transition.
"""
import logging
from typing import Callable, Coroutine, Optional

from monitor_stats import monitor_stats

logger = logging.getLogger(__name__)

IDLE = "idle"
LISTENING = "listening"
TRANSCRIBING = "transcribing"
THINKING = "thinking"
PLANNING = "planning"
EXECUTING = "executing"
SPEAKING = "speaking"
WAITING = "waiting"
SCRIPTING = "scripting"
WAITING_SUBAGENT = "waiting_subagent"

_VALID_STATES = frozenset({
    IDLE, LISTENING, TRANSCRIBING, THINKING,
    PLANNING, EXECUTING, SPEAKING, WAITING, SCRIPTING, WAITING_SUBAGENT,
})


class AgentStatusBroadcaster:
    def __init__(self, broadcast_fn: Callable[[dict], Coroutine], client_id: Optional[str] = None):
        self._broadcast_fn = broadcast_fn
        self._current_state: str = IDLE
        self._current_detail: str = ""
        self._client_id = client_id

    async def set_state(
        self,
        state: str,
        detail: str = "",
        plan_step: Optional[dict] = None,
    ) -> None:
        if state not in _VALID_STATES:
            logger.warning("[AgentStatus] Unknown state '%s' - ignoring.", state)
            return

        normalized_detail = detail or ""
        if state == self._current_state and normalized_detail == self._current_detail:
            return

        self._current_state = state
        self._current_detail = normalized_detail
        message: dict = {"type": "agent_status", "state": state}
        if normalized_detail:
            message["detail"] = normalized_detail
        if plan_step is not None:
            message["plan_step"] = plan_step

        logger.debug("[AgentStatus] -> %s  detail=%r", state, detail)
        monitor_stats.set_agent_state(state, client_id=self._client_id)
        monitor_stats.add_log(
            f"[AgentStatus] -> {state}" + (f"  {detail}" if detail else ""),
            client_id=self._client_id,
        )

        try:
            await self._broadcast_fn(message)
        except Exception as exc:
            logger.warning("[AgentStatus] Broadcast failed: %s", exc)

    @property
    def current_state(self) -> str:
        return self._current_state

    async def reset(self) -> None:
        self._current_state = ""
        self._current_detail = ""
        await self.set_state(IDLE)
