from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path

from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIGNAL_COLUMNS = ["ex", "ey", "ez", "ax", "ay", "az", "lx", "ly", "lz"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test for OpenAI image generation using a door-mounted IMU recording."
    )
    parser.add_argument("--csv", type=Path, required=True, help="Path to the IMU CSV file.")
    parser.add_argument("--key", type=Path, default=None, help="Path to the OpenAI API key file.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path. Defaults to a timestamped file in the system temp directory.",
    )
    parser.add_argument(
        "--model",
        default="gpt-image-2",
        help="Image generation model. Default: gpt-image-2",
    )
    parser.add_argument(
        "--size",
        default="1024x1024",
        choices=["1024x1024", "1536x1024", "1024x1536", "auto"],
        help="Requested image size.",
    )
    parser.add_argument(
        "--quality",
        default="medium",
        choices=["low", "medium", "high", "auto"],
        help="Requested image quality.",
    )
    return parser.parse_args()


def load_api_key(explicit_key_path: Path | None) -> str:
    if explicit_key_path is not None:
        return explicit_key_path.read_text(encoding="utf-8").strip()
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env.vsensagent", override=False)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in the environment or .env.vsensagent.")
    return key


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def to_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def summarize_signal(values: list[float]) -> dict[str, float]:
    signal_min = min(values)
    signal_max = max(values)
    span = signal_max - signal_min
    mean = sum(values) / len(values)
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    return {
        "min": signal_min,
        "max": signal_max,
        "span": span,
        "mean": mean,
        "rms": rms,
    }


def summarize_csv(rows: list[dict[str, str]]) -> dict:
    if not rows:
        raise ValueError("CSV contains no data rows.")

    time_values = [to_float(row, "time") for row in rows]
    signals = {column: [to_float(row, column) for row in rows] for column in SIGNAL_COLUMNS}

    ey_values = signals["ey"]
    ey_deltas = [abs(ey_values[index] - ey_values[index - 1]) for index in range(1, len(ey_values))]
    peak_delta_index = ey_deltas.index(max(ey_deltas)) + 1 if ey_deltas else 0

    summary = {
        "rows": len(rows),
        "time_start": time_values[0],
        "time_end": time_values[-1],
        "duration_seconds": time_values[-1] - time_values[0],
        "dominant_rotation_axis": "ey",
        "dominant_rotation_span_deg": summarize_signal(ey_values)["span"],
        "peak_rotation_change_time": time_values[peak_delta_index],
        "signals": {column: summarize_signal(values) for column, values in signals.items()},
    }
    return summary


def build_prompt(csv_path: Path, summary: dict) -> str:
    signal_lines = []
    for column in SIGNAL_COLUMNS:
        signal = summary["signals"][column]
        signal_lines.append(
            f"- {column}: min {signal['min']:.3f}, max {signal['max']:.3f}, span {signal['span']:.3f}, mean {signal['mean']:.3f}, rms {signal['rms']:.3f}"
        )

    return f"""
Create a clean scientific visualization poster that summarizes a door-mounted IMU recording of one door opening and closing event.

This is a smoke test for image generation, so the output should look intentionally analytical rather than artistic.

Hard requirements:
- Square layout with a white background.
- Main title: "Door IMU Open/Close Trial".
- Subtitle: "Conceptual visualization generated from sensor statistics".
- Show a door icon or simple door outline with an IMU sensor attached to the door panel.
- Include three chart-like panels that resemble time-series plots for rotation, acceleration, and linear acceleration.
- Use blue/orange/green traces and axis labels that look like an engineering report.
- Add a small note that this is a model-generated conceptual figure, not a ground-truth plotted chart.
- Overall style: minimal, precise, publication-style, readable.

Recording metadata:
- Source file: {csv_path.name}
- Samples: {summary['rows']}
- Duration: {summary['duration_seconds']:.3f} seconds
- Time range: {summary['time_start']:.4f} to {summary['time_end']:.4f}
- Dominant rotation axis: {summary['dominant_rotation_axis']}
- Dominant rotation span: {summary['dominant_rotation_span_deg']:.3f} degrees
- Peak rotation change around time: {summary['peak_rotation_change_time']:.4f}

Signal summary:
{chr(10).join(signal_lines)}

The figure should visually imply:
- door starts nearly stationary
- a rapid swing event
- then settles into a new orientation

Do not make it photorealistic. Make it look like a polished research infographic or lab report figure.
""".strip()


def default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(tempfile.gettempdir()) / f"openai_image_smoketest_{timestamp}.png"


def write_metadata(output_path: Path, payload: dict) -> None:
    metadata_path = output_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    args = parse_args()
    key_path = args.key
    api_key = load_api_key(key_path)
    rows = load_rows(args.csv)
    summary = summarize_csv(rows)
    prompt = build_prompt(args.csv, summary)

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = OpenAI(api_key=api_key)
    result = client.images.generate(
        model=args.model,
        prompt=prompt,
        size=args.size,
        quality=args.quality,
    )

    image_base64 = result.data[0].b64_json
    output_path.write_bytes(__import__("base64").b64decode(image_base64))

    metadata = {
        "csv_path": str(args.csv),
        "key_path": str(key_path),
        "model": args.model,
        "size": args.size,
        "quality": args.quality,
        "output_path": str(output_path),
        "summary": summary,
        "prompt": prompt,
    }
    write_metadata(output_path, metadata)

    print(f"Image written to: {output_path}")
    print(f"Metadata written to: {output_path.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
