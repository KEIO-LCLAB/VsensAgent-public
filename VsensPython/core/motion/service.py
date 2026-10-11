from __future__ import annotations

import hashlib
import io
import json
import os
import time
import urllib.request
from pathlib import Path

import numpy as np


_SMPLX_EXPECTED_POSE_DIM = 165
_SMPLX_OMITTED_FACE_JOINT_INSERT_AT = 66
_SMPLX_OMITTED_FACE_JOINT_DIM = 9


def _normalize_scalar(value, default=""):
    if value is None:
        return default
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return default
        return _normalize_scalar(value.reshape(-1)[0], default=default)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _normalize_smplx_poses(poses: np.ndarray) -> list[list[float]]:
    if poses.ndim != 2:
        raise ValueError(f"Expected poses to be rank-2, got shape {poses.shape}")

    pose_dim = poses.shape[1]
    if pose_dim == _SMPLX_EXPECTED_POSE_DIM:
        return poses.astype(float).tolist()

    # HY-Motion currently emits 156-dim SMPL-H pose vectors that omit jaw/eye
    # joints. Unity's parser expects the full 55-joint layout (165 floats), so
    # insert zero axis-angle triplets for jaw/left_eye/right_eye before fingers.
    if pose_dim == _SMPLX_EXPECTED_POSE_DIM - _SMPLX_OMITTED_FACE_JOINT_DIM:
        left = poses[:, :_SMPLX_OMITTED_FACE_JOINT_INSERT_AT]
        right = poses[:, _SMPLX_OMITTED_FACE_JOINT_INSERT_AT:]
        padding = np.zeros((poses.shape[0], _SMPLX_OMITTED_FACE_JOINT_DIM), dtype=poses.dtype)
        expanded = np.concatenate([left, padding, right], axis=1)
        return expanded.astype(float).tolist()

    raise ValueError(f"Unsupported SMPL-X pose dimension: {pose_dim}")


def _infer_fps(frame_count: int, requested_duration_s: float, default_fps: float) -> float:
    if frame_count <= 0:
        return float(default_fps)
    if requested_duration_s <= 0:
        return float(default_fps)
    inferred = frame_count / requested_duration_s
    if inferred <= 0:
        return float(default_fps)
    return float(inferred)


def convert_npz_bytes_to_smplx_json(
    npz_bytes: bytes,
    *,
    fps: float = 120.0,
    model: str = "smplx",
) -> str:
    with np.load(io.BytesIO(npz_bytes), allow_pickle=False) as data:
        poses_array = data["poses"].astype(np.float32)
        poses = _normalize_smplx_poses(poses_array)
        trans = data["trans"].astype(float).tolist()
        betas = data["betas"].astype(float).reshape(-1).tolist() if "betas" in data else []
        gender = str(_normalize_scalar(data["gender"], default="neutral")) if "gender" in data else "neutral"

    payload = {
        "model": model,
        "gender": gender,
        "fps": float(fps),
        "betas": betas,
        "poses": poses,
        "trans": trans,
    }
    return json.dumps(payload, separators=(",", ":"))


class MotionPreparationService:
    def __init__(
        self,
        *,
        service_url: str | None = None,
        cache_dir: Path | str | None = None,
        motion_client=None,
        fps: float = 120.0,
        poll_interval_s: float = 0.25,
        timeout_s: float = 60.0,
    ):
        project_root = Path(__file__).resolve().parents[2]
        self.service_url = (service_url or os.environ.get("HYMOTION_SERVICE_URL") or "http://131.113.87.66:9334").rstrip("/")
        self.cache_dir = Path(cache_dir or (project_root / "data" / "cache" / "avatar_motions"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.motion_client = motion_client or self._fetch_npz_from_remote_service
        self.fps = fps
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s

    def prepare_motion(
        self,
        text: str,
        *,
        duration: float = 5.0,
        seed: int = 42,
        cfg_scale: float = 5.0,
        motion_name: str | None = None,
    ) -> dict:
        normalized_text = (text or "").strip()
        if not normalized_text:
            raise ValueError("motion text is required")

        motion_id = self._build_motion_id(
            text=normalized_text,
            duration=duration,
            seed=seed,
            cfg_scale=cfg_scale,
        )
        cached = self._load_from_cache(motion_id)
        if cached is not None:
            return cached

        npz_bytes, remote_metadata = self.motion_client(
            normalized_text,
            duration=duration,
            seed=seed,
            cfg_scale=cfg_scale,
        )
        with np.load(io.BytesIO(npz_bytes), allow_pickle=False) as data:
            frame_count = int(data["poses"].shape[0]) if "poses" in data else 0
        motion_json = convert_npz_bytes_to_smplx_json(
            npz_bytes,
            fps=_infer_fps(frame_count, duration, self.fps),
        )
        result = {
            "motion_id": motion_id,
            "motion_name": motion_name or self._default_motion_name(normalized_text),
            "motion_json": motion_json,
            "source_text": normalized_text,
            "duration": duration,
            "seed": seed,
            "cfg_scale": cfg_scale,
            "service_metadata": remote_metadata or {},
        }
        self._store_in_cache(result)
        return result

    def _build_motion_id(self, *, text: str, duration: float, seed: int, cfg_scale: float) -> str:
        spec = json.dumps(
            {
                "text": text,
                "duration": float(duration),
                "seed": int(seed),
                "cfg_scale": float(cfg_scale),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"motion_{hashlib.sha256(spec.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _default_motion_name(text: str) -> str:
        base = "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")
        compact = "_".join(part for part in base.split("_") if part)
        return compact[:64] or "avatar_motion"

    def _json_path(self, motion_id: str) -> Path:
        return self.cache_dir / f"{motion_id}.json"

    def _meta_path(self, motion_id: str) -> Path:
        return self.cache_dir / f"{motion_id}.meta.json"

    def _load_from_cache(self, motion_id: str) -> dict | None:
        json_path = self._json_path(motion_id)
        meta_path = self._meta_path(motion_id)
        if not json_path.is_file() or not meta_path.is_file():
            return None

        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            "motion_id": motion_id,
            "motion_name": metadata["motion_name"],
            "motion_json": json_path.read_text(encoding="utf-8"),
            "source_text": metadata["source_text"],
            "duration": metadata["duration"],
            "seed": metadata["seed"],
            "cfg_scale": metadata["cfg_scale"],
            "service_metadata": metadata.get("service_metadata") or {},
        }

    def _store_in_cache(self, result: dict) -> None:
        motion_id = result["motion_id"]
        self._json_path(motion_id).write_text(result["motion_json"], encoding="utf-8")
        metadata = {
            "motion_name": result["motion_name"],
            "source_text": result["source_text"],
            "duration": result["duration"],
            "seed": result["seed"],
            "cfg_scale": result["cfg_scale"],
            "service_metadata": result.get("service_metadata") or {},
        }
        self._meta_path(motion_id).write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _fetch_npz_from_remote_service(
        self,
        text: str,
        *,
        duration: float,
        seed: int,
        cfg_scale: float,
    ) -> tuple[bytes, dict]:
        create_payload = json.dumps(
            {
                "text": text,
                "duration": duration,
                "seed": seed,
                "cfg_scale": cfg_scale,
            }
        ).encode("utf-8")
        create_req = urllib.request.Request(
            f"{self.service_url}/jobs",
            data=create_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(create_req, timeout=self.timeout_s) as resp:
            created = json.loads(resp.read().decode("utf-8"))

        job_id = created["job_id"]
        deadline = time.time() + self.timeout_s
        status_payload = None
        while time.time() < deadline:
            with urllib.request.urlopen(f"{self.service_url}/jobs/{job_id}", timeout=self.timeout_s) as resp:
                status_payload = json.loads(resp.read().decode("utf-8"))
            if status_payload["status"] == "succeeded":
                break
            if status_payload["status"] == "failed":
                raise RuntimeError(status_payload.get("error") or f"Motion service job {job_id} failed")
            time.sleep(self.poll_interval_s)
        else:
            raise TimeoutError(f"Timed out waiting for motion job {job_id}")

        with urllib.request.urlopen(f"{self.service_url}/jobs/{job_id}/result", timeout=self.timeout_s) as resp:
            npz_bytes = resp.read()

        return npz_bytes, {
            "job_id": job_id,
            "status": status_payload["status"],
            "result_url": status_payload.get("result_url"),
        }
