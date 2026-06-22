import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import settings


def generate_otp_code() -> str:
    """6-digit code, e.g. '042918'."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    """We never store the raw OTP code, only this hash — same idea as a password hash."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp_hash(code: str, code_hash: str) -> bool:
    return hash_otp(code) == code_hash


def _create_token(subject: str, role: str, expires_minutes: int, token_type: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "role": role, "type": token_type, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(user_id, role, settings.access_token_expire_minutes, "access")


def create_refresh_token(user_id: str, role: str) -> str:
    return _create_token(user_id, role, settings.refresh_token_expire_minutes, "refresh")


def decode_token(token: str) -> dict:
    """Raises jose.JWTError if the token is invalid or expired."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
