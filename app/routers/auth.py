import asyncio
from typing import Annotated, Any
from uuid import UUID

import bcrypt
import httpx
import jwt
from fastapi import APIRouter, Header, Request
from jwt import PyJWKClient

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CurrentUserDep, GatewayDep
from app.core.tokens import (
    decode_token,
    mint_access_token,
    mint_recovery_token,
    mint_refresh_token,
)
from app.infrastructure.auth_store import NativeAuthStore
from app.infrastructure.data_gateway import DataGateway
from app.infrastructure.email import MailMessage
from app.schemas.auth import (
    GoogleSignInRequest,
    LoginRequest,
    LogoutRequest,
    PasswordResetRequest,
    PasswordUpdateRequest,
    RefreshRequest,
    SignupRequest,
)
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_PASSTHROUGH_STATUSES = {400, 401, 403, 404, 409, 422, 429}
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_google_jwk_client: PyJWKClient | None = None


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "missing_token", "A bearer access token is required")
    return authorization.split(" ", 1)[1].strip()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _auth_store(request: Request) -> NativeAuthStore:
    store = getattr(request.app.state, "auth_store", None)
    if store is None:
        raise AppError(501, "unsupported_auth_mode", "Native authentication is not enabled")
    return store


# ── Native (backend-owned) flow ─────────────────────────────────────────────


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    created_at = row.get("created_at")
    return {
        "id": str(row["id"]),
        "email": row.get("email"),
        "user_metadata": row.get("raw_user_meta_data") or {},
        "created_at": created_at.isoformat() if created_at else None,
    }


async def _native_session(
    settings: Settings, store: NativeAuthStore, user_id: UUID, email: str | None
) -> dict[str, Any]:
    access_token, expires_in = mint_access_token(settings, user_id, email)
    refresh_token, token_id, expires_at = mint_refresh_token(settings, user_id)
    await store.store_refresh_token(token_id, user_id, expires_at)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_token": refresh_token,
    }


async def _native_signup(payload: SignupRequest, request: Request) -> dict:
    settings, store = _settings(request), _auth_store(request)
    password_hash = await asyncio.to_thread(_hash_password, payload.password)
    user = await store.create_user(
        email=str(payload.email),
        password_hash=password_hash,
        user_metadata={"full_name": payload.full_name, "role": payload.role},
    )
    user_id = UUID(str(user["id"]))
    # The replayed handle_new_user() trigger normally provisions these rows;
    # this covers databases bootstrapped without it.
    await store.ensure_provisioned(user_id, full_name=payload.full_name, role=payload.role)
    roles = await store.user_roles(user_id) or [payload.role]
    session = await _native_session(settings, store, user_id, user.get("email"))
    return {
        "user": _public_user(user),
        "session": session,
        "roles": roles,
        "confirmation_required": False,
    }


async def _native_login(payload: LoginRequest, request: Request) -> dict:
    settings, store = _settings(request), _auth_store(request)
    user = await store.get_user_by_email(str(payload.email))
    password_hash = user.get("encrypted_password") if user else None
    valid = await asyncio.to_thread(_verify_password, payload.password, password_hash)
    if not user or not valid:
        raise AppError(401, "invalid_credentials", "Invalid login credentials")
    user_id = UUID(str(user["id"]))
    await store.touch_last_sign_in(user_id)
    roles = await store.user_roles(user_id)
    session = await _native_session(settings, store, user_id, user.get("email"))
    return {"user": _public_user(user), "session": session, "roles": roles}


async def _native_refresh(payload: RefreshRequest, request: Request) -> dict:
    settings, store = _settings(request), _auth_store(request)
    claims = decode_token(settings, payload.refresh_token, "refresh")
    token_id = UUID(str(claims["jti"]))
    user_id = UUID(str(claims["sub"]))
    if not await store.is_refresh_token_active(token_id):
        raise AppError(401, "invalid_token", "The refresh token is invalid or revoked")
    user = await store.get_user_by_id(user_id)
    if not user:
        raise AppError(401, "invalid_token", "The refresh token is invalid or revoked")
    await store.revoke_refresh_token(token_id)
    roles = await store.user_roles(user_id)
    session = await _native_session(settings, store, user_id, user.get("email"))
    return {"user": _public_user(user), "session": session, "roles": roles}


async def _google_claims(settings: Settings, id_token: str) -> dict:
    if not settings.google_client_id:
        raise AppError(501, "google_signin_not_configured", "GOOGLE_CLIENT_ID is not configured")
    global _google_jwk_client
    if _google_jwk_client is None:
        _google_jwk_client = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True)

    def decode() -> dict:
        signing_key = _google_jwk_client.get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=GOOGLE_ISSUERS,
        )

    try:
        return await asyncio.to_thread(decode)
    except jwt.PyJWTError as error:
        raise AppError(401, "invalid_token", "The Google ID token is invalid") from error


# ── Supabase GoTrue proxy (AUTH_MODE=supabase) ──────────────────────────────


async def _gotrue(
    request: Request,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    token: str | None = None,
) -> dict:
    settings = _settings(request)
    if settings.auth_mode != "supabase":
        raise AppError(
            501,
            "unsupported_auth_mode",
            "This endpoint is only available when AUTH_MODE=supabase or native",
        )
    headers = {"apikey": settings.supabase_anon_key or ""}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    client: httpx.AsyncClient = request.app.state.http
    try:
        response = await client.request(
            method,
            f"{str(settings.supabase_url).rstrip('/')}/auth/v1/{path}",
            json=json,
            params=params,
            headers=headers,
        )
    except httpx.HTTPError as error:
        raise AppError(
            502, "auth_unavailable", "The authentication service is unavailable"
        ) from error
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = {}
        message = (
            detail.get("msg")
            or detail.get("error_description")
            or detail.get("message")
            or "Authentication request failed"
        )
        code = detail.get("error_code") or detail.get("error") or "auth_error"
        status = response.status_code if response.status_code in _PASSTHROUGH_STATUSES else 502
        raise AppError(status, str(code), str(message))
    if not response.content:
        return {}
    return response.json()


async def _load_roles(gateway: DataGateway, token: str, user_id: str) -> list[str]:
    rows = await gateway.select(
        "user_roles", token=token, columns="role", filters={"user_id": UUID(user_id)}
    )
    return sorted({str(row["role"]) for row in rows or []})


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/signup", status_code=201)
async def signup(payload: SignupRequest, request: Request, gateway: GatewayDep) -> dict:
    if _settings(request).auth_mode == "native":
        return await _native_signup(payload, request)
    # The handle_new_user() trigger reads `role` from the metadata and provisions
    # profiles, user_roles, grower_stats, user_settings (and inspectors) rows.
    params = {"redirect_to": str(payload.redirect_to)} if payload.redirect_to else None
    data = await _gotrue(
        request,
        "POST",
        "signup",
        json={
            "email": payload.email,
            "password": payload.password,
            "data": {"full_name": payload.full_name, "role": payload.role},
        },
        params=params,
    )
    # With email confirmation enabled GoTrue returns the bare user object;
    # otherwise it returns a full session envelope.
    session = data if data.get("access_token") else None
    user = data.get("user") if session else data
    if session:
        roles = await _load_roles(gateway, session["access_token"], user["id"])
    else:
        roles = [payload.role]
    return {
        "user": user,
        "session": session,
        "roles": roles,
        "confirmation_required": session is None,
    }


@router.post("/login")
async def login(payload: LoginRequest, request: Request, gateway: GatewayDep) -> dict:
    if _settings(request).auth_mode == "native":
        return await _native_login(payload, request)
    data = await _gotrue(
        request,
        "POST",
        "token",
        params={"grant_type": "password"},
        json={"email": payload.email, "password": payload.password},
    )
    user = data.pop("user", None)
    roles = await _load_roles(gateway, data["access_token"], user["id"]) if user else []
    return {"user": user, "session": data, "roles": roles}


@router.post("/refresh")
async def refresh(payload: RefreshRequest, request: Request, gateway: GatewayDep) -> dict:
    if _settings(request).auth_mode == "native":
        return await _native_refresh(payload, request)
    data = await _gotrue(
        request,
        "POST",
        "token",
        params={"grant_type": "refresh_token"},
        json={"refresh_token": payload.refresh_token},
    )
    user = data.pop("user", None)
    roles = await _load_roles(gateway, data["access_token"], user["id"]) if user else []
    return {"user": user, "session": data, "roles": roles}


@router.post("/google")
async def google_sign_in(payload: GoogleSignInRequest, request: Request) -> dict:
    settings = _settings(request)
    if settings.auth_mode != "native":
        raise AppError(501, "unsupported_auth_mode", "Google sign-in requires AUTH_MODE=native")
    store = _auth_store(request)
    claims = await _google_claims(settings, payload.id_token)
    email = claims.get("email")
    if not email or not claims.get("email_verified"):
        raise AppError(401, "unverified_email", "The Google account email is not verified")
    user = await store.get_user_by_email(email)
    if not user:
        user = await store.create_user(
            email=email,
            password_hash=None,
            user_metadata={"full_name": claims.get("name"), "role": payload.role},
            app_metadata={"provider": "google", "google_sub": claims.get("sub")},
        )
        await store.ensure_provisioned(
            UUID(str(user["id"])), full_name=claims.get("name"), role=payload.role
        )
    user_id = UUID(str(user["id"]))
    await store.touch_last_sign_in(user_id)
    roles = await store.user_roles(user_id)
    session = await _native_session(settings, store, user_id, user.get("email"))
    return {"user": _public_user(user), "session": session, "roles": roles}


@router.post("/logout")
async def logout(
    request: Request,
    payload: LogoutRequest | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> MessageResponse:
    settings = _settings(request)
    token = _bearer_token(authorization)
    if settings.auth_mode == "native":
        claims = decode_token(settings, token, "access")
        await _auth_store(request).revoke_all_refresh_tokens(UUID(str(claims["sub"])))
        return MessageResponse(message="Signed out")
    scope = payload.scope if payload else "global"
    await _gotrue(request, "POST", "logout", params={"scope": scope}, token=token)
    return MessageResponse(message="Signed out")


@router.post("/password-reset")
async def password_reset(payload: PasswordResetRequest, request: Request) -> MessageResponse:
    settings = _settings(request)
    generic = MessageResponse(message="If the email exists, a reset link has been sent")
    if settings.auth_mode == "native":
        store = _auth_store(request)
        user = await store.get_user_by_email(str(payload.email))
        if user:
            token = mint_recovery_token(settings, UUID(str(user["id"])), user.get("email"))
            if payload.redirect_to:
                separator = "&" if "?" in str(payload.redirect_to) else "?"
                body = (
                    "Reset your Urban Farming password using this link "
                    "(valid for 30 minutes):\n\n"
                    f"{payload.redirect_to}{separator}token={token}&type=recovery"
                )
            else:
                body = (
                    "Use this recovery token to reset your Urban Farming password "
                    f"(valid for 30 minutes):\n\n{token}"
                )
            await request.app.state.email.send(
                MailMessage(
                    to=str(user["email"]),
                    subject="Reset your Urban Farming password",
                    text=body,
                )
            )
        return generic
    params = {"redirect_to": str(payload.redirect_to)} if payload.redirect_to else None
    try:
        await _gotrue(request, "POST", "recover", json={"email": payload.email}, params=params)
    except AppError as error:
        # Never reveal whether the address has an account; only surface
        # rate-limit and upstream availability problems.
        if error.status_code in {429, 502}:
            raise
    return generic


@router.put("/password")
async def update_password(
    payload: PasswordUpdateRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> MessageResponse:
    settings = _settings(request)
    token = _bearer_token(authorization)
    if settings.auth_mode == "native":
        store = _auth_store(request)
        claims = decode_token(settings, token, "access", "recovery")
        user_id = UUID(str(claims["sub"]))
        password_hash = await asyncio.to_thread(_hash_password, payload.password)
        await store.set_password(user_id, password_hash)
        await store.revoke_all_refresh_tokens(user_id)
        return MessageResponse(message="Password updated")
    await _gotrue(request, "PUT", "user", json={"password": payload.password}, token=token)
    return MessageResponse(message="Password updated")


@router.get("/me")
async def me(user: CurrentUserDep) -> dict:
    return {"id": str(user.id), "email": user.email, "roles": sorted(user.roles)}
