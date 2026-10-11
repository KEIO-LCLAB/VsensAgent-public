import unittest

from core.protocol.user_turns import (
    build_clarification_reply_turn,
    build_proposal_select_turn,
)


class TestProtocolUserTurns(unittest.TestCase):
    def test_build_clarification_reply_turn(self):
        turn = build_clarification_reply_turn(
            question_id="q_1",
            selected_ids=["coffee_maker"],
            free_text="Near the sink",
        )

        self.assertEqual(
            turn,
            '[clarification.reply] {"question_id":"q_1","selected_ids":["coffee_maker"],"free_text":"Near the sink"}',
        )

    def test_build_proposal_select_turn(self):
        turn = build_proposal_select_turn(
            proposal_id="prop_1",
            selected_option_ids=["cand_1", "cand_2"],
            note="Prefer easier wiring",
        )

        self.assertEqual(
            turn,
            '[proposal.select] {"proposal_id":"prop_1","selected_option_ids":["cand_1","cand_2"],"note":"Prefer easier wiring"}',
        )
