import unittest

from core.agent_status import AgentStatusBroadcaster, EXECUTING, IDLE


class TestAgentStatusBroadcaster(unittest.IsolatedAsyncioTestCase):
    async def test_rebroadcasts_same_state_when_detail_changes(self):
        messages = []

        async def broadcast(message):
            messages.append(message)

        broadcaster = AgentStatusBroadcaster(broadcast)

        await broadcaster.set_state(EXECUTING, detail="Starting experiment")
        await broadcaster.set_state(EXECUTING, detail="Recording phase cooking")
        await broadcaster.set_state(EXECUTING, detail="Recording phase cooking")
        await broadcaster.set_state(IDLE)

        self.assertEqual(
            messages,
            [
                {"type": "agent_status", "state": EXECUTING, "detail": "Starting experiment"},
                {"type": "agent_status", "state": EXECUTING, "detail": "Recording phase cooking"},
                {"type": "agent_status", "state": IDLE},
            ],
        )
