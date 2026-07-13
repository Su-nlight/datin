"""
app/services/memory_service.py

Same behavior as Backend/API/memory.py, but TTL/max-turns come from
injected Settings instead of os.getenv() at import time.
"""
from langchain_community.chat_message_histories import RedisChatMessageHistory
from langchain_core.messages import BaseMessage

from app.config import Settings


class MemoryService:
    def __init__(self, settings: Settings):
        self.redis_url = settings.REDIS_URL
        self.session_ttl = settings.CHAT_SESSION_TTL
        self.default_max_turns = settings.CHAT_MAX_TURNS

    def get_session_history(self, session_id: str) -> RedisChatMessageHistory:
        return RedisChatMessageHistory(
            session_id=session_id, url=self.redis_url, ttl=self.session_ttl
        )

    def get_trimmed_history(
        self, session_id: str, max_turns: int | None = None
    ) -> list[BaseMessage]:
        max_turns = max_turns or self.default_max_turns
        history = self.get_session_history(session_id)
        messages = history.messages
        max_messages = max_turns * 2
        return messages[-max_messages:] if len(messages) > max_messages else messages