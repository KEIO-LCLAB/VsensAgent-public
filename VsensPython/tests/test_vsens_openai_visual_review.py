import base64
import os
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"decision":"accept","issues":[],"reason":"ok"}'))],
            usage=None,
        )


class TestVsensOpenAIVisualReview(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "env-openai-key", "OPENAI_MODEL_ID": "test-model"}, clear=False)
    @patch("vsens_openai.load_dotenv", return_value=False)
    @patch("vsens_openai.PromptComposer")
    @patch("vsens_openai.OpenAI")
    def test_uses_openai_api_key_from_environment(self, mock_openai, mock_composer, _load_dotenv):
        mock_openai.return_value = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
        mock_composer.return_value.compose.return_value = "system prompt"

        from vsens_openai import VsensOpenAI

        client = VsensOpenAI()

        self.assertEqual(client.api_key, "env-openai-key")
        mock_openai.assert_called_once_with(api_key="env-openai-key")

    @patch.dict(os.environ, {}, clear=True)
    @patch("vsens_openai.load_dotenv", return_value=False)
    @patch("vsens_openai.OpenAI")
    def test_requires_openai_api_key_when_no_key_path_is_provided(self, mock_openai, _load_dotenv):
        from vsens_openai import VsensOpenAI

        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            VsensOpenAI()

        mock_openai.assert_not_called()

    @patch("vsens_openai.load_dotenv", return_value=False)
    @patch("vsens_openai.PromptComposer")
    @patch("vsens_openai.OpenAI")
    def test_review_validation_images_sends_image_inputs_without_persisting_history(self, mock_openai, mock_composer, _load_dotenv):
        fake_completions = _FakeCompletions()
        mock_openai.return_value = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        mock_composer.return_value.compose.return_value = "system prompt"

        tmpdir = Path(__file__).resolve().parent / "_tmp" / f"openai_visual_review_{uuid.uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))

        try:
            image_path = tmpdir / "frame.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

            from vsens_openai import VsensOpenAI

            client = VsensOpenAI(api_key="env-openai-key", model="test-model")
            reply = client.review_validation_images(
                review_prompt="review prompt",
                context_text="task context",
                image_paths=[str(image_path)],
            )

            self.assertEqual(reply, '{"decision":"accept","issues":[],"reason":"ok"}')
            self.assertEqual(len(client.messages), 1)
            self.assertEqual(client.messages[0]["role"], "system")

            self.assertEqual(len(fake_completions.calls), 1)
            request = fake_completions.calls[0]
            self.assertEqual(request["model"], client.model)
            self.assertEqual(len(request["messages"]), 2)
            self.assertEqual(request["messages"][0]["content"], "review prompt")

            user_content = request["messages"][1]["content"]
            self.assertEqual(user_content[0]["type"], "text")
            self.assertEqual(user_content[0]["text"], "task context")
            self.assertEqual(user_content[1]["type"], "image_url")
            encoded_url = user_content[1]["image_url"]["url"]
            self.assertTrue(encoded_url.startswith("data:image/png;base64,"))
            payload = encoded_url.split(",", 1)[1]
            self.assertEqual(base64.b64decode(payload), b"\x89PNG\r\n\x1a\nfake")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
