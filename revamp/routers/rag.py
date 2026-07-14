"""
app/routers/rag.py

Replaces the /query, /query-stream, /clear-history endpoints that used
to live directly in main.py. The router does nothing but call the
service — no RagModel/PineconeDB/llm construction happens here.
"""
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from starlette import status

from app.dependencies import get_memory_service, get_rag_service
from app.models.rag_models import ChatRequest, RagResponse
from app.routers.auth import token_verifier
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService

router = APIRouter(prefix="/rag", tags=["RAG"])


@router.post("/query")
async def rag_query(
    request: ChatRequest,
    token_payload: dict = Depends(token_verifier),
    rag_service: RagService = Depends(get_rag_service),
    memory: MemoryService = Depends(get_memory_service),
):
    session_id = token_payload["username"]
    history = memory.get_trimmed_history(session_id)

    response = rag_service.generate(user_query=request.query, history=history)

    session = memory.get_session_history(session_id)
    session.add_user_message(request.query)
    session.add_ai_message(response)

    return {"message": RagResponse(query_resp=response)}


@router.post("/query-stream")
async def stream_rag_query(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    token_payload: dict = Depends(token_verifier),
    rag_service: RagService = Depends(get_rag_service),
    memory: MemoryService = Depends(get_memory_service),
):
    session_id = token_payload["username"]
    history = memory.get_trimmed_history(session_id)
    session = memory.get_session_history(session_id)

    session.add_user_message(request.query)

    def persist_ai_response(full_response: str):
        session.add_ai_message(full_response)

    def stream_generator():
        return rag_service.generate_stream(
            user_query=request.query,
            history=history,
            on_complete=lambda resp: background_tasks.add_task(persist_ai_response, resp),
        )

    return StreamingResponse(stream_generator(), media_type="text/plain")


@router.delete("/clear-history", status_code=status.HTTP_200_OK)
async def clear_chat_history(
    token_payload: dict = Depends(token_verifier),
    memory: MemoryService = Depends(get_memory_service),
):
    session_id = token_payload["username"]
    memory.get_session_history(session_id).clear()
    return {"message": f"Chat history cleared for '{session_id}'."}