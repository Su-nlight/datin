from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    wallet_address: Optional[str] = Field(None, description="Blockchain wallet address (e.g., Ethereum address)")
    name: str

    class Config:
        schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "password": "securepassword123",
                "wallet_address": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
                "name": "User Actual Name"
            }
        }

class CreateUserDatabase(BaseModel):
    email: EmailStr
    username: str
    hashed_password: str
    wallet_address: str
    name: str

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

class ReportLog(BaseModel):
    title: str
    severity: int = Field(..., ge=1, le=5, description="Severity level between 1 to 5")

class LogReport(BaseModel):
    owner: str
    content: str
    tokenAddress: str
    reward: str