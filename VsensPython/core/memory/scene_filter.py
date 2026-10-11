"""
core/memory/scene_filter.py
Filters a scene snapshot to the objects most semantically relevant to the
current user query, reducing prompt token usage for focused conversations.

Implements Token Strategy C from RECONSTRUCT_PLAN.md Section 10.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default number of objects to keep in the filtered scene
_DEFAULT_TOP_K = 15


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot-product cosine similarity — pure Python, no external dependencies."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(x ** 2 for x in b) ** 0.5
    return dot / (norm_a * norm_b + 1e-9)


def _object_description(name: str, obj: dict) -> str:
    """
    Build a short text description of a scene object for embedding.

    Uses semantically meaningful fields only — transforms are ignored.
    Handles the Unity nested sensor format (obj["sensor"]["sensorType"]).

    Examples:
      "Window_A: state=open, properties=[with_state, movable]"
      "DISTANCE-01: sensorType=DISTANCE, value=1.23, attachTo=Wall_A"
      "IMU-01: sensorType=IMU, attachTo=Wrist_L"
    """
    if not isinstance(obj, dict):
        return f"{name}: {obj}"

    parts: list[str] = []

    # Regular object state
    if "state" in obj:
        parts.append(f"state={obj['state']}")

    # Properties tag list
    props = obj.get("properties")
    if props:
        parts.append(f"properties=[{', '.join(props)}]")

    # Attachment relationship
    if "attachTo" in obj:
        parts.append(f"attachTo={obj['attachTo']}")

    # Sensor-specific data (Unity nested format)
    sensor_block = obj.get("sensor")
    if isinstance(sensor_block, dict):
        if "sensorType" in sensor_block:
            parts.append(f"sensorType={sensor_block['sensorType']}")
        if "value" in sensor_block:
            parts.append(f"value={sensor_block['value']}")

    desc = name
    if parts:
        desc += ": " + ", ".join(parts)
    return desc


class SceneFilter:
    """
    Re-embeds scene objects on change and returns a relevance-filtered
    snapshot for any given user query.

    Parameters
    ----------
    openai_client : An openai.OpenAI instance used for embeddings.
    """

    def __init__(self, openai_client):
        self.client = openai_client
        # name → embedding list[float]
        self._object_embeddings: dict[str, list[float]] = {}
        # name → description text (cached to detect changes without re-embedding)
        self._object_descriptions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return resp.data[0].embedding

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single API call (cheaper + faster)."""
        if not texts:
            return []
        resp = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_embeddings(self, scene: dict) -> None:
        """
        Re-embed only new or changed objects.
        Called by MemoryManager whenever the scene is updated.
        """
        to_embed_names: list[str] = []
        to_embed_texts: list[str] = []

        for name, obj in scene.items():
            desc = _object_description(name, obj)
            if name not in self._object_descriptions or self._object_descriptions[name] != desc:
                to_embed_names.append(name)
                to_embed_texts.append(desc)

        if not to_embed_names:
            return

        try:
            embeddings = self._embed_batch(to_embed_texts)
            for name, desc, emb in zip(to_embed_names, to_embed_texts, embeddings):
                self._object_embeddings[name] = emb
                self._object_descriptions[name] = desc
            logger.debug("[SceneFilter] Re-embedded %d objects.", len(to_embed_names))
        except Exception as exc:
            logger.warning("[SceneFilter] update_embeddings failed: %s", exc)

    def filter(
        self,
        scene: dict,
        query: str,
        top_k: int = _DEFAULT_TOP_K,
    ) -> dict:
        """
        Return a subset of *scene* containing the *top_k* most semantically
        relevant objects.  Objects explicitly named in *query* are always
        included.  Falls back to the full scene if embeddings are not yet
        available.

        Parameters
        ----------
        scene  : Full current scene snapshot.
        query  : The user's input text.
        top_k  : Maximum number of objects to include.

        Returns
        -------
        dict : Filtered scene snapshot (subset of *scene*).
        """
        if not self._object_embeddings:
            logger.debug("[SceneFilter] No embeddings available yet — returning full scene.")
            return scene

        try:
            query_emb = self._embed(query)

            # Always include objects whose names appear verbatim in the query
            query_lower = query.lower()
            pinned: set[str] = {
                name for name in scene
                if name.lower() in query_lower
            }

            # Score the remaining objects
            scored: list[tuple[str, float]] = []
            for name, obj_emb in self._object_embeddings.items():
                if name in scene and name not in pinned:
                    score = _cosine_similarity(query_emb, obj_emb)
                    scored.append((name, score))

            # Take top_k minus the pinned count
            remaining_slots = max(0, top_k - len(pinned))
            top_names = {n for n, _ in sorted(scored, key=lambda x: -x[1])[:remaining_slots]}
            keep = pinned | top_names

            filtered = {k: v for k, v in scene.items() if k in keep}
            logger.debug(
                "[SceneFilter] Filtered %d → %d objects (pinned=%d).",
                len(scene), len(filtered), len(pinned),
            )
            return filtered

        except Exception as exc:
            logger.warning("[SceneFilter] filter() failed, returning full scene: %s", exc)
            return scene
