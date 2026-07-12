import asyncio
from typing import Annotated
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Header, Request
from jwt import PyJWKClient

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.infrastructure.data_gateway import DataGateway
from app.infrastructure.postgres_gateway import PostgresGateway
from app.schemas.common import CurrentUser


async def get_gateway(request: Request) -> DataGateway:
    return request.app.state.gateway


async def _supabase_user(
    token: str,
    gateway: DataGateway,
    settings: Settings,
    client: httpx.AsyncClient,
) -> CurrentUser:
    response = await client.get(
        f"{str(settings.supabase_url).rstrip('/')}/auth/v1/user",
        headers={
            "apikey": settings.supabase_anon_key or "",
            "Authorization": f"Bearer {token}",
        },
    )
    if response.status_code == 401:
        raise AppError(401, "invalid_token", "The access token is invalid or expired")
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise AppError(
            502, "auth_unavailable", "The authentication service is unavailable"
        ) from error
    payload = response.json()
    if isinstance(gateway, PostgresGateway):
        await gateway.ensure_auth_user(payload)
    user_id = UUID(str(payload["id"]))
    role_rows = await gateway.select(
        "user_roles", token=token, columns="role", filters={"user_id": user_id}
    )
    roles = {str(row["role"]) for row in role_rows or []}
    return CurrentUser(
        id=user_id,
        email=payload.get("email"),
        roles=roles,
        access_token=token,
    )


async def _oidc_user(token: str, settings: Settings, gateway: DataGateway) -> CurrentUser:
    jwk_client = PyJWKClient(str(settings.oidc_jwks_url), cache_keys=True)

    def decode() -> dict:
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )

    try:
        claims = await asyncio.to_thread(decode)
    except jwt.PyJWTError as error:
        raise AppError(401, "invalid_token", "The access token is invalid or expired") from error

    user_id = UUID(str(claims["sub"]))
    role_rows = await gateway.select("user_roles", columns="role", filters={"user_id": user_id})
    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        roles={str(row["role"]) for row in role_rows or []},
        access_token=token,
    )


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    gateway: DataGateway = request.app.state.gateway

    if settings.auth_mode == "development":
        if not x_user_id:
            raise AppError(401, "missing_identity", "X-User-Id is required in development mode")
        return CurrentUser(
            id=UUID(x_user_id),
            roles=set((x_user_role or "grower").split(",")),
            access_token="development",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "missing_token", "A bearer access token is required")
    token = authorization.split(" ", 1)[1].strip()

    if settings.auth_mode == "supabase":
        return await _supabase_user(token, gateway, settings, request.app.state.http)
    return await _oidc_user(token, settings, gateway)


def require_roles(*allowed_roles: str):
    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_any_role(*allowed_roles):
            raise AppError(403, "forbidden", "You do not have access to this operation")
        return user

    return dependency


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
GatewayDep = Annotated[DataGateway, Depends(get_gateway)]
AdminUserDep = Annotated[CurrentUser, Depends(require_roles("admin", "operator"))]
InspectorUserDep = Annotated[CurrentUser, Depends(require_roles("admin", "operator", "inspector"))]
