from typing import Any
from uuid import UUID

import pytest

from app.routers.data import DataMutation, mutate_data
from app.schemas.common import CurrentUser

USER_ID = UUID("8cda0b73-f149-45f9-a75b-f74be25fb174")
OTHER_USER_ID = UUID("19b2c65b-41f0-40db-bcf0-6f4a43c1cdbc")


class MutationGateway:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.filters: dict[str, Any] | None = None

    async def update(
        self, table: str, payload: dict[str, Any], *, filters: dict[str, Any], token: str
    ) -> list[dict[str, Any]]:
        self.payload = payload
        self.filters = filters
        return [{"id": "garden-1", **payload}]


@pytest.mark.asyncio
async def test_grower_cannot_transfer_owned_record_with_update_payload() -> None:
    gateway = MutationGateway()
    user = CurrentUser(id=USER_ID, roles={"grower"}, access_token="test-token")
    payload = DataMutation(
        operation="update",
        table="garden_requests",
        payload={"owner_id": str(OTHER_USER_ID), "details": {"plants": ["lettuce"]}},
        filters={"id": "request-1"},
    )

    await mutate_data(payload, gateway, user)

    assert gateway.filters == {"id": "request-1", "owner_id": str(USER_ID)}
    assert gateway.payload == {
        "owner_id": str(USER_ID),
        "details": {"plants": ["lettuce"]},
    }
