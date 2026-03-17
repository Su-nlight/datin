import os
import hashlib
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette import status
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import timedelta, datetime, timezone
from dotenv import load_dotenv
from typing import Optional
from models import UserCreate, Token, CreateUserDatabase, RefreshRequest
from database import Database

load_dotenv("API.env")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
REFRESH_SECRET_KEY = os.getenv("JWT_REFRESH_SECRET_KEY")  # separate secret for refresh
ALGORITHM = os.getenv("JWT_ALGO", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

if not SECRET_KEY or not REFRESH_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY and JWT_REFRESH_SECRET_KEY must be set in API.env")

# ---------------------------------------------------------------------------
# Security primitives
# ---------------------------------------------------------------------------
bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_bearer = OAuth2PasswordBearer(tokenUrl="authenticate/login")
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix='/authenticate', tags=['authenticate'])


# ---------------------------------------------------------------------------
# Token utilities
# ---------------------------------------------------------------------------

def _create_token(data: dict, secret: str, expires_delta: timedelta) -> str:
    payload = {
        **data,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    return jwt.encode(payload, key=secret, algorithm=ALGORITHM)


def create_access_token(username: str) -> str:
    return _create_token(
        {"username": username, "type": "access"},
        SECRET_KEY,
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(username: str) -> str:
    return _create_token(
        {"username": username, "type": "refresh"},
        REFRESH_SECRET_KEY,
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )


def _hash_token(token: str) -> str:
    """SHA-256 hash of refresh token for safe DB storage — never store raw tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def token_verifier(token: str = Depends(oauth2_bearer)) -> dict:
    """
    Dependency — validates access token and returns decoded payload.
    Type claim prevents refresh tokens being used as access tokens.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token is invalid or expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("username")
        token_type: str = payload.get("type")

        if username is None or token_type != "access":
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post('/register', status_code=status.HTTP_201_CREATED)
async def create_user(create_new_user: UserCreate):
    """
    Register a new user.
    Password is hashed before persistence — raw password never touches the DB.
    """
    new_user_request = CreateUserDatabase(
        username=create_new_user.username,
        hashed_password=bcrypt_context.hash(create_new_user.password),
        email=create_new_user.email,
        name=create_new_user.name,
        wallet_address=create_new_user.wallet_address or ""
    )
    Database.create_user(user_data=new_user_request)
    return {'message': f"User '{new_user_request.username}' created successfully."}


@router.post('/login', response_model=Token, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")          # brute-force guard — 10 attempts per IP per minute
async def generate_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticate user and issue access + refresh token pair.
    Refresh token is hashed before DB storage.
    Timing-safe comparison via bcrypt.verify prevents username enumeration.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    hashed_pass = Database.get_user_pass(username=form_data.username)

    # Always run bcrypt.verify even if user not found — prevents timing-based enumeration
    dummy_hash = "$2b$12$KIXQz3P1Dz5E8G1Kz5E8G1Kz5E8G1Kz5E8G1Kz5E8G1Kz5E8G1K"
    check_hash = hashed_pass if hashed_pass else dummy_hash
    password_valid = bcrypt_context.verify(form_data.password, check_hash)

    if not hashed_pass or not password_valid:
        raise credentials_exception

    access_token = create_access_token(username=form_data.username)
    refresh_token = create_refresh_token(username=form_data.username)

    # Store hashed refresh token with expiry for server-side validation
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    Database.store_refresh_token(
        username=form_data.username,
        token_hash=_hash_token(refresh_token),
        expires_at=expires_at
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer"
    }


@router.post('/refresh', response_model=Token, status_code=status.HTTP_200_OK)
async def refresh_access_token(body: RefreshRequest):
    """
    Issue a new access token given a valid refresh token.
    Validates: JWT signature, type claim, expiry, and DB hash match.
    Implements refresh token rotation — old token is revoked on use.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token is invalid or expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(body.refresh_token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("username")
        token_type: str = payload.get("type")

        if username is None or token_type != "refresh":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Server-side validation — ensures token wasn't revoked after issuance
    stored = Database.get_refresh_token(username)
    if not stored or stored["token_hash"] != _hash_token(body.refresh_token):
        raise credentials_exception
    if stored["expires_at"] < datetime.now(timezone.utc):
        raise credentials_exception

    # Rotate: revoke old, issue new pair
    new_access = create_access_token(username)
    new_refresh = create_refresh_token(username)
    new_expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    Database.store_refresh_token(
        username=username,
        token_hash=_hash_token(new_refresh),
        expires_at=new_expires
    )

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "Bearer"
    }


@router.post('/logout', status_code=status.HTTP_200_OK)
async def logout(token_payload: dict = Depends(token_verifier)):
    """
    Revoke the user's refresh token server-side.
    Access token expiry is handled passively (stateless JWT — short TTL is the mitigation).
    """
    Database.revoke_refresh_token(token_payload["username"])
    return {"message": "Logged out successfully."}


@router.get("/verify-token", status_code=status.HTTP_200_OK)
async def verify_token(token_payload: dict = Depends(token_verifier)):
    """Lightweight liveness check for the client to validate token state."""
    return {"message": "Token is valid.", "username": token_payload["username"]}