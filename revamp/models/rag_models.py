from pydantic import BaseModel, Field


class RagResponse(BaseModel):
    query_resp: str


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=3000)