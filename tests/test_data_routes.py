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

    async def select(
        self,
        table: str,
        *,
        token: str | None = None,
        admin: bool = False,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
        single: bool = False,
    ) -> list[dict[str, Any]]:
        return []

    async def delete(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        token: str | None = None,
        admin: bool = False,
    ) -> None:
        return None


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


class InspectionHistoryGateway(MutationGateway):
    async def select(self, table: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "inspection-1"}] if table == "inspection_reports" else []


@pytest.mark.asyncio
async def test_admin_cannot_delete_property_with_inspection_history() -> None:
    gateway = InspectionHistoryGateway()
    user = CurrentUser(id=USER_ID, roles={"admin"}, access_token="test-token")
    payload = DataMutation(
        operation="delete",
        table="properties",
        filters={"id": "property-1"},
    )

    with pytest.raises(Exception) as exc_info:
        await mutate_data(payload, gateway, user)

    assert getattr(exc_info.value, "code", None) == "property_has_inspection_history"
