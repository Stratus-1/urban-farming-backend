from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthResponse)
async def liveness(settings: Settings = get_settings()) -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        data_backend=settings.data_backend,
        timestamp=datetime.now(UTC),
    )


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(request: Request, settings: Settings = get_settings()) -> HealthResponse:
    try:
        ready = await request.app.state.gateway.ping()
    except Exception as error:
        raise AppError(
            503, "data_unavailable", "The configured data backend is unavailable"
        ) from error
    return HealthResponse(
        status="ok" if ready else "degraded",
        environment=settings.environment,
        data_backend=settings.data_backend,
        timestamp=datetime.now(UTC),
    )
