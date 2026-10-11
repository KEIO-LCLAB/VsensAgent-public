import tempfile
import unittest
from pathlib import Path

from core.workspace.recording_resolver import resolve_recording_paths


class TestRecordingResolver(unittest.TestCase):
    def test_resolve_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            user_root = root / "0" / "welkin"
            (user_root / "welkin_0_20260421_155804").mkdir(parents=True)
            (user_root / "welkin_0_20260421_160804").mkdir(parents=True)

            selected = resolve_recording_paths(
                root=root,
                us="0",
                username="welkin",
                selector="latest",
            )

            self.assertEqual(len(selected.resolved_paths), 1)
            self.assertEqual(selected.resolved_paths[0].name, "welkin_0_20260421_160804")

    def test_resolve_recent_n_defaults_by_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            user_root = root / "0" / "welkin"
            for label in [
                "welkin_0_20260421_150000",
                "welkin_0_20260421_151000",
                "welkin_0_20260421_152000",
                "welkin_0_20260421_153000",
            ]:
                (user_root / label).mkdir(parents=True)

            selected = resolve_recording_paths(
                root=root,
                us="0",
                username="welkin",
                selector="recent_n",
                recent_n=3,
            )

            self.assertEqual(len(selected.resolved_paths), 3)
            self.assertEqual(
                [path.name for path in selected.resolved_paths],
                [
                    "welkin_0_20260421_153000",
                    "welkin_0_20260421_152000",
                    "welkin_0_20260421_151000",
                ],
            )

    def test_resolve_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            user_root = root / "0" / "welkin"
            (user_root / "welkin_0_20260421_150000").mkdir(parents=True)
            (user_root / "welkin_0_20260421_151000").mkdir(parents=True)

            selected = resolve_recording_paths(
                root=root,
                us="0",
                username="welkin",
                selector="all",
            )

            self.assertEqual(len(selected.resolved_paths), 2)

    def test_resolve_by_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            user_root = root / "0" / "welkin"
            (user_root / "welkin_0_20260421_155804").mkdir(parents=True)

            selected = resolve_recording_paths(
                root=root,
                us="0",
                username="welkin",
                selector="by_label",
                timestamp_label="welkin_0_20260421_155804",
            )

            self.assertEqual(len(selected.resolved_paths), 1)
            self.assertEqual(selected.resolved_paths[0].name, "welkin_0_20260421_155804")
