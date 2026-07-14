"""
app/routers/voice.py

Same endpoint flow as Backend/API/voice_router.py: /incoming → /answer →
/process → /deliver. The two-phase pattern (fast ack + background RAG +
poll-and-deliver) is unchanged; only dependency wiring changed —
`request.app.state.rag_model` becomes `Depends(get_rag_service)`, and
Deepgram/Twilio/gTTS logic now lives in VoiceService.
"""
import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.config import Settings, get_settings
from app.dependencies import get_memory_service, get_rag_service
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.services.voice_service import (
    ANSWER_KEY,
    AUDIO_DIR,
    INTRO_TEXT,
    RAG_PAUSE_SECONDS,
    RECORDING_KEY,
    VoiceService,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["Voice"])


def get_voice_service(settings: Settings = Depends(get_settings)) -> VoiceService:
    return VoiceService(settings=settings)


def _run_rag_and_store(rag_service: RagService, memory: MemoryService, transcript: str, session_id: str, call_sid: str) -> None:
    """Synchronous background task — runs in a thread executor, same as before."""
    session = memory.get_session_history(session_id)
    history = memory.get_trimmed_history(session_id)
    try:
        answer = rag_service.generate(user_query=transcript, history=history)
    except Exception as e:
        logger.error(f"[VOICE] RAG background task error: {e} — CallSid={call_sid}")
        answer = "I encountered an error processing your question. Please try again."

    session.add_user_message(transcript)
    session.add_ai_message(f"{ANSWER_KEY}{answer}")
    logger.info(f"[VOICE] RAG background task complete — CallSid={call_sid}")


def _cleanup_voice_session(call_sid: str, memory: MemoryService) -> None:
    try:
        memory.get_session_history(VoiceService.voice_session_id(call_sid)).clear()
        logger.info(f"[VOICE] Session cleared — CallSid={call_sid}")
    except Exception as e:
        logger.warning(f"[VOICE] Session cleanup failed: {e}")


@router.post("/incoming")
async def voice_incoming(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(default="unknown"),
    voice: VoiceService = Depends(get_voice_service),
    memory: MemoryService = Depends(get_memory_service),
):
    form_data = dict(await request.form())
    if not voice.validate_twilio_request(request.url.path, form_data, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(status_code=403, detail="Forbidden — invalid Twilio signature")

    logger.info(f"[VOICE] Incoming call — CallSid={CallSid} From={From}")

    memory.get_session_history(VoiceService.voice_session_id(CallSid)).clear()

    twiml = voice.twiml_say_and_record(say_text=INTRO_TEXT, audio_url=None)
    return Response(content=twiml, media_type="application/xml")


@router.post("/answer")
async def voice_answer(
    request: Request,
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingStatus: str = Form(default="completed"),
    voice: VoiceService = Depends(get_voice_service),
    memory: MemoryService = Depends(get_memory_service),
    settings: Settings = Depends(get_settings),
):
    form_data = dict(await request.form())
    if not voice.validate_twilio_request(request.url.path, form_data, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(status_code=403, detail="Forbidden — invalid Twilio signature")

    if RecordingStatus != "completed":
        logger.warning(f"[VOICE] Recording not completed — status={RecordingStatus}")
        return Response(content=voice.twiml_error("Sorry, I didn't catch that. Please try again."), media_type="application/xml")

    logger.info(f"[VOICE] Answer received — CallSid={CallSid}, storing recording URL")

    session = memory.get_session_history(VoiceService.voice_session_id(CallSid))
    session.add_user_message(f"{RECORDING_KEY}{RecordingUrl}")

    process_url = f"{settings.PUBLIC_BASE_URL}/voice/process"
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
    voice: VoiceService = Depends(get_voice_service),
    memory: MemoryService = Depends(get_memory_service),
    rag_service: RagService = Depends(get_rag_service),
    settings: Settings = Depends(get_settings),
):
    if not CallSid:
        form_data = dict(await request.form())
        CallSid = form_data.get("CallSid")
    if not CallSid:
        logger.error("[VOICE] /voice/process called without CallSid")
        return Response(content=voice.twiml_error("Sorry, there was an internal error. Please call again."), media_type="application/xml")

    logger.info(f"[VOICE] Processing — CallSid={CallSid}")

    session_id = VoiceService.voice_session_id(CallSid)
    session = memory.get_session_history(session_id)

    recording_url = None
    for msg in reversed(session.messages):
        content = getattr(msg, "content", "")
        if content.startswith(RECORDING_KEY):
            recording_url = content[len(RECORDING_KEY):]
            break

    if not recording_url:
        logger.error(f"[VOICE] No recording URL found in session — CallSid={CallSid}")
        return Response(content=voice.twiml_error("Sorry, I lost your question. Please ask again."), media_type="application/xml")

    try:
        audio_bytes = await voice.download_recording(recording_url)
    except Exception as e:
        logger.error(f"[VOICE] Failed to download recording: {e}")
        return Response(content=voice.twiml_error("Sorry, there was a network error. Please ask again."), media_type="application/xml")

    try:
        transcript = voice.transcribe(audio_bytes)
    except Exception as e:
        logger.error(f"[VOICE] Deepgram transcription failed: {e}")
        return Response(content=voice.twiml_error("Sorry, I could not understand you. Please try again."), media_type="application/xml")

    if not transcript:
        logger.info(f"[VOICE] Empty transcript — CallSid={CallSid}")
        return Response(content=voice.twiml_error("I didn't hear anything. Please ask your question after the beep."), media_type="application/xml")

    logger.info(f"[VOICE] Transcript: '{transcript}' — CallSid={CallSid}")

    hangup_keywords = {"goodbye", "bye", "exit", "quit", "stop", "end call"}
    if any(kw in transcript.lower() for kw in hangup_keywords):
        _cleanup_voice_session(CallSid, memory)
        return Response(content=VoiceService.twiml_goodbye(), media_type="application/xml")

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_rag_and_store, rag_service, memory, transcript, session_id, CallSid)

    deliver_url = f"{settings.PUBLIC_BASE_URL}/voice/deliver"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">I'm processing your question. One moment please.</Say>
    <Pause length="{RAG_PAUSE_SECONDS}"/>
    <Redirect method="POST">{deliver_url}</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/deliver")
async def voice_deliver(
    request: Request,
    CallSid: str = Form(default=None),
    voice: VoiceService = Depends(get_voice_service),
    memory: MemoryService = Depends(get_memory_service),
    settings: Settings = Depends(get_settings),
):
    if not CallSid:
        form_data = dict(await request.form())
        CallSid = form_data.get("CallSid")
    if not CallSid:
        return Response(content=voice.twiml_error("Sorry, there was an internal error."), media_type="application/xml")

    logger.info(f"[VOICE] Deliver — CallSid={CallSid}")

    session_id = VoiceService.voice_session_id(CallSid)
    session = memory.get_session_history(session_id)

    answer = None
    for msg in reversed(session.messages):
        content = getattr(msg, "content", "")
        if content.startswith(ANSWER_KEY):
            answer = content[len(ANSWER_KEY):]
            break

    if not answer:
        logger.warning(f"[VOICE] Answer not ready yet — retrying in 10s — CallSid={CallSid}")
        retry_url = f"{settings.PUBLIC_BASE_URL}/voice/deliver"
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Still thinking, just a few more seconds.</Say>
    <Pause length="10"/>
    <Redirect method="POST">{retry_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    logger.info(f"[VOICE] Answer ready, speaking — CallSid={CallSid}")
    tts_text = answer[:800] if len(answer) > 800 else answer
    twiml = voice.twiml_say_and_record(say_text=tts_text, audio_url=None)
    return Response(content=twiml, media_type="application/xml")


@router.get("/audio/{filename}")
async def serve_audio(filename: str, background_tasks: BackgroundTasks, voice: VoiceService = Depends(get_voice_service)):
    from pathlib import Path as _Path

    safe_name = _Path(filename).name
    if not safe_name.endswith(".mp3"):
        return Response(content="Not found", status_code=404)

    audio_path = AUDIO_DIR / safe_name
    if not audio_path.exists():
        return Response(content="Not found", status_code=404)

    background_tasks.add_task(voice.delete_file, audio_path)
    return FileResponse(path=str(audio_path), media_type="audio/mpeg")


@router.post("/recording-status")
async def recording_status(CallSid: str = Form(...), RecordingStatus: str = Form(...)):
    logger.info(f"[VOICE] Recording status — CallSid={CallSid} status={RecordingStatus}")
    return Response(content="", status_code=204)


@router.post("/clear-session")
async def clear_voice_session(CallSid: str, memory: MemoryService = Depends(get_memory_service)):
    _cleanup_voice_session(CallSid, memory)
    return {"message": f"Voice session cleared for CallSid={CallSid}"}


@router.get("/health")
async def voice_health(settings: Settings = Depends(get_settings)):
    issues = []
    if not settings.DEEPGRAM_API_KEY:
        issues.append("DEEPGRAM_API_KEY not set")
    if not settings.TWILIO_AUTH_TOKEN:
        issues.append("TWILIO_AUTH_TOKEN not set")
    if not settings.TWILIO_ACCOUNT_SID:
        issues.append("TWILIO_ACCOUNT_SID not set")
    if not settings.PUBLIC_BASE_URL:
        issues.append("PUBLIC_BASE_URL not set")

    return {
        "status": "ok" if not issues else "degraded",
        "issues": issues,
        "public_base_url": settings.PUBLIC_BASE_URL,
        "stt_model": "deepgram-nova-2",
        "tts_engine": "gTTS",
    }