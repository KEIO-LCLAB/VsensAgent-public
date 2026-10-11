from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path


def analyze_recordings(
    *,
    recording_paths: list[str],
    recording_keys: list[str],
    analysis_focus: str = "har_evidence",
    analysis_scope: list[str] | None = None,
    scene_context: dict | None = None,
) -> dict:
    if not recording_paths:
        raise ValueError("recording_paths must not be empty")

    scope = set(analysis_scope or ["descriptive_stats", "change_point", "anomaly"])
    recording_summaries: list[dict] = []
    all_sensor_names: list[str] = []
    all_scores: list[float] = []
    recordings_with_evidence = 0

    for recording_key, recording_path in zip(recording_keys, recording_paths):
        summary = _analyze_recording(
            recording_key=recording_key,
            recording_path=Path(recording_path),
            scope=scope,
        )
        recording_summaries.append(summary)
        all_sensor_names.extend(summary["sensor_names"])
        all_scores.append(summary["har_score"])
        if summary["har_judgement"] in {"strong", "moderate"}:
            recordings_with_evidence += 1

    scene_context_summary, context_weight = _summarize_scene_context(
        scene_context=scene_context or {},
        sensor_names=all_sensor_names,
    )
    overall_score = max(all_scores) if all_scores else 0.0
    overall_score = min(1.0, overall_score + context_weight)
    har_judgement = _score_to_judgement(overall_score)
    aggregate_findings = _build_aggregate_findings(
        recording_summaries=recording_summaries,
        recordings_with_evidence=recordings_with_evidence,
        scene_context_summary=scene_context_summary,
        scope=scope,
    )
    summary = _build_summary_text(
        analysis_focus=analysis_focus,
        har_judgement=har_judgement,
        recording_count=len(recording_summaries),
        recordings_with_evidence=recordings_with_evidence,
    )
    reply = _build_reply_text(
        summary=summary,
        scene_context_summary=scene_context_summary,
        aggregate_findings=aggregate_findings,
    )

    return {
        "reply": reply,
        "summary": summary,
        "har_judgement": har_judgement,
        "recording_count": len(recording_summaries),
        "recording_keys": recording_keys,
        "recording_summaries": recording_summaries,
        "aggregate_findings": aggregate_findings,
        "scene_context_summary": scene_context_summary,
        "analysis_scope": sorted(scope),
        "analysis_focus": analysis_focus,
        "artifacts": [],
    }


def _analyze_recording(*, recording_key: str, recording_path: Path, scope: set[str]) -> dict:
    if not recording_path.exists() or not recording_path.is_dir():
        raise FileNotFoundError(f"Recording directory not found: {recording_path}")

    sensor_summaries: list[dict] = []
    csv_paths = sorted(recording_path.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No CSV files found in recording directory: {recording_path}")

    for csv_path in csv_paths:
        sensor_summaries.append(_analyze_sensor_csv(csv_path=csv_path, scope=scope))

    har_score = max((sensor["har_score"] for sensor in sensor_summaries), default=0.0)
    har_judgement = _score_to_judgement(har_score)

    return {
        "recording_key": recording_key,
        "recording_path": str(recording_path),
        "sensor_count": len(sensor_summaries),
        "sensor_names": [sensor["sensor_name"] for sensor in sensor_summaries],
        "sensor_summaries": sensor_summaries,
        "har_score": round(har_score, 3),
        "har_judgement": har_judgement,
    }


def _analyze_sensor_csv(*, csv_path: Path, scope: set[str]) -> dict:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"CSV file is empty: {csv_path}")

    fieldnames = rows[0].keys()
    sensor_name = (rows[0].get("tag") or csv_path.stem.split("_")[0]).strip() or csv_path.stem
    numeric_columns = [
        name for name in fieldnames
        if name not in {"tag", "phase"} and _column_is_numeric(rows, name)
    ]
    primary_column, primary_values = _select_primary_series(rows, numeric_columns)
    time_values = _extract_numeric_series(rows, "time") if "time" in fieldnames else []

    descriptive_stats = _build_descriptive_stats(rows, numeric_columns, time_values)
    phase_stats = _build_phase_stats(rows, primary_column) if "phase" in fieldnames else None
    anomaly_findings, har_score = _detect_findings(primary_values)
    findings: list[str] = []
    if "descriptive_stats" in scope:
        findings.append(
            f"{sensor_name} captured {descriptive_stats['sample_count']} samples over "
            f"{descriptive_stats['duration_s']:.2f}s using primary signal `{primary_column}`."
        )
    if phase_stats and phase_stats["phase_count"] > 0:
        findings.append(
            f"{sensor_name} includes phase-labeled samples for "
            f"{', '.join(sorted(phase_stats['phases'].keys()))}."
        )
        if phase_stats["threshold_candidates"]:
            candidate = phase_stats["threshold_candidates"][0]
            findings.append(
                f"A candidate `{primary_column}` threshold between `{candidate['lower_phase']}` "
                f"and `{candidate['upper_phase']}` is {candidate['threshold']:.3f}."
            )
    if "change_point" in scope and anomaly_findings["abrupt_change_count"] > 0:
        findings.append(
            f"{sensor_name} shows {anomaly_findings['abrupt_change_count']} abrupt change points "
            f"(largest step {anomaly_findings['largest_step']:.3f})."
        )
    if "anomaly" in scope:
        if anomaly_findings["saturation_ratio"] >= 0.15:
            findings.append(
                f"{sensor_name} spends {anomaly_findings['saturation_ratio'] * 100:.1f}% of samples near saturation, "
                "which may indicate occlusion, max-range clipping, or a prolonged extreme state."
            )
        if anomaly_findings["stable_ratio"] >= 0.85:
            findings.append(
                f"{sensor_name} remains nearly constant for {anomaly_findings['stable_ratio'] * 100:.1f}% of adjacent samples."
            )

    if not findings:
        findings.append(f"{sensor_name} does not show strong temporal evidence beyond baseline fluctuation.")

    return {
        "sensor_name": sensor_name,
        "file_name": csv_path.name,
        "primary_column": primary_column,
        "descriptive_stats": descriptive_stats,
        "phase_stats": phase_stats or {"phase_count": 0, "phases": {}, "threshold_candidates": []},
        "anomaly_metrics": anomaly_findings,
        "findings": findings,
        "har_score": round(har_score, 3),
    }


def _build_phase_stats(rows: list[dict], primary_column: str) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        phase = (row.get("phase") or "").strip()
        if not phase:
            continue
        grouped.setdefault(phase, []).append(row)

    phases: dict[str, dict] = {}
    for phase, phase_rows in grouped.items():
        values = _extract_numeric_series(phase_rows, primary_column)
        times = _extract_numeric_series(phase_rows, "time")
        if not values:
            phases[phase] = {
                "sample_count": len(phase_rows),
                "duration_s": max(times) - min(times) if len(times) >= 2 else 0.0,
                "primary_column": primary_column,
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
            }
            continue
        phases[phase] = {
            "sample_count": len(phase_rows),
            "duration_s": max(times) - min(times) if len(times) >= 2 else 0.0,
            "primary_column": primary_column,
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
            "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        }

    threshold_candidates: list[dict] = []
    phase_items = [
        (phase, stats)
        for phase, stats in phases.items()
        if stats.get("mean") is not None
    ]
    phase_items.sort(key=lambda item: item[1]["mean"])
    for (lower_phase, lower_stats), (upper_phase, upper_stats) in zip(phase_items, phase_items[1:]):
        lower_max = lower_stats.get("max")
        upper_min = upper_stats.get("min")
        if lower_max is None or upper_min is None:
            continue
        threshold = (float(lower_max) + float(upper_min)) / 2.0
        separation = float(upper_stats["mean"]) - float(lower_stats["mean"])
        threshold_candidates.append(
            {
                "primary_column": primary_column,
                "lower_phase": lower_phase,
                "upper_phase": upper_phase,
                "threshold": threshold,
                "separation": separation,
            }
        )

    threshold_candidates.sort(key=lambda item: abs(item["separation"]), reverse=True)
    return {
        "phase_count": len(phases),
        "phases": phases,
        "threshold_candidates": threshold_candidates,
    }


def _build_descriptive_stats(rows: list[dict], numeric_columns: list[str], time_values: list[float]) -> dict:
    stats = {
        "sample_count": len(rows),
        "duration_s": max(time_values) - min(time_values) if len(time_values) >= 2 else 0.0,
        "missing_values": 0,
        "columns": {},
    }
    for column in numeric_columns:
        values = _extract_numeric_series(rows, column)
        stats["missing_values"] += len(rows) - len(values)
        if not values:
            continue
        stats["columns"][column] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
            "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        }
    return stats


def _detect_findings(primary_values: list[float]) -> tuple[dict, float]:
    if len(primary_values) < 2:
        return {
            "range": 0.0,
            "std": 0.0,
            "largest_step": 0.0,
            "abrupt_change_count": 0,
            "stable_ratio": 1.0,
            "saturation_ratio": 0.0,
        }, 0.0

    value_range = max(primary_values) - min(primary_values)
    std = statistics.pstdev(primary_values) if len(primary_values) > 1 else 0.0
    deltas = [abs(curr - prev) for prev, curr in zip(primary_values, primary_values[1:])]
    median_delta = statistics.median(deltas) if deltas else 0.0
    largest_step = max(deltas) if deltas else 0.0
    delta_threshold = max(value_range * 0.2, median_delta * 4.0, std * 1.5, 1e-4)
    abrupt_change_count = sum(1 for delta in deltas if delta >= delta_threshold)
    stable_epsilon = max(value_range * 0.01, 1e-4)
    stable_ratio = (
        sum(1 for delta in deltas if delta <= stable_epsilon) / len(deltas)
        if deltas else 1.0
    )
    observed_max = max(primary_values)
    saturation_ratio = (
        sum(1 for value in primary_values if value >= observed_max * 0.995) / len(primary_values)
        if observed_max > 0 else 0.0
    )

    score = 0.0
    if value_range > 0:
        score += min(0.45, value_range / (abs(statistics.fmean(primary_values)) + 1e-6) * 0.2)
    score += min(0.35, abrupt_change_count * 0.12)
    score += min(0.15, std * 0.05)
    if stable_ratio < 0.8:
        score += 0.15
    if saturation_ratio >= 0.15:
        score += 0.1

    return {
        "range": value_range,
        "std": std,
        "largest_step": largest_step,
        "abrupt_change_count": abrupt_change_count,
        "stable_ratio": stable_ratio,
        "saturation_ratio": saturation_ratio,
    }, min(1.0, score)


def _select_primary_series(rows: list[dict], numeric_columns: list[str]) -> tuple[str, list[float]]:
    lower_names = {name.lower(): name for name in numeric_columns}
    if {"ax", "ay", "az"} <= set(lower_names):
        ax = _extract_numeric_series(rows, lower_names["ax"])
        ay = _extract_numeric_series(rows, lower_names["ay"])
        az = _extract_numeric_series(rows, lower_names["az"])
        length = min(len(ax), len(ay), len(az))
        return "acceleration_magnitude", [
            math.sqrt(ax[i] ** 2 + ay[i] ** 2 + az[i] ** 2)
            for i in range(length)
        ]

    for preferred in ("d", "distance", "value", "v", "magnitude"):
        if preferred in lower_names:
            column = lower_names[preferred]
            return column, _extract_numeric_series(rows, column)

    if not numeric_columns:
        raise ValueError("No numeric columns found in CSV")

    column = numeric_columns[0]
    return column, _extract_numeric_series(rows, column)


def _extract_numeric_series(rows: list[dict], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(column)
        if raw in (None, ""):
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def _column_is_numeric(rows: list[dict], column: str) -> bool:
    for row in rows[:20]:
        raw = row.get(column)
        if raw in (None, ""):
            continue
        try:
            float(raw)
            return True
        except (TypeError, ValueError):
            return False
    return False


def _summarize_scene_context(*, scene_context: dict, sensor_names: list[str]) -> tuple[str, float]:
    if not scene_context:
        return (
            "No scene layout context was available, so the HAR judgement is based only on temporal sensor patterns.",
            0.0,
        )

    sensor_objects: list[str] = []
    matched_sensor_objects: list[str] = []
    for object_name, payload in scene_context.items():
        if not isinstance(payload, dict):
            continue
        raw_state = payload.get("state")
        state = raw_state if isinstance(raw_state, dict) else {}
        if payload.get("sensor") is not None or state.get("sensor_type"):
            sensor_objects.append(object_name)
            if object_name in sensor_names:
                matched_sensor_objects.append(object_name)

    if matched_sensor_objects:
        return (
            "Scene context is available and includes matching sensor objects: "
            + ", ".join(sorted(set(matched_sensor_objects)))
            + ". This makes the HAR judgement more spatially grounded.",
            0.08,
        )

    return (
        f"Scene context is available with {len(scene_context)} objects. "
        "The HAR judgement uses room layout context, but this pass did not confirm an exact sensor-object match in the scene snapshot.",
        0.03,
    )


def _build_aggregate_findings(
    *,
    recording_summaries: list[dict],
    recordings_with_evidence: int,
    scene_context_summary: str,
    scope: set[str],
) -> list[str]:
    findings = [
        f"{recordings_with_evidence}/{len(recording_summaries)} recordings show at least moderate HAR evidence."
    ]
    if "anomaly" in scope:
        sensor_findings = []
        for recording in recording_summaries:
            for sensor in recording["sensor_summaries"]:
                anomaly = sensor["anomaly_metrics"]
                if anomaly["abrupt_change_count"] > 0 or anomaly["saturation_ratio"] >= 0.15:
                    sensor_findings.append(sensor["sensor_name"])
        if sensor_findings:
            findings.append(
                "The strongest temporal anomalies appear on sensors: "
                + ", ".join(sorted(set(sensor_findings[:6])))
                + "."
            )
    phase_findings = []
    for recording in recording_summaries:
        for sensor in recording["sensor_summaries"]:
            phase_stats = sensor.get("phase_stats") or {}
            if int(phase_stats.get("phase_count") or 0) <= 0:
                continue
            phase_findings.append(sensor["sensor_name"])
            candidates = phase_stats.get("threshold_candidates") or []
            if candidates:
                candidate = candidates[0]
                findings.append(
                    f"{sensor['sensor_name']} has phase-labeled data; candidate "
                    f"{candidate['primary_column']} threshold between {candidate['lower_phase']} "
                    f"and {candidate['upper_phase']} is {candidate['threshold']:.3f}."
                )
                break
        if any("phase-labeled" in finding for finding in findings):
            break
    if phase_findings and not any("phase-labeled" in finding for finding in findings):
        findings.append(
            "Phase-labeled data is available on sensors: "
            + ", ".join(sorted(set(phase_findings[:6])))
            + "."
        )
    findings.append(scene_context_summary)
    return findings


def _build_summary_text(
    *,
    analysis_focus: str,
    har_judgement: str,
    recording_count: int,
    recordings_with_evidence: int,
) -> str:
    if analysis_focus == "har_evidence":
        return (
            f"I analyzed {recording_count} recording(s) for HAR evidence. "
            f"Overall evidence strength is {har_judgement}, with {recordings_with_evidence} recording(s) showing at least moderate support."
        )
    return (
        f"I analyzed {recording_count} recording(s). "
        f"Overall evidence strength is {har_judgement}."
    )


def _build_reply_text(*, summary: str, scene_context_summary: str, aggregate_findings: list[str]) -> str:
    detail_lines = aggregate_findings
    return "\n".join([summary, scene_context_summary, *detail_lines])


def _score_to_judgement(score: float) -> str:
    if score >= 0.7:
        return "strong"
    if score >= 0.35:
        return "moderate"
    return "weak"
