import os
from langchain_community.chat_message_histories import RedisChatMessageHistory
from langchain_core.messages import BaseMessage
from dotenv import load_dotenv

load_dotenv("API.env")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SESSION_TTL = int(os.getenv("CHAT_SESSION_TTL", 86400))   # default: 24h
DEFAULT_MAX_TURNS = int(os.getenv("CHAT_MAX_TURNS", 8))    # 8 turn pairs = 16 messages


def get_session_history(session_id: str) -> RedisChatMessageHistory:
    """
    Returns a RedisChatMessageHistory for the given session_id.
    session_id is the JWT username — no client-side UUID needed.
    TTL is reset on every write by RedisChatMessageHistory internally.
    """
    return RedisChatMessageHistory(
        session_id=session_id,
        url=REDIS_URL,
        ttl=SESSION_TTL
    )


def get_trimmed_history(session_id: str, max_turns: int = DEFAULT_MAX_TURNS) -> list[BaseMessage]:
    """
    Returns the last `max_turns` pairs (user + assistant) from history.
    Prevents context bloat — critical for Ollama/Llama's smaller context window.
    
    max_turns=8 → last 16 messages retained.
    """
    history = get_session_history(session_id)
    messages = history.messages
    max_messages = max_turns * 2  # each turn = 1 human + 1 AI message
    return messages[-max_messages:] if len(messages) > max_messages else messages