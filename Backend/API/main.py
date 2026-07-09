import logging
from code_analyzer import SecurityCodeAnalyzer
from code_evaluator import CodeSecurityEvaluator
from code_analysis_router import router as code_analysis_router
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette import status
from dotenv import load_dotenv
import os

import auth
from auth import token_verifier
from models import RagResponse, ChatRequest
from ragroute import RagModel
from memory import get_session_history, get_trimmed_history
from llm_provider import get_llm
from voice_router import router as voice_router

# both A/B and benchmark routers from testing_folder
from testing_folder import ab_router, benchmark_router

load_dotenv("API.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter — shared instance (auth.py uses the same limiter)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event("startup")
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize heavy resources once at startup, clean up on shutdown."""
    
    logger.info("Initializing LLM and models...")
    
    # 1️⃣ Create LLM
    llm = get_llm(provider=os.getenv("LLM_PROVIDER", "gemini"))
    
    # 2️⃣ Create RAG Model
    rag_model = RagModel(
        PineconeAPIKey=os.getenv("PINECONE_API_KEY"),
        # GenAIKey=os.getenv("GENAI_API_KEY"),  # ← ADD THIS
        NameSpaces=[s.strip() for s in os.getenv("NAMESPACES", "").split(",") if s],
        Index_Name=os.getenv("INDEX_NAME"),
        min_score=float(os.getenv("MIN_SCORE", 0.75)),
        llm=llm
    )
    
    # 3️⃣ Create Code Analyzer
    code_analyzer = SecurityCodeAnalyzer(llm=llm, rag_model=rag_model)
    
    # 4️⃣ Create Code Evaluator
    code_evaluator = CodeSecurityEvaluator(llm=llm)
    
    # 5️⃣ STORE ALL in app.state (in any order now)
    app.state.llm = llm
    app.state.rag_model = rag_model
    app.state.code_analyzer = code_analyzer
    app.state.code_evaluator = code_evaluator
    
    logger.info("✓ All models initialized")
    yield
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Airi — Cybersecurity RAG API",
    version="1.0.0",
    lifespan=lifespan
)

# Rate limit error handler — must be registered before routers
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth router — all routes prefixed /authenticate
app.include_router(auth.router)

# Voice router — all routes prefixed /voice
app.include_router(voice_router)

# Code analysis router — all routes prefixed /code-analysis
app.include_router(code_analysis_router)

# Testing / research routers — mounted 
app.include_router(ab_router)          # /ab-test/*   (A/B testing)
app.include_router(benchmark_router)   # /benchmark/* (research benchmarks)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),  # lockdown in prod via env
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/", status_code=status.HTTP_200_OK, tags=["Health"])
async def root():
    return {"status": "ok", "service": "Airi RAG API"}


# ---------------------------------------------------------------------------
# RAG endpoints
# ---------------------------------------------------------------------------
@app.post("/query", tags=["RAG"])
async def rag_query(
    request: ChatRequest,
    token_payload: dict = Depends(token_verifier)
):
    """
    Non-streaming RAG query.
    Authenticated via JWT. Session memory keyed on JWT username.
    """
    session_id = token_payload["username"]
    history = get_trimmed_history(session_id)
    rag_model: RagModel = app.state.rag_model

    response = rag_model.Rag_Generator_caller(
        user_query=request.query,
        history=history
    )

    session = get_session_history(session_id)
    session.add_user_message(request.query)
    session.add_ai_message(response)

    return {"message": RagResponse(query_resp=response)}


@app.post("/query-stream", tags=["RAG"])
async def stream_rag_query(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    token_payload: dict = Depends(token_verifier)
):
    """
    Streaming RAG query.
    AI response is persisted to Redis via BackgroundTask after stream completes.
    """
    session_id = token_payload["username"]
    history = get_trimmed_history(session_id)
    session = get_session_history(session_id)
    rag_model: RagModel = app.state.rag_model

    session.add_user_message(request.query)

    def persist_ai_response(full_response: str):
        session.add_ai_message(full_response)

    def stream_generator():
        return rag_model.Rag_Generator_stream_caller(
            user_query=request.query,
            history=history,
            on_complete=lambda resp: background_tasks.add_task(persist_ai_response, resp)
        )

    return StreamingResponse(stream_generator(), media_type="text/plain")


@app.delete("/clear-history", status_code=status.HTTP_200_OK, tags=["RAG"])
async def clear_chat_history(token_payload: dict = Depends(token_verifier)):
    """Clear the authenticated user's Redis conversation history."""
    session_id = token_payload["username"]
    get_session_history(session_id).clear()
    return {"message": f"Chat history cleared for '{session_id}'."}


@app.post("/submit-logreport", tags=["Logs"])
async def create_log_entry(token_payload: dict = Depends(token_verifier)):
    pass