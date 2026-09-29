from uuid import UUID

import pytest

from app.core.errors import AppError
from app.infrastructure.postgres_gateway import PostgresGateway
from app.routers.inspections import CHECKLIST_TEMPLATE, start_report, submit_for_approval
from app.schemas.common import CurrentUser
from app.schemas.inspections import InspectionAssessment, InspectionStart


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
        self.checklist_items: list[dict] = []
        self.photos: list[dict] = []
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
            if str(filters.get("user_id")) == self.inspector["user_id"]:
                return self.inspector if single else [self.inspector]
            return None if single else []
        if table == "inspection_assignments":
            if filters == {"id": self.assignment["id"]}:
                return self.assignment if single else [self.assignment]
            return None if single else []
        if table == "inspection_reports":
            if filters == {"assignment_id": self.assignment["id"]}:
                return self.report if single else ([self.report] if self.report else [])
            if self.report and filters == {"id": self.report["id"]}:
                return self.report if single else [self.report]
            return None if single else []
        if table == "inspection_checklist_items":
            return self.checklist_items
        if table == "inspection_photos":
            return self.photos
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
        if table == "inspection_reports" and self.report:
            self.report = {**self.report, **payload}
            return [self.report]
        raise AssertionError(f"Unexpected update table: {table}")

    async def rpc(self, name: str, payload: dict, *, token: str | None = None):
        self.rpc_calls.append((name, payload, token))
        return []


class FakePostgresGateway(FakeGateway, PostgresGateway):
    def __init__(self) -> None:
        FakeGateway.__init__(self)
        self.start_report_calls: list[dict] = []

    async def start_inspection_report(self, **kwargs):
        self.start_report_calls.append(kwargs)
        return {
            "id": "b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579",
            "assignment_id": str(kwargs["assignment_id"]),
            "inspector_id": str(kwargs["inspector_id"]),
            "garden_id": self.assignment["garden_id"],
            "overall_status": "pending",
        }


def admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        email="admin@urbanfarming.co.za",
        roles={"admin"},
        access_token="admin-token",
    )


def inspector_user(gateway: FakeGateway) -> CurrentUser:
    return CurrentUser(
        id=UUID(gateway.inspector["user_id"]),
        email="inspector@urbanfarming.co.za",
        roles={"inspector"},
        access_token="inspector-token",
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
async def test_postgres_start_report_uses_atomic_backend_path_instead_of_missing_rpc() -> None:
    gateway = FakePostgresGateway()

    result = await start_report(
        InspectionStart(
            assignment_id=UUID(gateway.assignment["id"]),
            gps_lat=-34.0,
            gps_lng=18.5,
        ),
        gateway,
        inspector_user(gateway),
        None,
    )

    assert result["report"][0]["assignment_id"] == gateway.assignment["id"]
    assert gateway.rpc_calls == []
    assert gateway.start_report_calls == [
        {
            "assignment_id": UUID(gateway.assignment["id"]),
            "inspector_id": UUID(gateway.inspector["id"]),
            "gps_lat": -34.0,
            "gps_lng": 18.5,
            "checklist_template": CHECKLIST_TEMPLATE,
            "token": "inspector-token",
        }
    ]


@pytest.mark.asyncio
async def test_start_report_requires_preview_inspector_for_admin_without_inspector_profile() -> (
    None
):
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


@pytest.mark.asyncio
async def test_submit_for_approval_persists_assessment_notes_and_gps() -> None:
    gateway = FakeGateway()
    gateway.report = {
        "id": "b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579",
        "assignment_id": gateway.assignment["id"],
        "inspector_id": gateway.inspector["id"],
        "assessment_status": "draft",
    }
    required_checks = [
        ("Garden condition", "full_garden_view"),
        ("Crop health", "crop_close_up"),
        ("Irrigation status", "irrigation"),
        ("Pest and disease", "problem_area"),
    ]
    gateway.checklist_items = [
        {
            "id": f"00000000-0000-0000-0000-00000000000{index}",
            "category": category,
            "item_name": category,
            "requires_photo": True,
            "result": "na" if category == "Crop health" else "pass",
            "comment": "No crops planted yet" if category == "Crop health" else None,
        }
        for index, (category, _) in enumerate(required_checks, start=1)
    ]
    gateway.photos = [
        {"checklist_item_id": None, "photo_type": photo_type} for _, photo_type in required_checks
    ]
    result = await submit_for_approval(
        UUID(gateway.report["id"]),
        InspectionAssessment(
            notes="The gate is narrow; use compact raised beds.",
            gps_lat=-34.0,
            gps_lng=18.5,
            sunlight_hours=7,
            water_access="reliable",
            usable_space_m2=12,
            installation_types=["raised_bed"],
            recommended_crops=["Spinach"],
            recommended_infrastructure=["Raised bed"],
        ),
        gateway,
        inspector_user(gateway),
        None,
    )

    report_update = next(
        call[1] for call in gateway.update_calls if call[0] == "inspection_reports"
    )
    assert report_update["notes"] == "The gate is narrow; use compact raised beds."
    assert report_update["gps_lat"] == -34.0
    assert report_update["gps_lng"] == 18.5
    assert report_update["assessment_status"] == "submitted_for_approval"
    assert result["report"]["suitability_band"] == "suitable"
    assert gateway.assignment["status"] == "completed"


@pytest.mark.asyncio
async def test_submit_for_approval_requires_checklist_evidence_photos() -> None:
    gateway = FakeGateway()
    gateway.report = {
        "id": "b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579",
        "assignment_id": gateway.assignment["id"],
        "inspector_id": gateway.inspector["id"],
        "assessment_status": "draft",
    }
    gateway.checklist_items = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "category": "Garden condition",
            "item_name": "Full garden view",
            "requires_photo": True,
            "result": "pass",
            "comment": None,
        }
    ]

    with pytest.raises(AppError) as raised:
        await submit_for_approval(
            UUID(gateway.report["id"]),
            InspectionAssessment(
                sunlight_hours=7,
                water_access="reliable",
                usable_space_m2=12,
                installation_types=["raised_bed"],
                recommended_crops=["Spinach"],
                recommended_infrastructure=["Raised bed"],
            ),
            gateway,
            inspector_user(gateway),
            None,
        )

    assert raised.value.status_code == 422
    assert raised.value.code == "inspection_evidence_incomplete"
    assert not gateway.update_calls
