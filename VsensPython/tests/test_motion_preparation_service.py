import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


class TestMotionPreparationService(unittest.TestCase):

    def _load_test_motion(self):
        npz_path = Path(__file__).parent / "test_motion.npz"
        with open(npz_path, "rb") as f:
            return f.read()

    def _build_npz_bytes(self, *, pose_dim: int = 165, frames: int = 2) -> bytes:
        buffer = io.BytesIO()
        poses = np.array(
            [
                [float(frame_index)] * pose_dim
                for frame_index in range(frames)
            ],
            dtype=np.float32,
        )
        np.savez_compressed(
            buffer,
            gender=np.array(["male"]),
            betas=np.array([0.1, 0.2, 0.3], dtype=np.float32),
            poses=poses,
            trans=np.array(
                [
                    [float(frame_index), 0.0, 0.0]
                    for frame_index in range(frames)
                ],
                dtype=np.float32,
            ),
            Rh=np.array(
                [
                    [10.0 + frame_index, 20.0 + frame_index, 30.0 + frame_index]
                    for frame_index in range(frames)
                ],
                dtype=np.float32,
            ),
        )
        return buffer.getvalue()

    def test_convert_npz_bytes_to_smplx_json(self):
        from core.motion.service import convert_npz_bytes_to_smplx_json

        motion_json = convert_npz_bytes_to_smplx_json(self._build_npz_bytes(), fps=120.0)
        payload = json.loads(motion_json)

        self.assertEqual(payload["model"], "smplx")
        self.assertEqual(payload["gender"], "male")
        self.assertEqual(payload["fps"], 120.0)
        self.assertEqual(len(payload["betas"]), 3)
        self.assertEqual(len(payload["poses"]), 2)
        self.assertEqual(len(payload["poses"][0]), 165)
        self.assertEqual(payload["trans"][1], [1.0, 0.0, 0.0])

    def test_convert_npz_bytes_to_smplx_json2(self):
        from core.motion.service import convert_npz_bytes_to_smplx_json

        motion_json = convert_npz_bytes_to_smplx_json(self._load_test_motion(), fps=120.0)
        payload = json.loads(motion_json)

        self.assertEqual(payload["model"], "smplx")
        self.assertEqual(payload["gender"], "neutral")
        self.assertEqual(payload["fps"], 120.0)
        self.assertEqual(len(payload["betas"]), 16)
        self.assertEqual(len(payload["poses"]), 150)
        self.assertEqual(len(payload["poses"][0]), 165)


    def test_convert_npz_bytes_expands_156_dim_poses_for_unity_smplx_layout(self):
        from core.motion.service import convert_npz_bytes_to_smplx_json

        motion_json = convert_npz_bytes_to_smplx_json(
            self._build_npz_bytes(pose_dim=156, frames=2),
            fps=30.0,
        )
        payload = json.loads(motion_json)

        self.assertEqual(len(payload["poses"][0]), 165)
        self.assertEqual(payload["poses"][0][:66], [0.0] * 66)
        self.assertEqual(payload["poses"][0][66:75], [0.0] * 9)
        self.assertEqual(payload["poses"][1][:66], [1.0] * 66)
        self.assertEqual(payload["poses"][1][66:75], [0.0] * 9)
        self.assertEqual(payload["poses"][1][75:], [1.0] * 90)

    def test_prepare_motion_reuses_disk_cache_for_same_request(self):
        from core.motion.service import MotionPreparationService

        with tempfile.TemporaryDirectory() as tmp_dir:
            calls = []

            def fake_client(text, *, duration, seed, cfg_scale):
                calls.append(
                    {
                        "text": text,
                        "duration": duration,
                        "seed": seed,
                        "cfg_scale": cfg_scale,
                    }
                )
                return self._build_npz_bytes(), {"job_id": "job_1"}

            service = MotionPreparationService(
                cache_dir=Path(tmp_dir),
                motion_client=fake_client,
            )

            first = service.prepare_motion("walk to the sink", duration=4.0, seed=7, cfg_scale=6.0)
            second = service.prepare_motion("walk to the sink", duration=4.0, seed=7, cfg_scale=6.0)

            self.assertEqual(len(calls), 1)
            self.assertEqual(first["motion_id"], second["motion_id"])
            self.assertEqual(first["motion_json"], second["motion_json"])
            self.assertTrue((Path(tmp_dir) / f"{first['motion_id']}.json").is_file())
            self.assertTrue((Path(tmp_dir) / f"{first['motion_id']}.meta.json").is_file())

    def test_prepare_motion_infers_fps_from_duration_and_frame_count(self):
        from core.motion.service import MotionPreparationService

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = MotionPreparationService(
                cache_dir=Path(tmp_dir),
                motion_client=lambda *_args, **_kwargs: (self._build_npz_bytes(pose_dim=156, frames=60), {"job_id": "job_2"}),
            )

            result = service.prepare_motion("walk forward", duration=2.0, seed=7, cfg_scale=4.5)
            payload = json.loads(result["motion_json"])

            self.assertEqual(payload["fps"], 30.0)
            self.assertEqual(len(payload["poses"]), 60)
