"""
core/perception/perception_config.py

Loads VsensPython/config/perception.yaml once at startup and:
  1. Patches the module-level threshold constants in scene_diff and
     event_classifier so all downstream calls use the configured values.
  2. Exposes a module-level ``cfg`` singleton with typed attributes consumed
     by HeartbeatHandler (cooldown, TTS, interval_s).

Usage
-----
Import once before any perception module is used (done in vsens_server.py):

    from core.perception.perception_config import cfg, load as load_perception_config
    load_perception_config()          # patches, prints summary

After that, every other import of scene_diff / event_classifier sees the
updated constants automatically.
"""
from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "perception.yaml"


# -----------------------------------------------------------------------
# Typed config dataclass
# -----------------------------------------------------------------------

@dataclass
class _HeartbeatCfg:
    interval_s: float = 5.0
    snapshot_mode: str = "full"

@dataclass
class _DiffCfg:
    continuous_abs_threshold: float = 0.10
    continuous_rel_threshold: float = 0.20
    sensor_anomaly_rel_threshold: float = 0.50
    user_proximity_threshold_m: float = 0.50

@dataclass
class _AttentionCfg:
    threshold: float = 0.5
    severity: dict = field(default_factory=lambda: {
        "SENSOR_TRIGGER": 0.8,
        "SENSOR_ANOMALY": 0.7,
        "STATE_CHANGE":   0.6,
        "OBJECT_ADDED":   0.5,
        "OBJECT_REMOVED": 0.5,
        "USER_PROXIMITY": 0.4,
        "NO_OP":          0.0,
    })

@dataclass
class _CooldownCfg:
    enabled: bool = True
    per_object_s: float = 10.0

@dataclass
class _AgentPushCfg:
    tts_enabled: bool = False
    tts_voice: str = "alloy"

@dataclass
class PerceptionConfig:
    heartbeat: _HeartbeatCfg = field(default_factory=_HeartbeatCfg)
    diff: _DiffCfg = field(default_factory=_DiffCfg)
    attention: _AttentionCfg = field(default_factory=_AttentionCfg)
    cooldown: _CooldownCfg = field(default_factory=_CooldownCfg)
    agent_push: _AgentPushCfg = field(default_factory=_AgentPushCfg)


# Module-level singleton — always has defaults, overwritten by load()
cfg = PerceptionConfig()


# -----------------------------------------------------------------------
# Loader
# -----------------------------------------------------------------------

def load(config_path: Path | str | None = None) -> PerceptionConfig:
    """
    Load perception.yaml and apply to the module singleton.

    Also patches module-level threshold constants in ``scene_diff`` and
    ``event_classifier`` so downstream calls use the configured values.

    Safe to call multiple times (idempotent — last call wins).
    """
    global cfg
    path = Path(config_path) if config_path else _CONFIG_PATH

    raw: dict = {}
    if path.exists():
        try:
            import yaml
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            logger.info("[PerceptionConfig] Loaded %s", path)
        except Exception as exc:
            logger.warning(
                "[PerceptionConfig] Failed to load %s: %s — using defaults.", path, exc
            )
    else:
        logger.warning(
            "[PerceptionConfig] Config file not found at %s — using defaults.", path
        )

    # Build the typed config from raw dict
    hb_raw  = raw.get("heartbeat",  {})
    diff_raw = raw.get("diff",      {})
    att_raw  = raw.get("attention", {})
    cd_raw   = raw.get("cooldown",  {})
    ap_raw   = raw.get("agent_push", {})

    cfg = PerceptionConfig(
        heartbeat=_HeartbeatCfg(
            interval_s=float(hb_raw.get("interval_s", 5.0)),
            snapshot_mode=str(hb_raw.get("snapshot_mode", "full")),
        ),
        diff=_DiffCfg(
            continuous_abs_threshold=float(diff_raw.get("continuous_abs_threshold", 0.10)),
            continuous_rel_threshold=float(diff_raw.get("continuous_rel_threshold", 0.20)),
            sensor_anomaly_rel_threshold=float(diff_raw.get("sensor_anomaly_rel_threshold", 0.50)),
            user_proximity_threshold_m=float(diff_raw.get("user_proximity_threshold_m", 0.50)),
        ),
        attention=_AttentionCfg(
            threshold=float(att_raw.get("threshold", 0.5)),
            severity={**PerceptionConfig.__dataclass_fields__["attention"].default_factory().severity,
                      **att_raw.get("severity", {})},
        ),
        cooldown=_CooldownCfg(
            enabled=bool(cd_raw.get("enabled", True)),
            per_object_s=float(cd_raw.get("per_object_s", 10.0)),
        ),
        agent_push=_AgentPushCfg(
            tts_enabled=bool(ap_raw.get("tts_enabled", False)),
            tts_voice=str(ap_raw.get("tts_voice", "alloy")),
        ),
    )

    # ── Patch module-level constants ──────────────────────────────────────────
    _patch_scene_diff(cfg.diff)
    _patch_event_classifier(cfg.diff, cfg.attention)

    logger.info(
        "[PerceptionConfig] heartbeat=%.1fs | threshold=%.2f | "
        "cooldown=%s %.1fs | tts=%s",
        cfg.heartbeat.interval_s,
        cfg.attention.threshold,
        "on" if cfg.cooldown.enabled else "off",
        cfg.cooldown.per_object_s,
        "on" if cfg.agent_push.tts_enabled else "off",
    )
    return cfg


# -----------------------------------------------------------------------
# Module patcher helpers
# -----------------------------------------------------------------------

def _patch_scene_diff(diff: _DiffCfg) -> None:
    """Overwrite threshold constants in core.perception.scene_diff."""
    try:
        import core.perception.scene_diff as _sd
        _sd._CONTINUOUS_ABS_THRESHOLD = diff.continuous_abs_threshold
        _sd._CONTINUOUS_REL_THRESHOLD = diff.continuous_rel_threshold
    except Exception as exc:
        logger.warning("[PerceptionConfig] Could not patch scene_diff: %s", exc)


def _patch_event_classifier(diff: _DiffCfg, att: _AttentionCfg) -> None:
    """Overwrite threshold constants in core.perception.event_classifier."""
    try:
        import core.perception.event_classifier as _ec
        _ec.ATTENTION_THRESHOLD             = att.threshold
        _ec.USER_PROXIMITY_THRESHOLD_M      = diff.user_proximity_threshold_m
        _ec.SENSOR_ANOMALY_REL_THRESHOLD    = diff.sensor_anomaly_rel_threshold
        _ec.DEFAULT_SEVERITY.update(att.severity)
    except Exception as exc:
        logger.warning("[PerceptionConfig] Could not patch event_classifier: %s", exc)
