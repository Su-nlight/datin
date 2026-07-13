"""
app/services/auth_service.py

Token creation, hashing, and verification logic pulled out of the old
auth.py so the router only has to call methods on an injected service.
Settings validation (missing JWT_SECRET_KEY etc.) now happens for free
via pydantic-settings at Settings() construction — no more manual
`if not SECRET_KEY: raise RuntimeError(...)` guard.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import Settings

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Constant-time dummy hash used to prevent username-enumeration via timing
_DUMMY_HASH = "$2b$12$KIXQz3P1Dz5E8G1Kz5E8G1Kz5E8G1Kz5E8G1Kz5E8G1Kz5E8G1K"


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def hash_password(self, password: str) -> str:
        return bcrypt_context.hash(password)

    def verify_password(self, password: str, hashed: str | None) -> bool:
        check_hash = hashed if hashed else _DUMMY_HASH
        return bcrypt_context.verify(password, check_hash)

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _create_token(self, data: dict, secret: str, expires_delta: timedelta) -> str:
        payload = {
            **data,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + expires_delta,
        }
        return jwt.encode(payload, key=secret, algorithm=self.settings.JWT_ALGO)

    def create_access_token(self, username: str) -> str:
        return self._create_token(
            {"username": username, "type": "access"},
            self.settings.JWT_SECRET_KEY,
            timedelta(minutes=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

    def create_refresh_token(self, username: str) -> str:
        return self._create_token(
            {"username": username, "type": "refresh"},
            self.settings.JWT_REFRESH_SECRET_KEY,
            timedelta(days=self.settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )

    def decode_access_token(self, token: str) -> dict:
        """Raises JWTError on invalid/expired token."""
        payload = jwt.decode(token, self.settings.JWT_SECRET_KEY, algorithms=[self.settings.JWT_ALGO])
        if payload.get("username") is None or payload.get("type") != "access":
            raise JWTError("Not a valid access token")
        return payload

    def decode_refresh_token(self, token: str) -> dict:
        payload = jwt.decode(token, self.settings.JWT_REFRESH_SECRET_KEY, algorithms=[self.settings.JWT_ALGO])
        if payload.get("username") is None or payload.get("type") != "refresh":
            raise JWTError("Not a valid refresh token")
        return payload