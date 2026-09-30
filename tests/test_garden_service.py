from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.schemas.common import CurrentUser
from app.schemas.gardens import CareActionCreate
from app.services.gardens import latest_inspection_report, record_care_action


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


class InspectionReportGateway:
    def __init__(self, reports: list[dict[str, Any]]) -> None:
        self.reports = reports
        self.select_call: dict[str, Any] | None = None

    async def select(self, table: str, **kwargs: Any) -> Any:
        self.select_call = {"table": table, **kwargs}
        filters = kwargs.get("filters", {})
        reports = [
            report
            for report in self.reports
            if report.get("garden_id") == filters.get("garden_id")
            and report.get("assessment_status") == filters.get("assessment_status")
        ]
        reports.sort(key=lambda report: report.get("submitted_at") or "", reverse=True)
        if kwargs.get("limit"):
            reports = reports[: kwargs["limit"]]
        return reports[0] if kwargs.get("single") and reports else None


@pytest.mark.asyncio
async def test_latest_inspection_report_filters_status_before_limiting() -> None:
    gateway = InspectionReportGateway(
        [
            {
                "id": "draft-report",
                "garden_id": "property-1",
                "assessment_status": "draft",
                "submitted_at": None,
            },
            {
                "id": "submitted-report",
                "garden_id": "property-1",
                "assessment_status": "submitted_for_approval",
                "submitted_at": "2026-09-29T12:00:00+00:00",
            },
        ]
    )

    report = await latest_inspection_report(
        gateway,
        "property-1",
        assessment_status="submitted_for_approval",
        token="admin-token",
    )

    assert report is not None
    assert report["id"] == "submitted-report"
    assert gateway.select_call == {
        "table": "inspection_reports",
        "token": "admin-token",
        "filters": {
            "garden_id": "property-1",
            "assessment_status": "submitted_for_approval",
        },
        "order": "submitted_at.desc",
        "limit": 1,
        "single": True,
    }
