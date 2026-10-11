from pathlib import Path
import base64
import mimetypes
import os
from monitor_stats import monitor_stats
from core.prompting.composer import PromptComposer

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    load_dotenv = None

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - local test fallback
    OpenAI = None


def _load_runtime_env(project_root: Path) -> None:
    if load_dotenv is None:
        return
    load_dotenv(dotenv_path=project_root / ".env.vsensagent", override=False)


def _load_model() -> str:
    env_key = os.getenv("OPENAI_MODEL_ID")
    if env_key:
        return env_key.strip()
    raise RuntimeError("OPENAI_MODEL_ID is not set. Add it to VsensPython/.env.vsensagent.")


def _load_api_key() -> str:
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key.strip()
    raise RuntimeError("OPENAI_API_KEY is not set. Add it to VsensPython/.env.vsensagent.")


class VsensOpenAI:
    def __init__(
        self,
        model: str = None,
        prompt_path: str = None,
        api_key: str = None
    ):
        # Set paths relative to VsensPython project root
        project_root = Path(__file__).parent
        self.project_root = project_root
        _load_runtime_env(project_root)
        if prompt_path is None:
            prompt_path = None
        if OpenAI is None:
            raise ModuleNotFoundError("openai package is required to construct VsensOpenAI")
        self.api_key = _load_api_key() if api_key is None else api_key
        self.model = _load_model() if model is None else model
        self.client = OpenAI(api_key=self.api_key)
        self.system_prompt = self._load_system_prompt(prompt_path)
        self.messages = []
        self.initialized = False

    def _load_system_prompt(self, path) -> str:
        if path is None:
            project_root = getattr(self, "project_root", Path(__file__).parent)
            composer = PromptComposer(project_root=project_root)
            return composer.compose().strip()
        prompt_file = Path(path) if not isinstance(path, Path) else path
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found at {prompt_file.absolute()}")
        return prompt_file.read_text(encoding="utf-8").strip()

    def _initialize_conversation(self):
        if not self.initialized:
            self.messages.append({"role": "system", "content": self.system_prompt})
            self.initialized = True

    def send_message(self, user_input: str, persist: bool = True) -> str:
        self._initialize_conversation()
        request_messages = list(self.messages)
        request_messages.append({"role": "user", "content": user_input})
        # if len(self.messages)>=3:
        #     self.messages.append({"role": "user", "content": "test wrong token prefix" + user_input})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=request_messages
        )
        
        reply = response.choices[0].message.content
        if persist:
            self.append_exchange(user_input, reply)
        
        # Collect statistics for monitoring
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cached_tokens = 0
        
        # Access individual usage details
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            
            print(f"Prompt Tokens: {prompt_tokens}")
            print(f"Completion Tokens: {completion_tokens}")
            print(f"Total Tokens: {total_tokens}")

            # Access the specific prompt_tokens_details (for models that support prompt caching)
            if hasattr(response.usage, 'prompt_tokens_details') and response.usage.prompt_tokens_details:
                cached_tokens = response.usage.prompt_tokens_details.cached_tokens
                print(f"Prompt Tokens Details: {response.usage.prompt_tokens_details}")
                print(f"Cached Tokens: {cached_tokens}")
            else:
                print("Prompt token details (e.g., cached_tokens) are not available for this request/model or caching did not occur.")
        
        # Store the last user input and reply for monitoring
        self._last_user_input = user_input
        self._last_reply = reply
        self._last_token_stats = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'cached_tokens': cached_tokens
        }
        
        return reply

    def append_exchange(self, user_input: str, reply: str) -> None:
        self._initialize_conversation()
        self.messages.append({"role": "user", "content": user_input})
        self.messages.append({"role": "assistant", "content": reply})

    def review_validation_images(
        self,
        *,
        review_prompt: str,
        context_text: str,
        image_paths: list[str],
    ) -> str:
        self._initialize_conversation()
        request_messages = [
            {"role": "system", "content": review_prompt},
            {
                "role": "user",
                "content": self._build_multimodal_user_content(context_text, image_paths or []),
            },
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=request_messages,
        )
        return response.choices[0].message.content

    @staticmethod
    def _build_multimodal_user_content(context_text: str, image_paths: list[str]) -> list[dict]:
        content = [{"type": "text", "text": context_text}]
        for image_path in image_paths:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": VsensOpenAI._image_path_to_data_url(image_path),
                }
            })
        return content

    @staticmethod
    def _image_path_to_data_url(image_path: str) -> str:
        path = Path(image_path)
        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def reset_conversation(self, client_id: str | None = None):
        self.messages = []
        self.initialized = False
        monitor_stats.reset_conversation(client_id=client_id)
        print('Conversation reset.')

    def transcribe_audio(self, audio_path: str, model: str = "whisper-1") -> str:
        """Transcribes audio file to text using OpenAI's transcription API"""
        with open(audio_path, "rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model=model,
                file=audio_file
            )
        return transcript.text

    def speak_text(
        self,
        text: str,
        output_path: str = "speech_output.mp3",
        voice: str = "nova",
        model: str = "tts-1"
    ) -> str:
        """Converts text to speech and saves it as an MP3"""
        speech_response = self.client.audio.speech.create(
            model=model,
            voice=voice,
            input=text
        )
        with open(output_path, "wb") as f:
            f.write(speech_response.content)
        return output_path
