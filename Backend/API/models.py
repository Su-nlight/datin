from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    wallet_address: Optional[str] = Field(None, description="Blockchain wallet address (e.g., Ethereum address)")

    class Config:
        schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "password": "securepassword123",
                "wallet_address": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F"
            }
        }

class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    wallet_address: Optional[str] = None
    is_active: bool
    oauth_provider: Optional[str] = None

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class GoogleAuthRequest(BaseModel):
    code: str

class RagResponse(BaseModel):
    query_resp : str