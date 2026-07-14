from uuid import UUID

import pytest

from app.core.errors import AppError
from app.routers.inspections import start_report
from app.schemas.common import CurrentUser
from app.schemas.inspections import InspectionStart


class FakeGateway:
    def __init__(self) -> None:
        self.assignment = {
            "id": "226b3f34-1e69-47b0-a691-1932d08001bf",
            "inspector_id": "4caa21df-b050-43af-8f99-9fdf0627aeb0",
            "garden_id": "06ac42e0-c673-4412-9660-272de2f9b9cb",
            "started_at": None,
        }
        self.inspector = {
            "id": "4caa21df-b050-43af-8f99-9fdf0627aeb0",
            "user_id": "1dbe6fde-5af0-4089-97f1-0ea6d10121c6",
            "status": "active",
        }
        self.report = None
        self.insert_calls: list[tuple[str, dict | list[dict]]] = []
        self.update_calls: list[tuple[str, dict, dict]] = []
        self.rpc_calls: list[tuple[str, dict, str | None]] = []

    async def select(
        self,
        table: str,
        *,
        token: str | None = None,
        columns: str = "*",
        filters: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
        single: bool = False,
    ):
        del token, columns, order, limit
        if table == "inspectors":
            if filters == {"id": self.inspector["id"], "status": "active"}:
                return self.inspector if single else [self.inspector]
            return None if single else []
        if table == "inspection_assignments":
            if filters == {"id": self.assignment["id"]}:
                return self.assignment if single else [self.assignment]
            return None if single else []
        if table == "inspection_reports":
            if filters == {"assignment_id": self.assignment["id"]}:
                return self.report if single else ([self.report] if self.report else [])
            return None if single else []
        raise AssertionError(f"Unexpected select table: {table}")

    async def insert(
        self,
        table: str,
        payload: dict | list[dict],
        *,
        token: str | None = None,
        upsert: bool = False,
        on_conflict: str | None = None,
    ):
        del token, upsert, on_conflict
        self.insert_calls.append((table, payload))
        if table == "inspection_reports":
            self.report = {
                "id": "b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579",
                **payload,
            }
            return [self.report]
        if table == "inspection_checklist_items":
            return payload
        raise AssertionError(f"Unexpected insert table: {table}")

    async def update(
        self,
        table: str,
        payload: dict,
        *,
        filters: dict,
        token: str | None = None,
    ):
        del token
        self.update_calls.append((table, payload, filters))
        if table == "inspection_assignments":
            self.assignment = {**self.assignment, **payload}
            return [self.assignment]
        raise AssertionError(f"Unexpected update table: {table}")

    async def rpc(self, name: str, payload: dict, *, token: str | None = None):
        self.rpc_calls.append((name, payload, token))
        return []


def admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        email="admin@urbanfarming.co.za",
        roles={"admin"},
        access_token="admin-token",
    )


@pytest.mark.asyncio
async def test_start_report_allows_admin_preview_to_act_as_selected_inspector() -> None:
    gateway = FakeGateway()

    result = await start_report(
        InspectionStart(
            assignment_id=UUID(gateway.assignment["id"]),
            gps_lat=-34.15384783876956,
            gps_lng=18.871281873126176,
        ),
        gateway,
        admin_user(),
        UUID(gateway.inspector["id"]),
    )

    assert gateway.rpc_calls == []
    assert result["report"][0]["inspector_id"] == gateway.inspector["id"]
    assert gateway.update_calls[0][0] == "inspection_assignments"
    checklist_table, checklist_payload = gateway.insert_calls[1]
    assert checklist_table == "inspection_checklist_items"
    assert isinstance(checklist_payload, list)
    assert len(checklist_payload) == 8


@pytest.mark.asyncio
async def test_start_report_requires_preview_inspector_for_admin_without_inspector_profile(
) -> None:
    gateway = FakeGateway()

    with pytest.raises(AppError) as raised:
        await start_report(
            InspectionStart(
                assignment_id=UUID(gateway.assignment["id"]),
                gps_lat=-34.15384783876956,
                gps_lng=18.871281873126176,
            ),
            gateway,
            admin_user(),
            None,
        )

    assert raised.value.status_code == 400
    assert raised.value.code == "inspector_preview_required"
