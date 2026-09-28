from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.workload_identity import WorkloadIdentityError, _verify
from app.infrastructure.postgres_gateway import PostgresGateway
from app.routers.communications import (
    help_center_garden_request_snapshot,
    project_garden_request_for_help_center,
)
from app.schemas.communications import HelpCenterGardenRequestCase


def test_help_center_projection_contains_only_allowlisted_lifecycle_data() -> None:
    row = {
        "id": "7c7f97d8-b7ee-4f9b-852e-8148ee2cb7ac",
        "owner_id": "50c25988-c05f-4071-a9b6-2661b6814c19",
        "status": "inspection_scheduled",
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 2, tzinfo=UTC),
        "email": "private@example.com",
        "address": "Private address",
        "details": {"message": "Private free text"},
        "admin_notes": "Internal note",
    }

    projection = project_garden_request_for_help_center(row, "x" * 32)
    payload = projection.model_dump()

    assert set(payload) == set(HelpCenterGardenRequestCase.model_fields)
    assert payload["status"] == "inspection_scheduled"
    assert payload["category"] == "garden_request"
    assert "private@example.com" not in repr(payload)
    assert "Private address" not in repr(payload)
    assert "Private free text" not in repr(payload)
    assert payload["tenant_scope_ref"] != payload["requester_ref"]
    assert payload["case_ref"].startswith("ufc-")


def test_help_center_projection_rejects_unknown_status() -> None:
    row = {
        "id": "7c7f97d8-b7ee-4f9b-852e-8148ee2cb7ac",
        "owner_id": "50c25988-c05f-4071-a9b6-2661b6814c19",
        "status": "arbitrary_text",
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 2, tzinfo=UTC),
    }
    with pytest.raises(ValueError, match="outside the support projection contract"):
        project_garden_request_for_help_center(row, "x" * 32)


@pytest.mark.asyncio
async def test_source_query_filters_tenant_scope_before_fetching_rows() -> None:
    scope_a = "uf-tenant-" + "a" * 64
    scope_b = "uf-tenant-" + "b" * 64
    owner_a = "50c25988-c05f-4071-a9b6-2661b6814c19"
    owner_b = "60c25988-c05f-4071-a9b6-2661b6814c19"
    requests = [
        {"id": "request-a", "owner_id": owner_a},
        {"id": "request-b", "owner_id": owner_b},
    ]
    source_mappings = [
        {"tenant_scope_ref": scope_a, "owner_id": owner_a},
        {"tenant_scope_ref": scope_b, "owner_id": owner_b},
    ]

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement, parameters):
            sql = str(statement)
            assert "INNER JOIN public.help_center_tenant_scopes" in sql
            assert "scope.owner_id = request.owner_id" in sql
            assert "scope.tenant_scope_ref = ANY" in sql
            requested = set(parameters["tenant_scope_refs"])
            allowed_owners = {
                mapping["owner_id"]
                for mapping in source_mappings
                if mapping["tenant_scope_ref"] in requested
            }
            fetched = [row for row in requests if row["owner_id"] in allowed_owners]
            return Result(fetched)

    class Engine:
        def connect(self):
            return Connection()

    gateway = object.__new__(PostgresGateway)
    gateway.engine = Engine()

    fetched = await gateway.select_garden_requests_for_help_center([scope_a], limit=501)

    assert [row["id"] for row in fetched] == ["request-a"]
    assert all(row["owner_id"] != owner_b for row in fetched)


def test_service_token_verification_requires_the_exact_allowlisted_service(monkeypatch) -> None:
    observed = {}

    def verify(token, request, *, audience, clock_skew_in_seconds):
        observed["audience"] = audience
        observed["clock_skew_in_seconds"] = clock_skew_in_seconds
        return {
            "iss": "https://accounts.google.com",
            "email": "help-center-runtime@stratus-website-496818.iam.gserviceaccount.com",
            "email_verified": True,
            "sub": "service-subject",
        }

    monkeypatch.setattr(
        "app.core.workload_identity.id_token.verify_oauth2_token",
        verify,
    )
    _verify(
        "signed-token",
        "https://urban-farming-backend-prod.example",
        "help-center-runtime@stratus-website-496818.iam.gserviceaccount.com",
    )
    assert observed == {
        "audience": "https://urban-farming-backend-prod.example",
        "clock_skew_in_seconds": 30,
    }


def test_service_token_verification_rejects_wrong_service_account(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.workload_identity.id_token.verify_oauth2_token",
        lambda *args, **kwargs: {
            "iss": "https://accounts.google.com",
            "email": "other-runtime@stratus-website-496818.iam.gserviceaccount.com",
            "email_verified": True,
            "sub": "service-subject",
        },
    )
    with pytest.raises(WorkloadIdentityError, match="not allowed"):
        _verify(
            "signed-token",
            "https://urban-farming-backend-prod.example",
            "help-center-runtime@stratus-website-496818.iam.gserviceaccount.com",
        )


@pytest.mark.asyncio
async def test_projection_is_disabled_without_reading_the_source() -> None:
    settings = Settings(help_center_projection_enabled=False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    with pytest.raises(HTTPException) as error:
        await help_center_garden_request_snapshot(
            request,
            gateway=object(),
            authorization=None,
            limit=500,
            tenant_scope_refs=["uf-tenant-" + "a" * 64],
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_projection_rejects_non_allowlisted_service_before_source_read(monkeypatch) -> None:
    settings = Settings(
        help_center_projection_enabled=True,
        data_backend="postgres",
        auth_mode="native",
        support_reference_secret="x" * 32,
        help_center_projection_audience="https://urban-farming-backend-prod.example",
        help_center_service_account_email="help-center-runtime@stratus-website-496818.iam.gserviceaccount.com",
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    async def reject_identity(*args, **kwargs):
        raise WorkloadIdentityError("not allowed")

    monkeypatch.setattr("app.routers.communications.verify_workload_identity", reject_identity)
    with pytest.raises(HTTPException) as error:
        await help_center_garden_request_snapshot(
            request,
            gateway=object(),
            authorization="Bearer signed-token",
            limit=500,
            tenant_scope_refs=["uf-tenant-" + "a" * 64],
        )
    assert error.value.status_code == 401
