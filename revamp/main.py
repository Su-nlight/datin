"""
app/main.py

Compare to the old Backend/API/main.py: no load_dotenv(), no lifespan()
building llm/rag_model/code_analyzer/code_evaluator and stuffing them
onto app.state, no manual construction of anything. Settings are
validated once at import (get_settings() raises immediately if a
required var like JWT_SECRET_KEY is missing, instead of failing deep
inside a request later). Every router pulls what it needs via Depends().

Voice is included but commented out, matching the current upstream
main.py (`# from voice_router import router as voice_router` is
commented there too) — the code is fully migrated to app/routers/voice.py
and app/services/voice_service.py, ready to enable whenever Twilio/
Deepgram creds are wired back in.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette import status

from app.config import get_settings
from app.dependencies import limiter
from app.routers import auth, abroute, benchmark, code_analysis, rag

# from app.routers import voice   # disabled upstream too — enable once Twilio/Deepgram creds are set

settings = get_settings()

app = FastAPI(title="Airi — Cybersecurity RAG API", version="2.0.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth.router)
app.include_router(rag.router)
app.include_router(code_analysis.router)
app.include_router(abroute.router)        # /ab-test/*   (A/B testing)
app.include_router(benchmark.router)      # /benchmark/* (research benchmarks)
# app.include_router(voice.router)        # /voice/*     (disabled — see note above)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", status_code=status.HTTP_200_OK, tags=["Health"])
async def root():
    return {"status": "ok", "service": "Airi RAG API"}