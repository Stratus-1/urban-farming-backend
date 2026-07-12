"""Backend-minted JWTs for AUTH_MODE=native."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from app.core.config import Settings
from app.core.errors import AppError

ALGORITHM = "HS256"


def mint_access_token(settings: Settings, user_id: UUID, email: str | None) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_in = settings.access_token_ttl_seconds
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(claims, settings.jwt_secret or "", algorithm=ALGORITHM), expires_in


def mint_refresh_token(settings: Settings, user_id: UUID) -> tuple[str, UUID, datetime]:
    now = datetime.now(UTC)
    token_id = uuid4()
    expires_at = now + timedelta(seconds=settings.refresh_token_ttl_seconds)
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "jti": str(token_id),
        "type": "refresh",
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(claims, settings.jwt_secret or "", algorithm=ALGORITHM), token_id, expires_at


def mint_recovery_token(settings: Settings, user_id: UUID, email: str | None) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "email": email,
        "type": "recovery",
        "iat": now,
        "exp": now + timedelta(minutes=30),
    }
    return jwt.encode(claims, settings.jwt_secret or "", algorithm=ALGORITHM)


def decode_token(settings: Settings, token: str, *expected_types: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret or "",
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as error:
        raise AppError(401, "invalid_token", "The access token is invalid or expired") from error
    if expected_types and claims.get("type") not in expected_types:
        raise AppError(401, "invalid_token", "The access token is invalid or expired")
    return claims
