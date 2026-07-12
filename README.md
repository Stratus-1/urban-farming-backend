# Urban Farming Backend

Standalone FastAPI backend for the Urban Farming platform. It is designed for a staged migration
from Supabase-managed backend services to Google Cloud without forcing a second frontend rewrite.

## Architecture

The API is the stable boundary. Infrastructure is selected with environment variables:

| Concern | Compatibility mode | GCP target mode |
|---|---|---|
| Compute | FastAPI on Cloud Run | FastAPI on Cloud Run |
| Data | Existing Supabase PostgREST/RLS | Cloud SQL PostgreSQL |
| Auth | Existing Supabase access tokens | Identity Platform or another OIDC issuer |
| Files | Supabase Storage | Cloud Storage |
| Secrets | Local environment variables | Secret Manager injected into Cloud Run |
| Delivery | Local SMTP-compatible provider | SMTP provider or a later transactional-email adapter |

This separation is intentional. Moving compute, database, auth, and storage simultaneously would
make rollback and data reconciliation unsafe.

## Local setup

```bash
cd /Users/user/stratsol-projects/urban-farming-backend
cp .env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface.

For compatibility mode, copy the existing frontend values into backend-only variables:

```env
DATA_BACKEND=supabase
AUTH_MODE=supabase
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_ANON_KEY=...
```

Add `SUPABASE_SERVICE_ROLE_KEY` only through Secret Manager when a future administrative operation
requires it. The current API preserves user RLS by forwarding the caller's access token.

## Development authentication

For local API development without an auth provider:

```env
ENVIRONMENT=development
AUTH_MODE=development
```

Send `X-User-Id` and `X-User-Role` headers. This mode is explicitly blocked in production.

## Cloud SQL bootstrap

The original Supabase migrations are preserved under `database/supabase_migrations`.

```bash
export DATABASE_URL_PSQL='postgresql://USER:PASSWORD@HOST:5432/urban_farming'
./scripts/bootstrap_cloud_sql.sh
```

Then export and import data during a controlled maintenance window:

```bash
export SUPABASE_DATABASE_URL='postgresql://...'
./scripts/export_supabase_data.sh /secure/path/urban-farming-data
./scripts/import_cloud_sql_data.sh /secure/path/urban-farming-data
```

Never commit the dump. Reconcile table counts, UUIDs, order totals, active garden requests, inspector
assignments, and storage references before enabling Cloud SQL writes.

For Cloud Run with the Cloud SQL Unix socket, use a URL shaped like:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@/urban_farming?host=/cloudsql/PROJECT:REGION:INSTANCE
DATA_BACKEND=postgres
```

Use `STORAGE_BACKEND=gcs` with `GCS_BUCKET`, and grant the Cloud Run service account Cloud SQL
Client, Secret Manager Secret Accessor, and the minimum required Storage Object permissions.

## Cloud Run deployment

Create an Artifact Registry repository, connect the repository to Cloud Build, and run:

```bash
gcloud builds submit --config cloudbuild.yaml
```

The included config targets `africa-south1`. Configure secrets on the Cloud Run service rather than
putting credentials in `cloudbuild.yaml`.

## Verification

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
docker build -t urban-farming-api .
```

See [docs/API_INVENTORY.md](docs/API_INVENTORY.md) for the current contract mapping and frontend
cutover boundary.
# urban-farming-backend
