from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.schemas.common import CurrentUser
from app.schemas.gardens import CareActionCreate
from app.services.gardens import record_care_action


class FakeGateway:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, Any]] = []
        self.updated: list[tuple[str, Any]] = []

    async def select(self, table: str, **kwargs: Any) -> Any:
        if table == "properties":
            return {"id": "property-1", "owner_id": str(USER_ID), "label": "Rooftop"}
        if table == "garden_tasks":
            return [{"id": "task-1"}]
        return []

    async def insert(self, table: str, payload: Any, **kwargs: Any) -> list[dict]:
        self.inserted.append((table, payload))
        if table == "garden_activity_logs":
            return [{"id": "activity-1", **payload}]
        return [{"id": "generated-1", **payload}]

    async def update(self, table: str, payload: Any, **kwargs: Any) -> list[dict]:
        self.updated.append((table, payload))
        return [{"id": "task-1", **payload}]


USER_ID = UUID("8cda0b73-f149-45f9-a75b-f74be25fb174")


@pytest.mark.asyncio
async def test_care_action_records_activity_completes_task_and_schedules_next() -> None:
    gateway = FakeGateway()
    user = CurrentUser(
        id=USER_ID,
        roles={"grower"},
        access_token="token",
    )
    payload = CareActionCreate(
        action_type="watering",
        occurred_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        amount=12,
        unit="L",
    )

    result = await record_care_action(gateway, UUID(int=1), payload, user)

    assert result["title"] == "Watered Rooftop"
    assert result["nextDueAt"] == "2026-07-14"
    assert [table for table, _payload in gateway.inserted] == [
        "garden_activity_logs",
        "garden_tasks",
    ]
    assert gateway.updated[0][1]["status"] == "done"
