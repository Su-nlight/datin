from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    wallet_address: Optional[str] = Field(None, description="Blockchain wallet address")
    name: str


class CreateUserDatabase(BaseModel):
    email: EmailStr
    username: str
    hashed_password: str
    wallet_address: str = ""
    name: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class TokenData(BaseModel):
    username: Optional[str] = None