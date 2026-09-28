"""Google-issued ID-token verification for explicitly allowlisted service callers."""

from __future__ import annotations

import asyncio

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


class WorkloadIdentityError(ValueError):
    """Raised when a service identity is absent or outside the configured trust."""


def _verify(token: str, audience: str, service_account_email: str) -> None:
    try:
        claims = id_token.verify_oauth2_token(
            token,
            GoogleAuthRequest(),
            audience=audience,
            clock_skew_in_seconds=30,
        )
    except Exception as error:
        raise WorkloadIdentityError("Service identity token is invalid") from error

    if (
        claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
        or str(claims.get("email", "")).casefold() != service_account_email.casefold()
        or claims.get("email_verified") is not True
        or not claims.get("sub")
    ):
        raise WorkloadIdentityError("Service identity is not allowed")


async def verify_workload_identity(
    token: str, *, audience: str, service_account_email: str
) -> None:
    """Verify Google signature, exact audience and the one configured service account."""
    if not token or len(token) > 16_384 or not audience or not service_account_email:
        raise WorkloadIdentityError("Service identity is not configured")
    await asyncio.to_thread(_verify, token, audience, service_account_email)
