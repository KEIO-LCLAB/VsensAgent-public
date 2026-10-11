import tempfile
import unittest
from pathlib import Path

from core.data_analysis.service import analyze_recordings


class TestDataAnalysisService(unittest.TestCase):
    def test_analyze_recordings_returns_context_aware_har_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recording_dir = root / "welkin_0_20260421_160201"
            recording_dir.mkdir(parents=True)
            (recording_dir / "DISTANCE-01_DISTANCE.csv").write_text(
                "\n".join(
                    [
                        "tag,time,d",
                        "DISTANCE-01,0.0,3.6",
                        "DISTANCE-01,0.1,3.6",
                        "DISTANCE-01,0.2,3.6",
                        "DISTANCE-01,0.3,4.9",
                        "DISTANCE-01,0.4,1.0",
                        "DISTANCE-01,0.5,10.0",
                        "DISTANCE-01,0.6,10.0",
                    ]
                ),
                encoding="utf-8",
            )

            result = analyze_recordings(
                recording_paths=[str(recording_dir)],
                recording_keys=["0/welkin/welkin_0_20260421_160201"],
                scene_context={
                    "DISTANCE-01": {
                        "state": {"sensor_type": "DISTANCE"},
                    },
                    "CoffeeMaker": {
                        "position": [0, 0, 0],
                    },
                },
            )

            self.assertEqual(result["recording_count"], 1)
            self.assertIn(result["har_judgement"], {"moderate", "strong"})
            self.assertIn("Scene context is available", result["scene_context_summary"])
            self.assertIn("DISTANCE-01", result["reply"])
            self.assertEqual(result["recording_summaries"][0]["sensor_count"], 1)

    def test_analyze_recordings_builds_phase_stats_and_threshold_for_labeled_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recording_dir = root / "kba_0_20260616_160000"
            recording_dir.mkdir(parents=True)
            (recording_dir / "DISTANCE-01_DISTANCE.csv").write_text(
                "\n".join(
                    [
                        "tag,time,phase,distance",
                        "DISTANCE-01,0.0,cooking,0.9",
                        "DISTANCE-01,1.0,cooking,1.1",
                        "DISTANCE-01,2.0,cooking,1.0",
                        "DISTANCE-01,3.0,washing_dishes,3.1",
                        "DISTANCE-01,4.0,washing_dishes,3.3",
                        "DISTANCE-01,5.0,washing_dishes,3.2",
                    ]
                ),
                encoding="utf-8",
            )

            result = analyze_recordings(
                recording_paths=[str(recording_dir)],
                recording_keys=["0/kba/kba_0_20260616_160000"],
                analysis_focus="threshold",
            )

            sensor_summary = result["recording_summaries"][0]["sensor_summaries"][0]
            self.assertEqual(sensor_summary["phase_stats"]["phase_count"], 2)
            self.assertEqual(sensor_summary["phase_stats"]["phases"]["cooking"]["sample_count"], 3)
            self.assertAlmostEqual(
                sensor_summary["phase_stats"]["threshold_candidates"][0]["threshold"],
                2.1,
                places=3,
            )
            self.assertIn("phase-labeled", result["reply"])

    def test_analyze_recordings_ignores_empty_phase_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recording_dir = root / "kba_0_20260616_170000"
            recording_dir.mkdir(parents=True)
            (recording_dir / "DISTANCE-01_DISTANCE.csv").write_text(
                "\n".join(
                    [
                        "tag,time,phase,distance",
                        "DISTANCE-01,0.0,,0.9",
                        "DISTANCE-01,1.0,,1.1",
                    ]
                ),
                encoding="utf-8",
            )

            result = analyze_recordings(
                recording_paths=[str(recording_dir)],
                recording_keys=["0/kba/kba_0_20260616_170000"],
            )

            sensor_summary = result["recording_summaries"][0]["sensor_summaries"][0]
            self.assertEqual(sensor_summary["phase_stats"]["phase_count"], 0)
            self.assertEqual(sensor_summary["phase_stats"]["threshold_candidates"], [])
