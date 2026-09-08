from __future__ import annotations

import asyncio
from collections.abc import Iterable
from functools import lru_cache
from itertools import islice
from typing import Any

from firebase_admin import App, credentials, get_app, initialize_app, messaging

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.data_gateway import DataGateway

MAX_FCM_BATCH_SIZE = 500


def _chunked(values: list[str], size: int = MAX_FCM_BATCH_SIZE) -> Iterable[list[str]]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


@lru_cache
def _firebase_app(project_id: str) -> App:
    try:
        return get_app()
    except ValueError:
        pass
    return initialize_app(credentials.ApplicationDefault(), {"projectId": project_id})


def _require_project_id(settings: Settings) -> str:
    if not settings.gcp_project_id:
        raise AppError(
            500,
            "firebase_project_missing",
            "GCP_PROJECT_ID is required to send mobile push notifications",
        )
    return settings.gcp_project_id


async def resolve_push_tokens(
    gateway: DataGateway,
    *,
    token: str,
    user_ids: list[str] | None = None,
    roles: list[str] | None = None,
) -> list[str]:
    candidate_user_ids: set[str] = set(user_ids or [])
    if roles:
        role_rows = await gateway.select(
            "user_roles",
            token=token,
            admin=True,
            columns="user_id",
            filters={"role": roles},
        )
        candidate_user_ids.update(str(row["user_id"]) for row in role_rows or [])

    if not candidate_user_ids:
        return []

    token_rows = await gateway.select(
        "mobile_push_tokens",
        token=token,
        admin=True,
        columns="token",
        filters={"user_id": list(candidate_user_ids)},
        order="last_seen_at.desc",
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for row in token_rows or []:
        device_token = str(row["token"]).strip()
        if device_token and device_token not in seen:
            deduped.append(device_token)
            seen.add(device_token)
    return deduped


async def send_push_notifications(
    *,
    settings: Settings,
    title: str,
    body: str,
    tokens: list[str],
    data: dict[str, str] | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    if not tokens:
        return {"requested": 0, "sent": 0, "failed": 0, "message_ids": [], "errors": []}

    project_id = _require_project_id(settings)
    _firebase_app(project_id)

    payload_data = {key: value for key, value in (data or {}).items() if value}
    message_ids: list[str] = []
    failures: list[dict[str, str]] = []

    for token_batch in _chunked(tokens):
        multicast_message = messaging.MulticastMessage(
            tokens=token_batch,
            notification=messaging.Notification(title=title, body=body, image=image_url),
            data=payload_data or None,
        )

        batch_response = await asyncio.to_thread(
            messaging.send_each_for_multicast, multicast_message
        )

        for token, response in zip(token_batch, batch_response.responses, strict=False):
            if response.success:
                if response.message_id:
                    message_ids.append(response.message_id)
                continue
            error = response.exception
            failures.append(
                {
                    "token": token,
                    "error": getattr(error, "code", None) or error.__class__.__name__,
                }
            )

    return {
        "requested": len(tokens),
        "sent": len(message_ids),
        "failed": len(failures),
        "message_ids": message_ids,
        "errors": failures,
    }


async def send_push_to_audience(
    *,
    settings: Settings,
    gateway: DataGateway,
    token: str,
    title: str,
    body: str,
    user_ids: list[str] | None = None,
    roles: list[str] | None = None,
    data: dict[str, str] | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    tokens = await resolve_push_tokens(
        gateway,
        token=token,
        user_ids=user_ids,
        roles=roles,
    )
    return await send_push_notifications(
        settings=settings,
        title=title,
        body=body,
        tokens=tokens,
        data=data,
        image_url=image_url,
    )
