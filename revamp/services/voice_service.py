"""
app/services/voice_service.py

TwiML building, Deepgram transcription, and gTTS logic extracted from
Backend/API/voice_router.py. The old file read DEEPGRAM_API_KEY,
TWILIO_AUTH_TOKEN, TWILIO_ACCOUNT_SID, PUBLIC_BASE_URL as module-level
constants via os.getenv() at import time; those now come from an
injected Settings object instead.
"""
import asyncio
import logging
import uuid
from pathlib import Path

from deepgram import DeepgramClient
from gtts import gTTS
from twilio.request_validator import RequestValidator

from app.config import Settings

logger = logging.getLogger(__name__)

AUDIO_DIR = Path("/tmp/airi_voice")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

INTRO_TEXT = (
    "Hello! I am Airi, your cybersecurity AI assistant powered by DATIN. "
    "Please ask your question after the beep, and I will answer it for you."
)

VOICE_SESSION_PREFIX = "voice:"
RECORDING_KEY = "__recording__"
ANSWER_KEY = "__answer__"
RAG_PAUSE_SECONDS = 28


class VoiceService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._deepgram = DeepgramClient(settings.DEEPGRAM_API_KEY) if settings.DEEPGRAM_API_KEY else None
        self._validator = (
            RequestValidator(settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_AUTH_TOKEN else None
        )

    @staticmethod
    def voice_session_id(call_sid: str) -> str:
        return f"{VOICE_SESSION_PREFIX}{call_sid}"

    def validate_twilio_request(self, request_url_path: str, form_data: dict, signature: str) -> bool:
        """
        Validate the request genuinely came from Twilio. Skips validation
        in dev mode (no TWILIO_AUTH_TOKEN / PUBLIC_BASE_URL configured) —
        same behavior as the original _validate_twilio().
        """
        if not self.settings.TWILIO_AUTH_TOKEN:
            logger.warning("TWILIO_AUTH_TOKEN not set — skipping Twilio signature validation.")
            return True
        if not self.settings.PUBLIC_BASE_URL:
            logger.warning("PUBLIC_BASE_URL not set — skipping Twilio signature validation.")
            return True

        public_url = f"{self.settings.PUBLIC_BASE_URL.rstrip('/')}{request_url_path}"
        is_valid = self._validator.validate(public_url, form_data, signature)
        if not is_valid:
            logger.warning(f"[VOICE] Twilio signature validation FAILED — url={public_url} sig={signature[:20]}...")
        return is_valid

    async def download_recording(self, recording_url: str) -> bytes:
        import httpx

        recording_mp3_url = recording_url + ".mp3"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                recording_mp3_url,
                auth=(self.settings.TWILIO_ACCOUNT_SID, self.settings.TWILIO_AUTH_TOKEN),
                follow_redirects=True,
                timeout=30,
            )
        response.raise_for_status()
        return response.content

    def transcribe(self, audio_bytes: bytes) -> str:
        dg_response = self._deepgram.listen.rest.v("1").transcribe_file(
            {"buffer": audio_bytes, "mimetype": "audio/mp3"},
            {"model": "nova-2", "smart_format": True, "language": "en"},
        )
        return dg_response.results.channels[0].alternatives[0].transcript.strip()

    async def text_to_speech(self, text: str) -> Path:
        filename = AUDIO_DIR / f"{uuid.uuid4()}.mp3"
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: gTTS(text=text, lang="en", slow=False).save(str(filename)))
        return filename

    def twiml_say_and_record(self, say_text: str | None, audio_url: str | None) -> str:
        action_url = f"{self.settings.PUBLIC_BASE_URL}/voice/answer"
        if audio_url:
            play_block = f"<Play>{audio_url}</Play>"
        elif say_text:
            escaped = say_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            play_block = f'<Say voice="Polly.Joanna">{escaped}</Say>'
        else:
            play_block = ""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {play_block}
    <Record
        maxLength="20"
        action="{action_url}"
        recordingStatusCallback="{self.settings.PUBLIC_BASE_URL}/voice/recording-status"
        transcribe="false"
        playBeep="true"
    />
</Response>"""

    @staticmethod
    def twiml_goodbye() -> str:
        return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Thank you for using Airi. Goodbye!</Say>
    <Hangup/>
</Response>"""

    def twiml_error(self, message: str = "An error occurred. Please try again.") -> str:
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        action_url = f"{self.settings.PUBLIC_BASE_URL}/voice/answer"
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{escaped}</Say>
    <Record
        maxLength="20"
        action="{action_url}"
        recordingStatusCallback="{self.settings.PUBLIC_BASE_URL}/voice/recording-status"
        transcribe="false"
        playBeep="true"
    />
</Response>"""

    @staticmethod
    async def delete_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"[VOICE] Audio cleanup failed: {e}")