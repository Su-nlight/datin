from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import timedelta, datetime
import os
from dotenv import load_dotenv
from typing import Optional


# Initialize an API router for authentication-related routes
router = APIRouter(
    prefix='/authenticate',  # Prefix for all routes in this router
    tags=['authenticate']  # Tag for grouping routes in the FastAPI documentation
)
load_dotenv("API.env")

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-for-jwt")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def generate_payload(username: str, expiration: Optional[timedelta] = None):
    """
    Generate a JWT payload for a user.

    Args:
        username (str): Username to include in the token.
        expiration (timedelta | None): Optional expiration time for the token.

    Returns:
        str: The generated JWT token.
    """
    if expiration is None:
        expiration = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)  # Set default expiration time to 1 hour if not provided
    payload = {
        "username": username,  # Include the username in the payload
        "iat": datetime.utcnow(),  # Issued at time (current time)
        "exp": datetime.utcnow() + expiration  # Expiration time for the token
    }
    token = jwt.encode(payload, key=SECRET_KEY, algorithm=ALGORITHM)  # Encode the payload into a JWT token using HS256
    return token  # Return the generated token

async def create_user():
    pass