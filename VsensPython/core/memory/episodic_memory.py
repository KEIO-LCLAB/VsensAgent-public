"""
core/memory/episodic_memory.py
LanceDB-backed episodic store.

Each interaction is saved as a vector-embedded record so that past episodes
can be retrieved by semantic similarity at prompt-build time.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import lancedb
    import pyarrow as pa
except Exception as exc:
    lancedb = None
    pa = None
    logger.warning("[EpisodicMemory] LanceDB import failed, using in-memory fallback store: %s", exc)

# Embedding dimension for text-embedding-3-small
_EMBED_DIM = 1536

# Arrow schema — LanceDB requires an explicit schema for vector columns.
_SCHEMA = None if pa is None else pa.schema([
    pa.field("session_id",      pa.string()),
    pa.field("timestamp",       pa.string()),
    pa.field("user_input",      pa.string()),
    pa.field("agent_reply",     pa.string()),
    pa.field("scene_summary",   pa.string()),
    pa.field("control_actions", pa.string()),
    pa.field("embedding",       pa.list_(pa.float32(), _EMBED_DIM)),
])


def _compact_scene(snapshot: dict) -> str:
    """
    Strip position / rotation / size / scale; keep only the semantically
    meaningful fields per object.

    Unity scene snapshot schema (relevant fields):
      Regular objects : state, availableStates, properties
      Sensor objects  : properties, attachTo,
                        sensor.sensorType, sensor.value  (if present)

    Yields ~80 % token reduction vs. the full snapshot.
    """
    compact = {}
    for name, obj in snapshot.items():
        if not isinstance(obj, dict):
            compact[name] = obj
            continue
        entry: dict = {}
        if "state" in obj:
            entry["state"] = obj["state"]
        if "properties" in obj:
            entry["properties"] = obj["properties"]
        if "attachTo" in obj:
            entry["attachTo"] = obj["attachTo"]
        # Nested sensor block (Unity SensorObjectDescriber format)
        sensor_block = obj.get("sensor")
        if isinstance(sensor_block, dict):
            sensor_entry: dict = {}
            if "sensorType" in sensor_block:
                sensor_entry["sensorType"] = sensor_block["sensorType"]
            if "value" in sensor_block:
                sensor_entry["value"] = sensor_block["value"]
            if sensor_entry:
                entry["sensor"] = sensor_entry
        compact[name] = entry if entry else {}
    return json.dumps(compact, separators=(",", ":"))


class EpisodicMemory:
    """
    Stores interaction episodes in a local LanceDB table and retrieves
    the most semantically similar ones for a given query.

    Parameters
    ----------
    db_path      : Directory path for the LanceDB database.
    openai_client: An openai.OpenAI instance used for embeddings.
    """

    TABLE_NAME = "episodes"

    def __init__(self, db_path: str, openai_client):
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self.client = openai_client
        self.db = None
        if lancedb is None or pa is None:
            logger.warning("[EpisodicMemory] LanceDB unavailable, using in-memory fallback store.")
            self._table = _InMemoryEpisodeTable()
            return

        self.db = lancedb.connect(db_path)
        self._table = self._open_or_create_table()

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _open_or_create_table(self):
        tables = self.db.table_names()
        if self.TABLE_NAME in tables:
            return self.db.open_table(self.TABLE_NAME)
        logger.info("[EpisodicMemory] Creating new LanceDB table '%s'.", self.TABLE_NAME)
        return self.db.create_table(self.TABLE_NAME, schema=_SCHEMA)

    # ------------------------------------------------------------------
    # Embedding helper
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return resp.data[0].embedding

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        session_id: str,
        user_input: str,
        agent_reply: str,
        scene_snapshot: dict,
        control_actions: list[dict],
    ) -> None:
        """Embed and persist one interaction episode."""
        try:
            text_to_embed = f"{user_input} {agent_reply}"
            embedding = self._embed(text_to_embed)
            row = {
                "session_id":      session_id,
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                "user_input":      user_input,
                "agent_reply":     agent_reply,
                "scene_summary":   _compact_scene(scene_snapshot),
                "control_actions": json.dumps(control_actions, separators=(",", ":")),
                "embedding":       [float(x) for x in embedding],
            }
            self._table.add([row])
            logger.debug("[EpisodicMemory] Stored episode for session %s.", session_id[:8])
        except Exception as exc:
            logger.warning("[EpisodicMemory] store() failed: %s", exc)

    def retrieve(self, query: str, n: int = 3, max_distance: float = 0.8) -> list[dict]:
        """
        Return the *n* most relevant past episodes for *query*.

        Only episodes whose L2 distance to the query embedding is ≤ max_distance
        are returned.  This prevents irrelevant past episodes from being injected
        as context as the memory grows over many sessions.

        Rough cosine-similarity equivalents for normalized embeddings:
          max_distance=0.6  →  cosine ≥ ~0.82  (very similar)
          max_distance=0.8  →  cosine ≥ ~0.68  (clearly related)  ← default
          max_distance=1.0  →  cosine ≥ ~0.50  (loosely related)

        Each result is a plain dict with all schema fields.
        Returns an empty list on any error.
        """
        try:
            # Check if table has data
            if self._table.count_rows() == 0:
                return []
            embedding = self._embed(query)
            results = (
                self._table
                .search(embedding)
                .limit(n)
                .to_list()
            )
            # Filter out low-similarity results — without this, LanceDB always
            # returns exactly n rows regardless of relevance, which injects noise
            # as the episode store accumulates across sessions.
            filtered = [r for r in results if r.get("_distance", 9999) <= max_distance]
            if len(results) != len(filtered):
                logger.debug(
                    "[EpisodicMemory] retrieve: %d/%d candidates passed distance filter (≤%.2f).",
                    len(filtered), len(results), max_distance,
                )
            return filtered
        except Exception as exc:
            logger.warning("[EpisodicMemory] retrieve() failed: %s", exc)
            return []

    def count(self) -> int:
        """Return the total number of stored episodes."""
        try:
            return self._table.count_rows()
        except Exception:
            return 0


class _InMemoryEpisodeQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._limit = len(rows)

    def limit(self, value: int):
        self._limit = value
        return self

    def to_list(self) -> list[dict]:
        return list(self._rows[:self._limit])


class _InMemoryEpisodeTable:
    def __init__(self):
        self._rows: list[dict] = []

    def add(self, rows: list[dict]) -> None:
        self._rows.extend(rows)

    def count_rows(self) -> int:
        return len(self._rows)

    def search(self, _embedding: list[float]) -> _InMemoryEpisodeQuery:
        return _InMemoryEpisodeQuery(self._rows)
