import unittest

from core.skills.control_parser import ControlParser


class TestQueryParser(unittest.TestCase):
    def test_extract_query_block(self):
        reply = """I need one more detail.
<query>
{"method":"scene.query_objects","params":{"aliases":["CoffeeMaker"]},"reason":"Need canonical object identity."}
</query>
"""
        structured = ControlParser.extract_structured_reply(reply)

        self.assertEqual(structured["query"]["method"], "scene.query_objects")
        self.assertEqual(structured["query"]["params"]["aliases"], ["CoffeeMaker"])
        self.assertEqual(structured["spoken_text"], "I need one more detail.")

    def test_extract_experiment_block(self):
        reply = """I will run a phased collection.
<experiment>
{
  "goal": "distinguish cooking from washing dishes",
  "requires_avatar": true,
  "recording": {"sensors": ["DISTANCE-01"], "auto_upload": true},
  "phases": [
    {"label": "cooking", "duration_s": 15},
    {"label": "washing_dishes", "duration_s": 15}
  ],
  "repeat": 2,
  "analysis": {"run_after": true, "goal": "find a distance threshold"}
}
</experiment>
"""
        structured = ControlParser.extract_structured_reply(reply)

        self.assertEqual(structured["spoken_text"], "I will run a phased collection.")
        self.assertEqual(structured["experiment"]["goal"], "distinguish cooking from washing dishes")
        self.assertTrue(structured["experiment"]["requires_avatar"])
        self.assertEqual(structured["experiment"]["phases"][0]["label"], "cooking")
        self.assertEqual(structured["experiment"]["repeat"], 2)

    def test_malformed_query_block_does_not_crash(self):
        reply = """Need more detail.
<query>
{"method":"scene.query_objects","params":
</query>
"""
        structured = ControlParser.extract_structured_reply(reply)

        self.assertIsNone(structured["query"])
        self.assertEqual(structured["spoken_text"], "Need more detail.")

    def test_malformed_experiment_block_is_stripped_and_ignored(self):
        reply = """I will collect this later.
<experiment>
{"goal":"collect data","phases":
</experiment>
"""
        structured = ControlParser.extract_structured_reply(reply)

        self.assertIsNone(structured["experiment"])
        self.assertEqual(structured["spoken_text"], "I will collect this later.")

    def test_internal_scene_dispatch_line_is_removed_from_spoken_text(self):
        reply = """□□ to=scene.validate_avatar_placement
Placing the avatar at the best collision-free coffee-making spot."""

        structured = ControlParser.extract_structured_reply(reply)

        self.assertEqual(
            structured["spoken_text"],
            "Placing the avatar at the best collision-free coffee-making spot.",
        )

    def test_malformed_control_block_tail_is_stripped_from_spoken_text(self):
        reply = """Placing the avatar now.
<control>
{
  "actions": [
    {"target": "avatar_main", "action": "spawn_avatar"}
"""

        structured = ControlParser.extract_structured_reply(reply)

        self.assertEqual(structured["spoken_text"], "Placing the avatar now.")
