import unittest


class TestVisualReviewParsing(unittest.TestCase):
    def test_parse_accept_review(self):
        from core.protocol.visual_review import parse_visual_review

        result = parse_visual_review('{"decision":"accept","issues":[],"reason":"Looks good."}')

        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["reason"], "Looks good.")

    def test_parse_retry_review(self):
        from core.protocol.visual_review import parse_visual_review

        result = parse_visual_review('{"decision":"retry","issues":["bad_facing","too_far"],"reason":"Avatar is angled away."}')

        self.assertEqual(result["decision"], "retry")
        self.assertEqual(result["issues"], ["bad_facing", "too_far"])
        self.assertEqual(result["reason"], "Avatar is angled away.")

    def test_parse_malformed_review_falls_back_to_retry(self):
        from core.protocol.visual_review import parse_visual_review

        result = parse_visual_review("not-json")

        self.assertEqual(result["decision"], "retry")
        self.assertEqual(result["issues"], ["review_parse_error"])
        self.assertIn("Unable", result["reason"])

