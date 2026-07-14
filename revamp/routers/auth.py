"""
app/routers/auth.py

Same endpoints as Backend/API/auth.py, restructured so the router has
no module-level SECRET_KEY/REFRESH_SECRET_KEY, no manual "raise
RuntimeError if missing" guard (pydantic-settings does that at startup
now), and gets AuthService/DatabaseService via Depends() instead of
importing a `Database` class with @staticmethod calls.

`token_verifier` is exported from here because it's the one dependency
every other protected router needs (rag.py, code_analysis router, etc.)
— this mirrors where it lived before, just wired through DI now.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette import status

from app.dependencies import get_auth_service, get_database_service
from app.models.auth_models import CreateUserDatabase, RefreshRequest, Token, UserCreate
from app.services.auth_service import AuthService
from app.services.database_service import DatabaseService

oauth2_bearer = OAuth2PasswordBearer(tokenUrl="authenticate/login")
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/authenticate", tags=["authenticate"])


def token_verifier(
    token: str = Depends(oauth2_bearer),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token is invalid or expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        return auth_service.decode_access_token(token)
    except JWTError:
        raise credentials_exception


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def create_user(
    create_new_user: UserCreate,
    auth_service: AuthService = Depends(get_auth_service),
    db: DatabaseService = Depends(get_database_service),
):
    new_user_request = CreateUserDatabase(
        username=create_new_user.username,
        hashed_password=auth_service.hash_password(create_new_user.password),
        email=create_new_user.email,
        name=create_new_user.name,
        wallet_address=create_new_user.wallet_address or "",
    )
    db.create_user(user_data=new_user_request)
    return {"message": f"User '{new_user_request.username}' created successfully."}


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def generate_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
    db: DatabaseService = Depends(get_database_service),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    hashed_pass = db.get_user_pass(username=form_data.username)
    # Always run verify even if user not found — prevents timing-based enumeration
    password_valid = auth_service.verify_password(form_data.password, hashed_pass)

    if not hashed_pass or not password_valid:
        raise credentials_exception

    access_token = auth_service.create_access_token(username=form_data.username)
    refresh_token = auth_service.create_refresh_token(username=form_data.username)

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=auth_service.settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    db.store_refresh_token(
        username=form_data.username,
        token_hash=auth_service.hash_token(refresh_token),
        expires_at=expires_at,
    )

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "Bearer"}


@router.post("/refresh", response_model=Token, status_code=status.HTTP_200_OK)
async def refresh_access_token(
    body: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
    db: DatabaseService = Depends(get_database_service),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token is invalid or expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth_service.decode_refresh_token(body.refresh_token)
    except JWTError:
        raise credentials_exception

    username = payload["username"]
    stored = db.get_refresh_token(username)
    if not stored or stored["token_hash"] != auth_service.hash_token(body.refresh_token):
        raise credentials_exception
    if stored["expires_at"] < datetime.now(timezone.utc):
        raise credentials_exception

    new_access = auth_service.create_access_token(username)
    new_refresh = auth_service.create_refresh_token(username)
    new_expires = datetime.now(timezone.utc) + timedelta(
        days=auth_service.settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    db.store_refresh_token(
        username=username, token_hash=auth_service.hash_token(new_refresh), expires_at=new_expires
    )

    return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "Bearer"}


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    token_payload: dict = Depends(token_verifier),
    db: DatabaseService = Depends(get_database_service),
):
    db.revoke_refresh_token(token_payload["username"])
    return {"message": "Logged out successfully."}


@router.get("/verify-token", status_code=status.HTTP_200_OK)
async def verify_token(token_payload: dict = Depends(token_verifier)):
    return {"message": "Token is valid.", "username": token_payload["username"]}