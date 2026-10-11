"""
core/memory/memory_manager.py
Single entry-point for all memory operations.

Owns:
  - WorkingMemory   (passed in by AgentCore)
  - EpisodicMemory  (LanceDB-backed long-term store)
  - SemanticMemory  (YAML knowledge files)
  - SceneFilter     (relevance-based scene truncation)

Builds the memory-augmented context string injected before every LLM call.
"""
import logging

from core.memory.working_memory import WorkingMemory
from core.memory.episodic_memory import EpisodicMemory
from core.memory.semantic_memory import SemanticMemory
from core.memory.scene_filter import SceneFilter

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Combines all memory subsystems and provides two public operations:

      build_context(user_input)  →  str  (inject into prompt)
      store_interaction(...)     →  None (record after response)

    Parameters
    ----------
    working  : The shared WorkingMemory instance from AgentCore.
    episodic : EpisodicMemory wrapping the LanceDB table.
    semantic : SemanticMemory loaded from YAML files.
    scene_filter : SceneFilter for relevance-based scene truncation.
    """

    def __init__(
        self,
        working: WorkingMemory,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        scene_filter: SceneFilter,
    ):
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.scene_filter = scene_filter

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def build_context(self, user_input: str) -> str:
        """
        Return a context string to prepend to the user's message:
          1. Up to 3 relevant past episodes (from episodic retrieval)
          2. Active plan step from working memory (if any)
          3. Last 3 recent classified events from working memory

        An empty string is returned when there is nothing useful to add.
        """
        context_parts: list[str] = []

        # 1. Relevant past episodes
        try:
            episodes = self.episodic.retrieve(user_input, n=3)
            if episodes:
                context_parts.append("[Relevant past interactions]")
                for ep in episodes:
                    reply_preview = ep.get("agent_reply", "")[:120]
                    if len(ep.get("agent_reply", "")) > 120:
                        reply_preview += "..."
                    context_parts.append(
                        f'- User said: "{ep.get("user_input", "")}" → '
                        f'Agent replied: "{reply_preview}"'
                    )
        except Exception as exc:
            logger.warning("[MemoryManager] Episodic retrieve failed: %s", exc)

        # 2. Active plan step
        if self.working.active_plan:
            step = self.working.active_plan.get("current_step")
            if step:
                context_parts.append(f"[Active plan step: {step}]")

        # 3. Recent classified events
        if self.working.recent_events:
            recent = self.working.recent_events[-3:]
            context_parts.append("[Recent scene events]")
            for ev in recent:
                summary = ev.get("summary", str(ev))
                context_parts.append(f"- {summary}")

        return "\n".join(context_parts)

    # ------------------------------------------------------------------
    # Filtering scene
    # ------------------------------------------------------------------

    def get_filtered_scene(self, user_input: str, top_k: int = 15) -> dict:
        """
        Trigger embedding update for changed objects and return the
        relevance-filtered scene for *user_input*.
        """
        # Update only changed / new object embeddings
        self.scene_filter.update_embeddings(self.working.scene)
        return self.scene_filter.filter(self.working.scene, user_input, top_k=top_k)

    # ------------------------------------------------------------------
    # Storing interactions
    # ------------------------------------------------------------------

    def store_interaction(
        self,
        session_id: str,
        user_input: str,
        agent_reply: str,
        scene_snapshot: dict,
        control_actions: list[dict],
    ) -> None:
        """Persist the current interaction to episodic memory."""
        self.episodic.store(
            session_id=session_id,
            user_input=user_input,
            agent_reply=agent_reply,
            scene_snapshot=scene_snapshot,
            control_actions=control_actions,
        )
