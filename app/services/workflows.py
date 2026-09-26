from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.infrastructure.data_gateway import DataGateway
from app.schemas.common import CurrentUser


async def advance_workflow_stage(
    gateway: DataGateway,
    user: CurrentUser,
    request_id: UUID,
    stage_key: str,
    status: str,
    *,
    evidence: dict[str, Any],
    next_action: str | None = None,
) -> None:
    workflow = await gateway.select(
        "operational_workflows",
        token=user.access_token,
        filters={"garden_request_id": request_id},
        single=True,
    )
    if not workflow:
        raise AppError(
            409,
            "workflow_missing",
            "The request has no operational workflow. Apply the workflow database migration first.",
        )
    stage = await gateway.select(
        "workflow_stages",
        token=user.access_token,
        filters={"workflow_id": workflow["id"], "stage_key": stage_key},
        single=True,
    )
    if not stage:
        raise AppError(409, "workflow_stage_missing", f"Workflow stage {stage_key} is missing.")

    now = datetime.now(UTC).isoformat()
    prior_evidence = stage.get("evidence")
    merged_evidence = {**(prior_evidence if isinstance(prior_evidence, dict) else {}), **evidence}
    update: dict[str, Any] = {
        "status": status,
        "owner_user_id": str(user.id),
        "evidence": merged_evidence,
        "started_at": stage.get("started_at") or now,
    }
    if status in {"completed", "rejected"}:
        update["completed_at"] = now
    if status == "submitted":
        update["submitted_at"] = now
    if next_action is not None:
        update["next_action"] = next_action

    rows = await gateway.update(
        "workflow_stages",
        update,
        filters={"id": stage["id"]},
        token=user.access_token,
    )
    if not rows:
        raise AppError(409, "workflow_stage_update_failed", f"Could not advance {stage_key}.")


async def ready_workflow_stage(
    gateway: DataGateway,
    user: CurrentUser,
    request_id: UUID,
    stage_key: str,
    *,
    next_action: str,
) -> None:
    await advance_workflow_stage(
        gateway,
        user,
        request_id,
        stage_key,
        "ready",
        evidence={},
        next_action=next_action,
    )
