"""
Voice Router — Twilio + Deepgram + gTTS voice calling feature for DATIN/Airi.

Flow:
  1. Twilio calls POST /voice/incoming  → plays intro TwiML, records question
  2. Twilio posts recording to POST /voice/answer
     → immediately responds with "Please wait" + <Redirect> to /voice/process
     → this avoids Twilio's 15-second webhook timeout
  3. POST /voice/process does the heavy work:
     - Downloads recording from Twilio
     - Deepgram Nova-2 transcribes audio → text
     - Text goes to RagModel.Rag_Generator_caller() with Redis history
     - Answer converted to MP3 via gTTS
     - Twilio plays MP3 back to caller → loop continues

Multi-turn: CallSid keyed Redis session (separate namespace from chat sessions).
"""

import asyncio
import concurrent.futures
import logging
import os
import uuid
from pathlib import Path

from deepgram import DeepgramClient
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response
from gtts import gTTS
import httpx
from twilio.request_validator import RequestValidator

from memory import get_session_history, get_trimmed_history

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEEPGRAM_API_KEY   = os.getenv("DEEPGRAM_API_KEY")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")

# Public base URL — Cloudflare tunnel URL (no trailing slash)
# Must match exactly what Twilio sees, e.g. https://sisters-predict-funky-castle.trycloudflare.com
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Audio files stored in /tmp — cleaned up after serving
AUDIO_DIR = Path("/tmp/airi_voice")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Airi intro — played once per call on first turn
INTRO_TEXT = (
    "Hello! I am Airi, your cybersecurity AI assistant powered by DATIN. "
    "Please ask your question after the beep, and I will answer it for you."
)

# Redis session prefix for voice (separate namespace from chat sessions)
VOICE_SESSION_PREFIX = "voice:"

# Internal key prefix used to store the recording URL in Redis between
# /voice/answer and /voice/process
_RECORDING_KEY = "__recording__"

# Internal key prefix used to store the RAG answer in Redis between
# /voice/process (background task) and /voice/deliver
_ANSWER_KEY = "__answer__"

# How long to pause (seconds) while RAG runs in background before /voice/deliver
_RAG_PAUSE_SECONDS = 28

router = APIRouter(prefix="/voice", tags=["Voice"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_rag_and_store(
    rag_model,
    transcript: str,
    session_id: str,
    call_sid: str,
) -> None:
    """
    Synchronous background task: run RAG in a thread executor so it never
    blocks the asyncio event loop. Stores the answer in Redis under _ANSWER_KEY.
    /voice/deliver reads this after the <Pause> expires.
    """
    session = get_session_history(session_id)
    history = get_trimmed_history(session_id)
    try:
        answer = rag_model.Rag_Generator_caller(
            user_query=transcript,
            history=history,
        )
    except Exception as e:
        logger.error(f"[VOICE] RAG background task error: {e} — CallSid={call_sid}")
        answer = "I encountered an error processing your question. Please try again."

    # Store under _ANSWER_KEY so /voice/deliver can find it
    session.add_user_message(transcript)
    session.add_ai_message(f"{_ANSWER_KEY}{answer}")
    logger.info(f"[VOICE] RAG background task complete — CallSid={call_sid}")

def _voice_session_id(call_sid: str) -> str:
    """Namespaced session key so voice history never collides with chat history."""
    return f"{VOICE_SESSION_PREFIX}{call_sid}"


def _validate_twilio(request: Request, form_data: dict) -> bool:
    """
    Validate that the request genuinely came from Twilio.

    IMPORTANT: Uses PUBLIC_BASE_URL from env instead of request.url
    because inside Docker, request.url gives the internal container URL
    (e.g. http://0.0.0.0:80/voice/incoming) which does NOT match the
    public Cloudflare URL that Twilio signed the request with.
    Mismatched URL = validation always fails = 403 on every real call.

    Skip validation if TWILIO_AUTH_TOKEN is not set (dev mode).
    """
    if not TWILIO_AUTH_TOKEN:
        logger.warning("TWILIO_AUTH_TOKEN not set — skipping Twilio signature validation.")
        return True

    if not PUBLIC_BASE_URL:
        logger.warning("PUBLIC_BASE_URL not set — skipping Twilio signature validation.")
        return True

    validator  = RequestValidator(TWILIO_AUTH_TOKEN)
    signature  = request.headers.get("X-Twilio-Signature", "")

    # Build the exact public URL that Twilio used when it signed this request
    path       = request.url.path   # e.g. /voice/incoming
    public_url = f"{PUBLIC_BASE_URL}{path}"

    is_valid = validator.validate(public_url, form_data, signature)
    if not is_valid:
        logger.warning(
            f"[VOICE] Twilio signature validation FAILED — "
            f"url={public_url} sig={signature[:20]}..."
        )
    return is_valid


async def _text_to_speech(text: str) -> Path:
    """
    Convert text to MP3 using gTTS (Google TTS — free, reliable in Docker).
    Runs in a thread executor so it doesn't block the async event loop.
    Returns the path to the generated MP3 file.
    """
    filename = AUDIO_DIR / f"{uuid.uuid4()}.mp3"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: gTTS(text=text, lang="en", slow=False).save(str(filename))
    )
    return filename


async def _delete_file(path: Path) -> None:
    """Async helper to delete a file — used as BackgroundTask after serving audio."""
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"[VOICE] Audio cleanup failed: {e}")


def _twiml_say_and_record(
    say_text: str | None,
    audio_url: str | None,
    call_sid: str,
) -> str:
    """
    Build TwiML that:
      - Plays a pre-generated gTTS audio file (preferred), OR
      - Falls back to Twilio Polly TTS if no audio file is available
      - Then records the caller's next question
    """
    action_url = f"{PUBLIC_BASE_URL}/voice/answer"

    if audio_url:
        play_block = f"<Play>{audio_url}</Play>"
    elif say_text:
        escaped = (
            say_text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        play_block = f'<Say voice="Polly.Joanna">{escaped}</Say>'
    else:
        play_block = ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {play_block}
    <Record
        maxLength="20"
        action="{action_url}"
        recordingStatusCallback="{PUBLIC_BASE_URL}/voice/recording-status"
        transcribe="false"
        playBeep="true"
    />
</Response>"""


def _twiml_goodbye() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Thank you for using Airi. Goodbye!</Say>
    <Hangup/>
</Response>"""


def _twiml_error(message: str = "An error occurred. Please try again.") -> str:
    """Generic error TwiML that keeps the call alive so the caller can retry."""
    escaped = (
        message
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    action_url = f"{PUBLIC_BASE_URL}/voice/answer"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{escaped}</Say>
    <Record
        maxLength="20"
        action="{action_url}"
        recordingStatusCallback="{PUBLIC_BASE_URL}/voice/recording-status"
        transcribe="false"
        playBeep="true"
    />
</Response>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/incoming")
async def voice_incoming(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(default="unknown"),
):
    """
    Entry point — Twilio calls this when someone phones your Twilio number.
    Plays the intro and immediately prompts for the first question.
    """
    form_data = dict(await request.form())

    if not _validate_twilio(request, form_data):
        raise HTTPException(status_code=403, detail="Forbidden — invalid Twilio signature")

    logger.info(f"[VOICE] Incoming call — CallSid={CallSid} From={From}")

    # Clear any stale session under the same CallSid
    session = get_session_history(_voice_session_id(CallSid))
    session.clear()

    twiml = _twiml_say_and_record(
        say_text=INTRO_TEXT,
        audio_url=None,
        call_sid=CallSid,
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/answer")
async def voice_answer(
    request: Request,
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingStatus: str = Form(default="completed"),
):
    """
    Twilio posts here immediately after the caller finishes recording.

    We MUST respond within ~15 seconds or Twilio gives up and plays
    "application error". Since RAG takes 20-30+ seconds, we:
      1. Store the RecordingUrl in Redis
      2. Immediately return TwiML that says "please wait" and redirects
         to /voice/process where all the heavy work happens.

    This way Twilio gets a fast response here and waits patiently at
    /voice/process for the actual answer.
    """
    form_data = dict(await request.form())

    if not _validate_twilio(request, form_data):
        raise HTTPException(status_code=403, detail="Forbidden — invalid Twilio signature")

    if RecordingStatus != "completed":
        logger.warning(f"[VOICE] Recording not completed — status={RecordingStatus}")
        return Response(
            content=_twiml_error("Sorry, I didn't catch that. Please try again."),
            media_type="application/xml",
        )

    logger.info(f"[VOICE] Answer received — CallSid={CallSid}, storing recording URL")

    # Store RecordingUrl in Redis so /voice/process can retrieve it
    session = get_session_history(_voice_session_id(CallSid))
    session.add_user_message(f"{_RECORDING_KEY}{RecordingUrl}")

    # Immediately respond with "please wait" + redirect — no timeout risk
    process_url = f"{PUBLIC_BASE_URL}/voice/process"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Please wait while I process your question.</Say>
    <Redirect method="POST">{process_url}</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/process")
async def voice_process(
    request: Request,
    CallSid: str = Form(default=None),
):
    """
    Two-phase handler to beat Twilio's ~15 second redirect timeout.

    Phase 1 (this endpoint — must return in < 5s):
      1. Retrieve RecordingUrl from Redis
      2. Download recording + transcribe with Deepgram (fast, ~2-3s)
      3. Kick off RAG as a BackgroundTask (slow, 20-30s)
      4. Immediately return TwiML with a <Pause> while RAG runs, then
         <Redirect> to /voice/deliver which reads and speaks the answer.

    Phase 2 (/voice/deliver):
      5. RAG answer is in Redis — read and speak it with <Say>
    """
    if not CallSid:
        form_data = dict(await request.form())
        CallSid = form_data.get("CallSid")

    if not CallSid:
        logger.error("[VOICE] /voice/process called without CallSid")
        return Response(
            content=_twiml_error("Sorry, there was an internal error. Please call again."),
            media_type="application/xml",
        )

    logger.info(f"[VOICE] Processing — CallSid={CallSid}")

    session_id = _voice_session_id(CallSid)
    session    = get_session_history(session_id)

    # ── Step 1: Retrieve RecordingUrl from Redis ──────────────────────────────
    RecordingUrl = None
    for msg in reversed(session.messages):
        content = getattr(msg, "content", "")
        if content.startswith(_RECORDING_KEY):
            RecordingUrl = content[len(_RECORDING_KEY):]
            break

    if not RecordingUrl:
        logger.error(f"[VOICE] No recording URL found in session — CallSid={CallSid}")
        return Response(
            content=_twiml_error("Sorry, I lost your question. Please ask again."),
            media_type="application/xml",
        )

    # ── Step 2: Download Twilio recording ────────────────────────────────────
    recording_mp3_url = RecordingUrl + ".mp3"
    try:
        async with httpx.AsyncClient() as client:
            audio_response = await client.get(
                recording_mp3_url,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                follow_redirects=True,
                timeout=30,
            )
        audio_response.raise_for_status()
        audio_bytes = audio_response.content
    except Exception as e:
        logger.error(f"[VOICE] Failed to download recording: {e}")
        return Response(
            content=_twiml_error("Sorry, there was a network error. Please ask again."),
            media_type="application/xml",
        )

    # ── Step 3: Transcribe with Deepgram Nova-2 ──────────────────────────────
    try:
        dg_client   = DeepgramClient(DEEPGRAM_API_KEY)
        dg_response = dg_client.listen.rest.v("1").transcribe_file(
            {"buffer": audio_bytes, "mimetype": "audio/mp3"},
            {"model": "nova-2", "smart_format": True, "language": "en"},
        )
        transcript = (
            dg_response.results.channels[0].alternatives[0].transcript.strip()
        )
    except Exception as e:
        logger.error(f"[VOICE] Deepgram transcription failed: {e}")
        return Response(
            content=_twiml_error("Sorry, I could not understand you. Please try again."),
            media_type="application/xml",
        )

    if not transcript:
        logger.info(f"[VOICE] Empty transcript — CallSid={CallSid}")
        return Response(
            content=_twiml_error(
                "I didn't hear anything. Please ask your question after the beep."
            ),
            media_type="application/xml",
        )

    logger.info(f"[VOICE] Transcript: '{transcript}' — CallSid={CallSid}")

    # ── Detect hangup keywords ────────────────────────────────────────────────
    hangup_keywords = {"goodbye", "bye", "exit", "quit", "stop", "end call"}
    if any(kw in transcript.lower() for kw in hangup_keywords):
        _cleanup_voice_session(CallSid)
        return Response(content=_twiml_goodbye(), media_type="application/xml")

    # ── Step 4: Kick off RAG in a thread executor, respond instantly ─────────
    # RAG (Ollama) is synchronous and CPU/GPU-bound — it blocks the entire
    # event loop if awaited directly, which prevents Twilio's /voice/deliver
    # request from being handled during the <Pause>.
    # run_in_executor() offloads it to a thread so the event loop stays free.
    rag_model = request.app.state.rag_model
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None,  # default ThreadPoolExecutor
        _run_rag_and_store,
        rag_model,
        transcript,
        session_id,
        CallSid,
    )

    deliver_url = f"{PUBLIC_BASE_URL}/voice/deliver"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">I'm processing your question. One moment please.</Say>
    <Pause length="{_RAG_PAUSE_SECONDS}"/>
    <Redirect method="POST">{deliver_url}</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/deliver")
async def voice_deliver(
    request: Request,
    CallSid: str = Form(default=None),
):
    """
    Called by Twilio after the <Pause> in /voice/process expires.
    By now the RAG BackgroundTask has written the answer to Redis.
    Reads it and speaks it with <Say>, then records the next question.
    If RAG is still running (very slow model), waits 10 more seconds and retries once.
    """
    if not CallSid:
        form_data = dict(await request.form())
        CallSid = form_data.get("CallSid")

    if not CallSid:
        return Response(
            content=_twiml_error("Sorry, there was an internal error."),
            media_type="application/xml",
        )

    logger.info(f"[VOICE] Deliver — CallSid={CallSid}")

    session_id = _voice_session_id(CallSid)
    session    = get_session_history(session_id)

    # Read the answer that the background RAG task stored in Redis
    answer = None
    for msg in reversed(session.messages):
        content = getattr(msg, "content", "")
        if content.startswith(_ANSWER_KEY):
            answer = content[len(_ANSWER_KEY):]
            break

    if not answer:
        # RAG didn't finish in time — pause 10 more seconds and retry once
        logger.warning(f"[VOICE] Answer not ready yet — retrying in 10s — CallSid={CallSid}")
        retry_url = f"{PUBLIC_BASE_URL}/voice/deliver"
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Still thinking, just a few more seconds.</Say>
    <Pause length="10"/>
    <Redirect method="POST">{retry_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    logger.info(f"[VOICE] Answer ready, speaking — CallSid={CallSid}")

    # Answer is ready — speak it and record the next question
    tts_text = answer[:800] if len(answer) > 800 else answer
    twiml = _twiml_say_and_record(
        say_text=tts_text,
        audio_url=None,
        call_sid=CallSid,
    )
    return Response(content=twiml, media_type="application/xml")


@router.get("/audio/{filename}")
async def serve_audio(filename: str, background_tasks: BackgroundTasks):
    """
    Serve generated TTS audio files to Twilio.
    Only serves .mp3 files from AUDIO_DIR — no path traversal possible.
    File is deleted in the background after it has been streamed.
    """
    safe_name = Path(filename).name
    if not safe_name.endswith(".mp3"):
        return Response(content="Not found", status_code=404)

    audio_path = AUDIO_DIR / safe_name
    if not audio_path.exists():
        return Response(content="Not found", status_code=404)

    background_tasks.add_task(_delete_file, audio_path)

    return FileResponse(
        path=str(audio_path),
        media_type="audio/mpeg",
    )


@router.post("/recording-status")
async def recording_status(
    CallSid: str = Form(...),
    RecordingStatus: str = Form(...),
):
    """
    Twilio recording status callback — fire and forget, logging only.
    """
    logger.info(
        f"[VOICE] Recording status — CallSid={CallSid} status={RecordingStatus}"
    )
    return Response(content="", status_code=204)


@router.post("/clear-session")
async def clear_voice_session(CallSid: str):
    """Manually clear a voice session from Redis — useful for testing."""
    _cleanup_voice_session(CallSid)
    return {"message": f"Voice session cleared for CallSid={CallSid}"}


@router.get("/health")
async def voice_health():
    """Quick health check for the voice subsystem."""
    issues = []
    if not DEEPGRAM_API_KEY:
        issues.append("DEEPGRAM_API_KEY not set")
    if not TWILIO_AUTH_TOKEN:
        issues.append("TWILIO_AUTH_TOKEN not set")
    if not TWILIO_ACCOUNT_SID:
        issues.append("TWILIO_ACCOUNT_SID not set")
    if not PUBLIC_BASE_URL:
        issues.append("PUBLIC_BASE_URL not set")

    return {
        "status": "ok" if not issues else "degraded",
        "issues": issues,
        "public_base_url": PUBLIC_BASE_URL,
        "stt_model": "deepgram-nova-2",
        "tts_engine": "gTTS",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cleanup_voice_session(call_sid: str) -> None:
    """Remove voice session from Redis on hangup."""
    try:
        get_session_history(_voice_session_id(call_sid)).clear()
        logger.info(f"[VOICE] Session cleared — CallSid={call_sid}")
    except Exception as e:
        logger.warning(f"[VOICE] Session cleanup failed: {e}")