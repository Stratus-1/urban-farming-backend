import json
import re
from datetime import UTC, date, datetime, time
from uuid import UUID

import pytest

from app.core.errors import AppError
from app.infrastructure.postgres_gateway import (
    bind_value,
    build_filters,
    coerce_column_value,
    quote_identifier,
)


def test_build_filters_parameterizes_values() -> None:
    where_sql, parameters = build_filters(
        {
            "owner_id": "8cda0b73-f149-45f9-a75b-f74be25fb174",
            "status": ["pending", "in_progress"],
            "deleted_at": None,
        }
    )

    assert '"owner_id" = :filter_0' in where_sql
    assert '"status" IN (:filter_1_0, :filter_1_1)' in where_sql
    assert '"deleted_at" IS NULL' in where_sql
    assert parameters["filter_1_0"] == "pending"


def test_quote_identifier_rejects_injection() -> None:
    try:
        quote_identifier('properties; DROP TABLE "properties"')
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe SQL identifiers must be rejected")


def test_build_filters_coerces_iso_timestamps_for_asyncpg() -> None:
    where_sql, parameters = build_filters(
        {
            "scheduled_at": "gte.2026-07-12T21:15:25.899Z",
            "created_at": "2026-07-12T23:15:25+02:00",
        }
    )

    assert '"scheduled_at" >= :filter_0' in where_sql
    assert parameters["filter_0"] == datetime(2026, 7, 12, 21, 15, 25, 899000, tzinfo=UTC)
    assert parameters["filter_1"] == datetime.fromisoformat("2026-07-12T23:15:25+02:00")


def test_bind_value_serializes_json_objects_for_asyncpg() -> None:
    placeholder, value = bind_value(
        "details",
        {"trackingState": "requested", "plants": ["Lettuce", "Basil"]},
    )

    assert placeholder == "CAST(:details AS JSONB)"
    assert value == '{"trackingState": "requested", "plants": ["Lettuce", "Basil"]}'


def test_bind_value_serializes_jsonb_arrays_without_converting_postgres_arrays() -> None:
    risks = [{"category": "pests", "severity": "medium", "notes": "Observed"}]

    placeholder, value = bind_value("risks", risks, "jsonb")
    array_placeholder, array_value = bind_value("installation_types", ["vertical"], "ARRAY")

    assert placeholder == "CAST(:risks AS JSONB)"
    assert value == '[{"category": "pests", "severity": "medium", "notes": "Observed"}]'
    assert array_placeholder == ":installation_types"
    assert array_value == ["vertical"]


def test_coerce_column_value_converts_json_temporal_strings_for_asyncpg() -> None:
    assert coerce_column_value("2026-07-14", "date") == date(2026, 7, 14)
    assert coerce_column_value("2026-07-14T07:00:00.000Z", "timestamp with time zone") == datetime(
        2026, 7, 14, 7, tzinfo=UTC
    )
    assert coerce_column_value("07:30:00", "time without time zone") == time(7, 30)


def test_coerce_column_value_preserves_text_even_when_it_looks_like_a_date() -> None:
    assert coerce_column_value("2026-07-14", "text") == "2026-07-14"


def test_coerce_column_value_rejects_invalid_temporal_values() -> None:
    with pytest.raises(AppError) as raised:
        coerce_column_value("not-a-date", "date")

    assert raised.value.status_code == 422
    assert raised.value.code == "invalid_temporal_value"


class _MappingsResult:
    def __init__(self, row=None) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        return self.row

    def all(self):
        if isinstance(self.row, list):
            return self.row
        return [self.row] if self.row is not None else []


class _InspectionConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.report = None
        self.checklist_exists = False

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "FROM public.inspection_assignments" in sql:
            return _MappingsResult(
                {
                    "id": UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
                    "inspector_id": UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
                    "garden_id": UUID("06ac42e0-c673-4412-9660-272de2f9b9cb"),
                    "status": "pending",
                    "started_at": None,
                }
            )
        if "FROM public.inspection_reports" in sql:
            return _MappingsResult(self.report)
        if "INSERT INTO public.inspection_reports" in sql:
            self.report = {
                "id": UUID("b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579"),
                "assignment_id": UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
                "inspector_id": UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
                "garden_id": UUID("06ac42e0-c673-4412-9660-272de2f9b9cb"),
                "overall_status": "pending",
            }
            return _MappingsResult(self.report)
        return _MappingsResult()

    async def scalar(self, _statement, _parameters=None):
        return self.checklist_exists


class _InspectionTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, _type, _value, _traceback):
        return False


class _InspectionEngine:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return _InspectionTransaction(self.connection)


class _SchedulingConnection:
    def __init__(self) -> None:
        self.request_id = UUID("e1b1d0c2-96cd-4cc2-a9b6-4f34e7614dd1")
        self.owner_id = UUID("6102934a-e389-4ad9-ac92-2b70d2f99157")
        self.property_id = UUID("11b1c03a-4f2c-4210-a025-0ae4d905a7aa")
        self.assignment_id = UUID("6aa1470a-973c-45a8-9d37-95cb97c6f68c")
        self.inspector_id = UUID("952addb5-b2dd-4aa6-a18e-9ba8e5131bdf")
        self.request = {
            "id": self.request_id,
            "owner_id": self.owner_id,
            "property_id": None,
            "status": "submitted",
            "label": "Courtyard garden",
            "address": "1 Test Road",
            "city": "Cape Town",
            "lat": None,
            "lng": None,
            "available_space_m2": 12,
            "sunlight_hours": 6,
            "details": {"notes": "Grower notes"},
            "admin_notes": None,
        }
        self.assignment = None
        self.workflow_stage_ids = {
            key: UUID(int=index)
            for index, key in enumerate(
                ("property_details", "preliminary_assessment", "inspector_visit"),
                start=1,
            )
        }
        self.statements: list[tuple[str, object]] = []

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        parameters = parameters or {}
        self.statements.append((sql, parameters))
        if "SELECT * FROM public.garden_requests" in sql:
            return _MappingsResult(dict(self.request))
        if "FROM public.inspectors" in sql:
            return _MappingsResult({"id": self.inspector_id})
        if "INSERT INTO public.properties" in sql:
            self.request["property_id"] = self.property_id
            return _MappingsResult({"id": self.property_id})
        if "SELECT owner_id FROM public.properties" in sql:
            return _MappingsResult({"owner_id": self.owner_id})
        if "FROM public.inspection_assignments" in sql:
            return _MappingsResult(dict(self.assignment) if self.assignment else None)
        if "INSERT INTO public.inspection_assignments" in sql:
            self.assignment = {
                **parameters,
                "id": self.assignment_id,
                "status": "pending",
            }
            return _MappingsResult(dict(self.assignment))
        if "UPDATE public.inspection_assignments" in sql:
            self.assignment.update(parameters)
            return _MappingsResult(dict(self.assignment))
        if "FROM public.workflow_stages AS stage" in sql:
            stage_id = self.workflow_stage_ids[parameters["stage_key"]]
            return _MappingsResult(
                {"id": stage_id, "evidence": {}, "started_at": None, "completed_at": None}
            )
        if "UPDATE public.workflow_stages" in sql:
            return _MappingsResult({"id": parameters["stage_id"]})
        if "UPDATE public.garden_requests" in sql:
            for key in (
                "property_id",
                "admin_notes",
                "details",
                "status",
                "reviewed_by",
                "reviewed_at",
            ):
                match = re.search(rf'"{key}" = (?:CAST\()?:(request_value_\d+)', sql)
                if match:
                    value = parameters[match.group(1)]
                    self.request[key] = json.loads(value) if key == "details" else value
            return _MappingsResult(dict(self.request))
        return _MappingsResult()


class _SchedulingEngine(_InspectionEngine):
    pass


@pytest.mark.asyncio
async def test_inspection_schedule_retries_reuse_linked_property_and_assignment() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    connection = _SchedulingConnection()
    gateway = object.__new__(PostgresGateway)
    gateway.engine = _SchedulingEngine(connection)
    gateway._column_types = {
        "garden_requests": {
            "details": "jsonb",
            "property_id": "uuid",
            "status": "USER-DEFINED",
            "reviewed_by": "uuid",
            "reviewed_at": "timestamp with time zone",
        }
    }
    schedule = {
        "inspector_id": connection.inspector_id,
        "due_date": date(2026, 9, 30),
        "scheduled_for": datetime(2026, 9, 30, 7, tzinfo=UTC),
        "priority": "high",
        "focus_areas": ["Water access"],
        "focus_brief": "Check irrigation",
        "access_instructions": None,
        "admin_notes": "FOCUS AREAS: Water access",
    }

    first = await gateway.schedule_garden_request_inspection(
        connection.request_id, schedule, connection.owner_id, token=None
    )
    second = await gateway.schedule_garden_request_inspection(
        connection.request_id, schedule, connection.owner_id, token=None
    )

    assert first["request"]["property_id"] == connection.property_id
    assert first["request"]["status"] == "inspection_scheduled"
    assert second["assignment"]["id"] == connection.assignment_id
    assert sum("INSERT INTO public.properties" in sql for sql, _ in connection.statements) == 1
    assert (
        sum("INSERT INTO public.inspection_assignments" in sql for sql, _ in connection.statements)
        == 1
    )
    assert second["request"]["details"]["inspectionAssignment"]["assignmentId"] == str(
        connection.assignment_id
    )
    workflow_updates = [
        parameters
        for statement, parameters in connection.statements
        if "UPDATE public.workflow_stages" in statement
    ]
    assert len(workflow_updates) == 6
    inspector_stage_evidence = json.loads(workflow_updates[2]["evidence"])
    assert inspector_stage_evidence["assignment_id"] == str(connection.assignment_id)
    property_stage_evidence = json.loads(workflow_updates[0]["evidence"])
    assert property_stage_evidence["property_id"] == str(connection.property_id)


@pytest.mark.asyncio
async def test_postgres_start_inspection_report_locks_assignment_and_seeds_checklist() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _InspectionConnection()
    gateway.engine = _InspectionEngine(connection)

    report = await gateway.start_inspection_report(
        assignment_id=UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
        inspector_id=UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
        gps_lat=-34.0,
        gps_lng=18.5,
        checklist_template=(
            ("Garden condition", "Full garden view", True, 1),
            ("Crop health", "Leaf and growth check", True, 2),
        ),
        token="inspector-token",
    )

    assignment_lock = next(sql for sql, _params in connection.statements if "FOR UPDATE" in sql)
    checklist_seed = next(
        params
        for sql, params in connection.statements
        if "INSERT INTO public.inspection_checklist_items" in sql
    )
    assert report["overall_status"] == "pending"
    assert "inspector_id = :inspector_id" in assignment_lock
    assert len(checklist_seed) == 2
    assert checklist_seed[0]["category"] == "Garden condition"
    assert checklist_seed[0]["requires_photo"] is True


class _SubmissionConnection:
    def __init__(self, *, missing_photo: bool = False) -> None:
        self.statements: list[tuple[str, object]] = []
        self.missing_photo = missing_photo
        self.report = {
            "id": UUID("b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579"),
            "assignment_id": UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
            "inspector_id": UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
            "assessment_status": "draft",
        }
        self.assignment = {"id": self.report["assignment_id"], "status": "in_progress"}

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        parameters = parameters or {}
        self.statements.append((sql, parameters))
        if "FROM public.inspection_reports" in sql:
            return _MappingsResult(dict(self.report))
        if "FROM public.inspection_assignments" in sql:
            return _MappingsResult(dict(self.assignment))
        if "FROM public.inspection_checklist_items" in sql:
            return _MappingsResult(
                [
                    {
                        "id": UUID("00000000-0000-0000-0000-000000000001"),
                        "requires_photo": True,
                        "result": "pass",
                    }
                ]
            )
        if "UPDATE public.inspection_reports" in sql:
            self.report.update(parameters)
            self.report["assessment_status"] = "submitted_for_approval"
            return _MappingsResult(dict(self.report))
        if "UPDATE public.inspection_assignments" in sql:
            self.assignment.update(parameters)
            self.assignment["status"] = "completed"
        return _MappingsResult()

    async def scalar(self, _statement, _parameters=None):
        return self.missing_photo


@pytest.mark.asyncio
async def test_inspection_submission_saves_report_and_assignment_in_one_transaction() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    connection = _SubmissionConnection()
    gateway = PostgresGateway.__new__(PostgresGateway)
    gateway.engine = _InspectionEngine(connection)
    assessment = {
        "notes": "Clear irrigation access",
        "gps_lat": -34.0,
        "gps_lng": 18.5,
        "sunlight_hours": 7.0,
        "water_access": "reliable",
        "usable_space_m2": 12.0,
        "installation_types": ["raised_bed"],
        "measurements": {},
        "risks": [],
        "suitability_score": 85,
        "score_breakdown": {"sunlight": 20},
        "suitability_band": "suitable",
        "recommended_crops": ["Spinach"],
        "recommended_infrastructure": ["Raised bed"],
        "overall_status": "pass",
        "follow_up_required": False,
        "submitted_at": "2026-09-29T10:00:00+00:00",
    }

    result = await gateway.submit_inspection_for_approval(
        report_id=connection.report["id"],
        assignment_id=connection.report["assignment_id"],
        inspector_id=connection.report["inspector_id"],
        assessment=assessment,
        token=None,
    )

    report_update = next(
        sql for sql, _ in connection.statements if "UPDATE public.inspection_reports" in sql
    )
    assignment_update = next(
        sql for sql, _ in connection.statements if "UPDATE public.inspection_assignments" in sql
    )
    assert "FOR UPDATE" in next(
        sql for sql, _ in connection.statements if "FROM public.inspection_reports" in sql
    )
    assert connection.statements.index(
        (report_update, next(p for s, p in connection.statements if s == report_update))
    ) < connection.statements.index(
        (assignment_update, next(p for s, p in connection.statements if s == assignment_update))
    )
    assert result["assessment_status"] == "submitted_for_approval"
    assert connection.assignment["status"] == "completed"
    assert gateway.engine.begin_calls == 1


@pytest.mark.asyncio
async def test_inspection_submission_rejects_missing_photo_before_writing() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    connection = _SubmissionConnection(missing_photo=True)
    gateway = PostgresGateway.__new__(PostgresGateway)
    gateway.engine = _InspectionEngine(connection)
    assessment = {
        "notes": None,
        "gps_lat": None,
        "gps_lng": None,
        "sunlight_hours": 7.0,
        "water_access": "reliable",
        "usable_space_m2": 12.0,
        "installation_types": ["raised_bed"],
        "measurements": {},
        "risks": [],
        "suitability_score": 85,
        "score_breakdown": {},
        "suitability_band": "suitable",
        "recommended_crops": ["Spinach"],
        "recommended_infrastructure": ["Raised bed"],
        "overall_status": "pass",
        "follow_up_required": False,
        "submitted_at": "2026-09-29T10:00:00+00:00",
    }

    with pytest.raises(AppError) as raised:
        await gateway.submit_inspection_for_approval(
            report_id=connection.report["id"],
            assignment_id=connection.report["assignment_id"],
            inspector_id=connection.report["inspector_id"],
            assessment=assessment,
            token=None,
        )

    assert raised.value.code == "inspection_evidence_incomplete"
    assert gateway.engine.begin_calls == 1
    assert not any("UPDATE public." in sql for sql, _ in connection.statements)


class _GardenPlantingConnection:
    def __init__(self, status: str = "seeds", workflow_stage: bool = True) -> None:
        self.status = status
        self.workflow_stage = workflow_stage
        self.statements: list[tuple[str, object]] = []
        self.rollback_requested = False

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "FROM public.garden_requests" in sql and "FOR UPDATE" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "property_id": UUID("22222222-2222-4222-8222-222222222222"),
                    "status": self.status,
                }
            )
        if "FROM public.installations" in sql:
            return _MappingsResult(
                {
                    "id": UUID("33333333-3333-4333-8333-333333333333"),
                    "installed_at": date(2026, 9, 20),
                }
            )
        if "FROM public.crop_batches" in sql:
            return _MappingsResult(
                [
                    {"id": UUID("44444444-4444-4444-8444-444444444444"), "status": "planned"},
                    {"id": UUID("55555555-5555-4555-8555-555555555555"), "status": "planned"},
                ]
            )
        if "FROM public.workflow_stages" in sql:
            if not self.workflow_stage:
                return _MappingsResult()
            return _MappingsResult(
                {
                    "id": UUID("66666666-6666-4666-8666-666666666666"),
                    "evidence": {"prior": "kept"},
                    "started_at": None,
                }
            )
        if "UPDATE public.crop_batches" in sql:
            assert "status IN ('planned', 'growing')" in sql
            return _MappingsResult(
                [
                    {"id": UUID("44444444-4444-4444-8444-444444444444")},
                    {"id": UUID("55555555-5555-4555-8555-555555555555")},
                ]
            )
        if "UPDATE public.garden_requests" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "status": "final_install",
                }
            )
        if "UPDATE public.workflow_stages" in sql:
            return _MappingsResult({"id": UUID("66666666-6666-4666-8666-666666666666")})
        return _MappingsResult()


class _GardenPlantingEngine(_InspectionEngine):
    def begin(self):
        return _GardenPlantingTransaction(self.connection)


class _GardenInstallationConnection:
    def __init__(self, workflow_stages: bool = True, approved_report: bool = True) -> None:
        self.workflow_stages = workflow_stages
        self.approved_report = approved_report
        self.statements: list[tuple[str, object]] = []
        self.rollback_requested = False

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "FROM public.garden_requests" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "owner_id": UUID("77777777-7777-4777-8777-777777777777"),
                    "property_id": UUID("22222222-2222-4222-8222-222222222222"),
                    "status": "needing_implements",
                }
            )
        if "FROM public.inspection_reports" in sql:
            return (
                _MappingsResult({"id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")})
                if self.approved_report
                else _MappingsResult()
            )
        if "FROM public.workflow_stages" in sql:
            if not self.workflow_stages:
                return _MappingsResult([])
            return _MappingsResult(
                [
                    {
                        "id": UUID("66666666-6666-4666-8666-666666666666"),
                        "stage_key": "installation",
                        "evidence": {},
                        "started_at": None,
                    },
                    {
                        "id": UUID("99999999-9999-4999-8999-999999999999"),
                        "stage_key": "crop_allocation",
                        "evidence": {},
                        "started_at": None,
                    },
                ]
            )
        if "FROM public.installations" in sql:
            return _MappingsResult()
        if "INSERT INTO public.installations" in sql:
            return _MappingsResult({"id": UUID("33333333-3333-4333-8333-333333333333")})
        if "UPDATE public.garden_requests" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "status": "implements_installed",
                }
            )
        if "UPDATE public.workflow_stages" in sql:
            return _MappingsResult({"id": parameters["stage_id"]})
        return _MappingsResult()


class _GardenInstallationEngine(_InspectionEngine):
    def begin(self):
        return _GardenInstallationTransaction(self.connection)


class _GardenInstallationTransaction(_InspectionTransaction):
    async def __aexit__(self, exc_type, _value, _traceback):
        self.connection.rollback_requested = exc_type is not None
        return False


@pytest.mark.asyncio
async def test_postgres_installation_commits_request_installation_and_workflow_together() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenInstallationConnection()
    gateway.engine = _GardenInstallationEngine(connection)

    request, installation = await gateway.complete_garden_installation(
        UUID("11111111-1111-4111-8111-111111111111"),
        UUID("22222222-2222-4222-8222-222222222222"),
        {
            "install_type": "raised_bed",
            "size_m2": 8,
            "capacity_units": 2,
            "installed_at": "2026-09-20",
            "photos": ["https://example.test/install.jpg"],
            "maintenance_notes": None,
        },
        UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        token="admin-token",
    )

    sql = [statement for statement, _ in connection.statements]
    workflow_updates = [
        parameters["status"]
        for statement, parameters in connection.statements
        if "UPDATE public.workflow_stages" in statement
    ]
    assert request["status"] == "implements_installed"
    assert installation["id"] == UUID("33333333-3333-4333-8333-333333333333")
    assert workflow_updates == ["completed", "ready"]
    assert sql.index(next(s for s in sql if "UPDATE public.garden_requests" in s)) < sql.index(
        next(s for s in sql if "UPDATE public.workflow_stages" in s)
    )
    assert connection.rollback_requested is False


@pytest.mark.asyncio
async def test_postgres_installation_rolls_back_when_workflow_stage_is_missing() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenInstallationConnection(workflow_stages=False)
    gateway.engine = _GardenInstallationEngine(connection)

    with pytest.raises(AppError) as raised:
        await gateway.complete_garden_installation(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
            {"installed_at": "2026-09-20", "photos": []},
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            token="admin-token",
        )

    assert raised.value.code == "workflow_stage_missing"
    assert connection.rollback_requested is True
    assert not any("INSERT INTO public.installations" in sql for sql, _ in connection.statements)


@pytest.mark.asyncio
async def test_postgres_installation_rechecks_approved_report_before_writes() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenInstallationConnection(approved_report=False)
    gateway.engine = _GardenInstallationEngine(connection)

    with pytest.raises(AppError) as raised:
        await gateway.complete_garden_installation(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
            {"installed_at": "2026-09-20", "photos": []},
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            token="admin-token",
        )

    assert raised.value.code == "inspection_approval_required"
    assert connection.rollback_requested is True
    assert not any("INSERT INTO public.installations" in sql for sql, _ in connection.statements)


class _GardenPlantingTransaction(_InspectionTransaction):
    async def __aexit__(self, exc_type, _value, _traceback):
        self.connection.rollback_requested = exc_type is not None
        return False


class _GardenAllocationConnection(_GardenPlantingConnection):
    def __init__(self, status: str = "implements_installed", workflow_stages: bool = True) -> None:
        super().__init__(status=status, workflow_stage=workflow_stages)
        self.crop_id = UUID("88888888-8888-4888-8888-888888888888")
        self.existing_crop_id = UUID("99999999-9999-4999-8999-999999999999")

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "FROM public.garden_requests" in sql and "FOR UPDATE" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "owner_id": UUID("77777777-7777-4777-8777-777777777777"),
                    "property_id": UUID("22222222-2222-4222-8222-222222222222"),
                    "status": self.status,
                    "details": {"request": "preserved"},
                }
            )
        if "FROM public.inspection_reports" in sql:
            return _MappingsResult(
                {
                    "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                    "recommended_crops": ["Lettuce", "Spinach"],
                }
            )
        if "UPDATE public.properties" in sql:
            return _MappingsResult({"id": UUID("22222222-2222-4222-8222-222222222222")})
        if "FROM public.installations" in sql:
            return _MappingsResult({"id": UUID("33333333-3333-4333-8333-333333333333")})
        if "FROM public.crop_batches" in sql:
            return _MappingsResult(
                [
                    {
                        "id": self.existing_crop_id,
                        "crop_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
                    }
                ]
            )
        if "INSERT INTO public.crop_batches" in sql:
            return _MappingsResult({"id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")})
        if "UPDATE public.garden_requests" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "status": "seeds",
                }
            )
        if "FROM public.workflow_stages" in sql:
            if not self.workflow_stage:
                return _MappingsResult([])
            return _MappingsResult(
                [
                    {
                        "id": UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
                        "stage_key": "crop_allocation",
                        "evidence": {},
                        "started_at": None,
                    },
                    {
                        "id": UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
                        "stage_key": "maintenance_tasks",
                        "evidence": {"existing": True},
                        "started_at": None,
                    },
                ]
            )
        if "UPDATE public.workflow_stages" in sql:
            return _MappingsResult({"id": parameters["stage_id"]})
        return _MappingsResult()


class _GardenAllocationEngine(_GardenPlantingEngine):
    pass


class _RequestWorkflowConnection:
    def __init__(self, status: str = "inspection_scheduled") -> None:
        self.status = status
        self.statements: list[tuple[str, dict | None]] = []

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "SELECT id, property_id, status FROM public.garden_requests" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "property_id": UUID("22222222-2222-4222-8222-222222222222"),
                    "status": self.status,
                }
            )
        if "UPDATE public.inspection_reports" in sql:
            return _MappingsResult({"id": parameters["report_id"]})
        if "UPDATE public.garden_requests SET" in sql:
            return _MappingsResult(
                {
                    "id": UUID("11111111-1111-4111-8111-111111111111"),
                    "status": "accepted",
                }
            )
        if "SELECT stage.id, stage.evidence" in sql:
            stage_id = (
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                if parameters["stage_key"] == "approval"
                else "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            )
            return _MappingsResult(
                {
                    "id": UUID(stage_id),
                    "evidence": {"prior": parameters["stage_key"]},
                    "started_at": None,
                    "completed_at": None,
                }
            )
        if "UPDATE public.workflow_stages" in sql:
            return _MappingsResult({"id": parameters["stage_id"]})
        return _MappingsResult()


class _RequestWorkflowEngine(_InspectionEngine):
    def __init__(self, connection) -> None:
        super().__init__(connection)
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return _InspectionTransaction(self.connection)


@pytest.mark.asyncio
async def test_request_status_report_and_workflow_stages_advance_in_one_transaction() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _RequestWorkflowConnection()
    engine = _RequestWorkflowEngine(connection)
    gateway.engine = engine
    gateway._column_types = {
        "garden_requests": {
            "status": "USER-DEFINED",
            "reviewed_by": "uuid",
            "reviewed_at": "timestamp with time zone",
            "admin_notes": "text",
        }
    }

    request_id = UUID("11111111-1111-4111-8111-111111111111")
    report_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    actor_id = UUID("77777777-7777-4777-8777-777777777777")
    result = await gateway.update_garden_request_workflow(
        request_id,
        "inspection_scheduled",
        {
            "status": "accepted",
            "reviewed_by": str(actor_id),
            "reviewed_at": "2026-09-28T12:00:00+00:00",
            "admin_notes": "Site approved after review.",
        },
        actor_id,
        [
            {
                "stage_key": "approval",
                "status": "completed",
                "evidence": {
                    "decision": "approved",
                    "report_id": str(report_id),
                    "property_id": request_id,
                },
            },
            {
                "stage_key": "installation",
                "status": "ready",
                "evidence": {},
                "next_action": "Prepare the installation.",
            },
        ],
        report_update={
            "report_id": report_id,
            "status": "approved",
            "notes": "Site approved after review.",
        },
        token="admin-token",
    )

    sql = [statement for statement, _parameters in connection.statements]
    assert engine.begin_calls == 1
    assert result["status"] == "accepted"
    report_update_index = next(
        index for index, item in enumerate(sql) if "UPDATE public.inspection_reports" in item
    )
    request_update_index = next(
        index for index, item in enumerate(sql) if "UPDATE public.garden_requests SET" in item
    )
    assert report_update_index < request_update_index
    stage_parameters = [
        parameters
        for statement, parameters in connection.statements
        if "UPDATE public.workflow_stages" in statement
    ]
    assert len(stage_parameters) == 2
    approval_evidence = next(
        json.loads(parameters["evidence"])
        for parameters in stage_parameters
        if json.loads(parameters["evidence"]).get("decision") == "approved"
    )
    assert approval_evidence["property_id"] == str(request_id)


@pytest.mark.asyncio
async def test_request_workflow_update_rejects_stale_status_before_writes() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _RequestWorkflowConnection(status="submitted")
    gateway.engine = _RequestWorkflowEngine(connection)
    gateway._column_types = {"garden_requests": {"status": "USER-DEFINED"}}

    with pytest.raises(AppError) as raised:
        await gateway.update_garden_request_workflow(
            UUID("11111111-1111-4111-8111-111111111111"),
            "inspection_scheduled",
            {"status": "accepted"},
            UUID("77777777-7777-4777-8777-777777777777"),
            [],
            token="admin-token",
        )

    assert raised.value.code == "request_changed"
    assert not any("UPDATE public." in statement for statement, _ in connection.statements)


@pytest.mark.asyncio
async def test_postgres_planting_locks_and_advances_batches_request_and_workflow() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenPlantingConnection()
    gateway.engine = _GardenPlantingEngine(connection)

    request = await gateway.complete_garden_planting(
        request_id=UUID("11111111-1111-4111-8111-111111111111"),
        planted_at=date(2026, 9, 28),
        actor_id=UUID("77777777-7777-4777-8777-777777777777"),
        token="admin-token",
    )

    request_lock = next(
        sql for sql, _params in connection.statements if "FROM public.garden_requests" in sql
    )
    batch_lock = next(
        sql for sql, _params in connection.statements if "FROM public.crop_batches" in sql
    )
    batch_update_index = next(
        i
        for i, (sql, _params) in enumerate(connection.statements)
        if "UPDATE public.crop_batches" in sql
    )
    request_update_index = next(
        i
        for i, (sql, _params) in enumerate(connection.statements)
        if "UPDATE public.garden_requests" in sql
    )
    stage_update_index = next(
        i
        for i, (sql, _params) in enumerate(connection.statements)
        if "UPDATE public.workflow_stages" in sql
    )

    assert "FOR UPDATE" in request_lock
    assert "FOR UPDATE" in batch_lock
    assert request["status"] == "final_install"
    assert batch_update_index < request_update_index < stage_update_index
    stage_update = connection.statements[stage_update_index][1]
    assert stage_update["evidence"] == (
        '{"prior": "kept", "planted_at": "2026-09-28", '
        '"crop_batch_ids": ["44444444-4444-4444-8444-444444444444", '
        '"55555555-5555-4555-8555-555555555555"]}'
    )


@pytest.mark.asyncio
async def test_postgres_planting_rejects_stale_request_before_any_write() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenPlantingConnection(status="cancelled")
    gateway.engine = _GardenPlantingEngine(connection)

    with pytest.raises(AppError) as raised:
        await gateway.complete_garden_planting(
            request_id=UUID("11111111-1111-4111-8111-111111111111"),
            planted_at=date(2026, 9, 28),
            actor_id=UUID("77777777-7777-4777-8777-777777777777"),
            token="admin-token",
        )

    assert raised.value.code == "allocation_required"
    assert not any(sql.lstrip().startswith("UPDATE") for sql, _params in connection.statements)


@pytest.mark.asyncio
async def test_postgres_planting_requires_workflow_stage_before_any_write() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenPlantingConnection(workflow_stage=False)
    gateway.engine = _GardenPlantingEngine(connection)

    with pytest.raises(AppError) as raised:
        await gateway.complete_garden_planting(
            request_id=UUID("11111111-1111-4111-8111-111111111111"),
            planted_at=date(2026, 9, 28),
            actor_id=UUID("77777777-7777-4777-8777-777777777777"),
            token="admin-token",
        )

    assert raised.value.code == "workflow_stage_missing"
    assert not any(sql.lstrip().startswith("UPDATE") for sql, _params in connection.statements)


@pytest.mark.asyncio
async def test_postgres_allocation_commits_property_batches_request_and_workflow_together() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenAllocationConnection()
    gateway.engine = _GardenAllocationEngine(connection)
    property_id = UUID("22222222-2222-4222-8222-222222222222")
    request_id = UUID("11111111-1111-4111-8111-111111111111")
    crop_rows = [
        {
            "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            "name": "Lettuce",
            "est_yield_kg_per_unit": 2.5,
        },
        {
            "id": connection.crop_id,
            "name": "Spinach",
            "est_yield_kg_per_unit": 1.2,
        },
    ]

    result = await gateway.complete_garden_allocation(
        request_id=request_id,
        expected_property_id=property_id,
        property_payload={
            "label": "Garden",
            "address": "Street",
            "city": "Cape Town",
            "lat": -34.0,
            "lng": 18.5,
            "available_space_m2": 8.0,
            "sunlight_hours": 6.0,
            "notes": "Install notes",
        },
        approved_report_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        crop_rows=crop_rows,
        detail_updates={
            "requestedPlants": ["Lettuce"],
            "allocatedPlants": ["Lettuce", "Spinach"],
            "inspectionNotes": "Good site",
            "allocationNotes": "Plant two crops",
            "trackingState": "planned",
        },
        admin_notes="Plant two crops",
        actor_id=UUID("77777777-7777-4777-8777-777777777777"),
        token="admin-token",
    )

    sql_statements = [sql for sql, _params in connection.statements]
    inserted_batches = [sql for sql in sql_statements if "INSERT INTO public.crop_batches" in sql]
    activity_inserts = [
        sql for sql in sql_statements if "INSERT INTO public.garden_activity_logs" in sql
    ]
    workflow_updates = [
        params["status"]
        for sql, params in connection.statements
        if "UPDATE public.workflow_stages" in sql
    ]

    assert "FOR UPDATE" in next(
        sql for sql in sql_statements if "FROM public.garden_requests" in sql
    )
    assert "FOR UPDATE" in next(sql for sql in sql_statements if "FROM public.installations" in sql)
    assert len(inserted_batches) == 1
    assert len(activity_inserts) == 2
    assert workflow_updates == ["completed", "ready"]
    assert result["status"] == "seeds"
    assert result["matchedPlants"] == ["Lettuce", "Spinach"]
    assert connection.rollback_requested is False


@pytest.mark.asyncio
async def test_postgres_allocation_rolls_back_if_workflow_stage_is_missing() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _GardenAllocationConnection(workflow_stages=False)
    gateway.engine = _GardenAllocationEngine(connection)

    with pytest.raises(AppError) as raised:
        await gateway.complete_garden_allocation(
            request_id=UUID("11111111-1111-4111-8111-111111111111"),
            expected_property_id=UUID("22222222-2222-4222-8222-222222222222"),
            property_payload={
                "label": "Garden",
                "address": None,
                "city": None,
                "lat": None,
                "lng": None,
                "available_space_m2": 8.0,
                "sunlight_hours": 6.0,
                "notes": None,
            },
            approved_report_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            crop_rows=[
                {
                    "id": connection.crop_id,
                    "name": "Spinach",
                    "est_yield_kg_per_unit": 1.2,
                }
            ],
            detail_updates={"allocatedPlants": ["Spinach"]},
            admin_notes=None,
            actor_id=UUID("77777777-7777-4777-8777-777777777777"),
            token="admin-token",
        )

    assert raised.value.code == "workflow_stage_missing"
    assert connection.rollback_requested is True
