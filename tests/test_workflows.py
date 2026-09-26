from typing import Any
from uuid import UUID

import pytest

from app.core.errors import AppError
from app.schemas.common import CurrentUser
from app.services.workflows import advance_workflow_stage

USER_ID = UUID("8cda0b73-f149-45f9-a75b-f74be25fb174")
REQUEST_ID = UUID("9e89c870-fb64-4e29-b44d-903222a82e6f")


class WorkflowGateway:
    def __init__(self, workflow: dict[str, Any] | None = None) -> None:
        self.workflow = workflow or {"id": "workflow-1"}
        self.stage = {
            "id": "stage-1",
            "status": "ready",
            "evidence": {"prior": "kept"},
            "started_at": "2026-01-01T00:00:00Z",
        }
        self.updated: list[tuple[str, dict[str, Any]]] = []

    async def select(self, table: str, **kwargs: Any) -> Any:
        return self.workflow if table == "operational_workflows" else self.stage

    async def update(self, table: str, payload: dict[str, Any], **kwargs: Any) -> list[dict]:
        self.updated.append((table, payload))
        return [{"id": "stage-1", **payload}]


@pytest.mark.asyncio
async def test_advance_stage_preserves_existing_evidence_and_records_actor() -> None:
    gateway = WorkflowGateway()
    user = CurrentUser(id=USER_ID, roles={"admin"}, access_token="token")

    await advance_workflow_stage(
        gateway,
        user,
        REQUEST_ID,
        "approval",
        "completed",
        evidence={"decision": "approved", "report_id": "report-1"},
    )

    table, update = gateway.updated[0]
    assert table == "workflow_stages"
    assert update["status"] == "completed"
    assert update["owner_user_id"] == str(USER_ID)
    assert update["evidence"] == {
        "prior": "kept",
        "decision": "approved",
        "report_id": "report-1",
    }
    assert update["completed_at"]


@pytest.mark.asyncio
async def test_advance_stage_fails_closed_when_request_workflow_is_missing() -> None:
    gateway = WorkflowGateway(workflow=None)
    gateway.workflow = None
    user = CurrentUser(id=USER_ID, roles={"admin"}, access_token="token")

    with pytest.raises(AppError) as error:
        await advance_workflow_stage(
            gateway,
            user,
            REQUEST_ID,
            "approval",
            "completed",
            evidence={"decision": "approved"},
        )

    assert error.value.code == "workflow_missing"
    assert gateway.updated == []
