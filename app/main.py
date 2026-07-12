from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.infrastructure.auth_store import NativeAuthStore
from app.infrastructure.email import EmailGateway
from app.infrastructure.postgres_gateway import PostgresGateway
from app.infrastructure.storage import GCSStorageGateway, SupabaseStorageGateway
from app.infrastructure.supabase_gateway import SupabaseGateway
from app.routers import (
    accounts,
    admin,
    auth,
    commerce,
    communications,
    community,
    data,
    gardens,
    geocoding,
    health,
    inspections,
    plans,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_runtime()
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
        if settings.data_backend == "supabase":
            gateway = SupabaseGateway(
                url=str(settings.supabase_url),
                anon_key=settings.supabase_anon_key or "",
                service_role_key=settings.supabase_service_role_key,
                client=http_client,
            )
        else:
            gateway = PostgresGateway(
                settings.database_url or "",
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            )

        if settings.storage_backend == "gcs":
            if not settings.gcs_bucket:
                raise RuntimeError("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
            storage = GCSStorageGateway(settings.gcs_bucket, settings.gcp_project_id)
        elif isinstance(gateway, SupabaseGateway):
            storage = SupabaseStorageGateway(gateway)
        else:
            raise RuntimeError("Use STORAGE_BACKEND=gcs when DATA_BACKEND=postgres")

        app.state.auth_store = None
        if settings.auth_mode == "native" and isinstance(gateway, PostgresGateway):
            auth_store = NativeAuthStore(gateway.engine)
            try:
                await auth_store.ensure_schema()
            except Exception as error:  # DB may come up after the API does
                logger.warning("auth_schema_bootstrap_failed", error=str(error))
            app.state.auth_store = auth_store

        app.state.settings = settings
        app.state.http = http_client
        app.state.gateway = gateway
        app.state.storage = storage
        app.state.email = EmailGateway(settings)
        logger.info(
            "application_started",
            environment=settings.environment,
            data_backend=settings.data_backend,
            auth_mode=settings.auth_mode,
            storage_backend=settings.storage_backend,
        )
        try:
            yield
        finally:
            await gateway.close()
            await http_client.aclose()
            logger.info("application_stopped")

    app = FastAPI(
        title="Urban Farming API",
        version="0.1.0",
        description=(
            "GCP-ready backend replacing direct frontend access to Supabase while preserving "
            "the existing Urban Farming domain contracts."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    install_error_handlers(app)
    app.include_router(health.router)
    for router in (
        auth.router,
        accounts.router,
        gardens.router,
        inspections.router,
        plans.router,
        commerce.router,
        community.router,
        data.router,
        communications.router,
        geocoding.router,
        admin.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
