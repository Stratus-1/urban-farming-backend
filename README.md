# Urban Farming Backend

Production-oriented FastAPI backend for the Urban Farming platform. It provides a stable API
between the React frontend and infrastructure services while supporting a controlled migration
from Supabase to Google Cloud.

The production architecture uses Cloud Run for compute, Cloud SQL PostgreSQL for transactional
application data, Cloud Storage for uploads, and Secret Manager for credentials. BigQuery should
be added as an analytics destination when reporting volume requires it; it is not the operational
database for authentication, workflows, orders, or other user-facing transactions.

## Current production services

| Component | Service |
|---|---|
| Frontend | `urban-farming-git` on Cloud Run |
| Backend | `urban-farming-backend-git` on Cloud Run |
| Database | Cloud SQL PostgreSQL 17, instance `urban-farming-db` |
| Object storage | Cloud Storage bucket `urban-farming-inspection-photos` |
| Secrets | Secret Manager (`database-url`, `jwt-secret`, and other sensitive values) |
| Region | `europe-west1` |
| GCP project | `stratus-website-496818` |

Production URLs:

- Frontend: `https://urban-farming-git-737493449401.europe-west1.run.app`
- API: `https://urban-farming-backend-git-737493449401.europe-west1.run.app`
- OpenAPI: `https://urban-farming-backend-git-737493449401.europe-west1.run.app/docs`

## Architecture

```text
Browser / React frontend
          |
          | HTTPS + bearer JWT
          v
FastAPI backend on Cloud Run
          |
          +--> Cloud SQL PostgreSQL      application state and transactions
          +--> Cloud Storage             inspection photos and uploads
          +--> SMTP                      transactional email
          +--> Google Identity Services  optional Google sign-in
          +--> Nominatim                 geocoding

Cloud SQL/PostgreSQL --> BigQuery        future analytics and BI pipeline
```

Cloud SQL is the system of record for current operational state: users, roles, properties,
gardens, inspections, workflows, orders, inventory, and refresh tokens. BigQuery is appropriate
for historical reporting, aggregated KPIs, cohort analysis, forecasting, and BI—not low-latency
CRUD or authentication.

The backend can operate in two infrastructure modes:

| Concern | GCP production | Supabase compatibility/rollback |
|---|---|---|
| Data | `DATA_BACKEND=postgres` | `DATA_BACKEND=supabase` |
| Auth | `AUTH_MODE=native` or `oidc` | `AUTH_MODE=supabase` |
| Files | `STORAGE_BACKEND=gcs` | `STORAGE_BACKEND=supabase` |

## Repository layout

```text
app/
  core/               settings, JWTs, security, errors, and logging
  infrastructure/     PostgreSQL, Supabase, storage, email, and auth adapters
  routers/            FastAPI route groups
  schemas/            request and response models
  services/           domain services
database/
  cloud_sql/          compatibility objects required by Cloud SQL
  supabase_migrations preserved frontend/Supabase schema migrations
docs/                 API inventory and Cloud Run notes
scripts/              schema bootstrap, export/import, and env sync utilities
tests/                 unit and integration-style API tests
Dockerfile             production container
cloudbuild.yaml         build, push, and Cloud Run deployment
docker-compose.yml      local API and PostgreSQL stack
```

## Prerequisites

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Docker and Docker Compose for the containerized local stack
- PostgreSQL client tools (`psql`, `pg_dump`, `pg_restore`) for schema/data migration
- Google Cloud CLI for deployment and production operations

## Local development

### 1. Install dependencies

```bash
cd /Users/user/stratsol-projects/urban-farming-backend
uv sync --extra dev
```

### 2. Configure the environment

```bash
cp .env.example .env
```

For local PostgreSQL and native authentication, configure at least:

```env
ENVIRONMENT=development
DATA_BACKEND=postgres
AUTH_MODE=native
JWT_SECRET=replace-with-a-long-random-value
DATABASE_URL=postgresql+asyncpg://urban_farming:local-development-only@127.0.0.1:5432/urban_farming
STORAGE_BACKEND=gcs
GCS_BUCKET=urban-farming-inspection-photos
GCP_PROJECT_ID=stratus-website-496818
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:8081
```

Generate a local JWT secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never commit `.env`, database URLs, JWT secrets, SMTP passwords, Google credentials, or exported
user data.

### 3. Start PostgreSQL and bootstrap the schema

```bash
docker compose up -d postgres
make db-bootstrap
```

The bootstrap applies `database/cloud_sql/0000_supabase_compatibility.sql`, followed by every SQL
file in `database/supabase_migrations` in filename order.

### 4. Run the API

```bash
make dev
```

Useful local URLs:

- API documentation: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Liveness: `http://127.0.0.1:8000/health/live`
- Readiness: `http://127.0.0.1:8000/health/ready`

### Run the complete local stack with Docker

```bash
docker compose up --build
```

The host exposes the API on port `8000`; the container listens on `8080`.

## Configuration reference

Pydantic settings are defined in `app/core/config.py`. Comma-separated `ALLOWED_ORIGINS` values
are parsed into an origin list.

| Variable | Required when | Purpose |
|---|---|---|
| `ENVIRONMENT` | Always | `development`, `test`, `staging`, or `production` |
| `API_PREFIX` | Optional | API prefix; defaults to `/api/v1` |
| `LOG_LEVEL` | Optional | Application log level; defaults to `INFO` |
| `ALLOWED_ORIGINS` | Browser clients | Exact frontend origins allowed by CORS |
| `DATA_BACKEND` | Always | `postgres` or `supabase` |
| `AUTH_MODE` | Always | `native`, `supabase`, `oidc`, or local-only `development` |
| `DATABASE_URL` | `DATA_BACKEND=postgres` | SQLAlchemy async PostgreSQL URL |
| `DB_POOL_SIZE` | PostgreSQL | Base connection pool size |
| `DB_MAX_OVERFLOW` | PostgreSQL | Additional burst connections |
| `JWT_SECRET` | `AUTH_MODE=native` | Signs access, refresh, and recovery tokens |
| `JWT_ISSUER` | Native auth | Token issuer |
| `JWT_AUDIENCE` | Native auth | Token audience |
| `ACCESS_TOKEN_TTL_SECONDS` | Optional | Access token lifetime; default 3600 |
| `REFRESH_TOKEN_TTL_SECONDS` | Optional | Refresh token lifetime; default 2592000 |
| `GOOGLE_CLIENT_ID` | Google login | Google web OAuth client ID |
| `SUPABASE_URL` | Supabase data/auth | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase data/auth | Public Supabase client key |
| `SUPABASE_SERVICE_ROLE_KEY` | Selected admin operations | Privileged Supabase key; secret only |
| `OIDC_ISSUER` | `AUTH_MODE=oidc` | Trusted token issuer |
| `OIDC_AUDIENCE` | `AUTH_MODE=oidc` | Expected token audience |
| `OIDC_JWKS_URL` | `AUTH_MODE=oidc` | Issuer signing-key endpoint |
| `STORAGE_BACKEND` | Always | `gcs` or `supabase` |
| `GCS_BUCKET` | `STORAGE_BACKEND=gcs` | Upload bucket name |
| `GCP_PROJECT_ID` | GCP integrations | Google Cloud project ID |
| `SMTP_HOST` | Email enabled | SMTP server |
| `SMTP_PORT` | Email enabled | STARTTLS port, normally `587` |
| `SMTP_USER` | Email enabled | SMTP username |
| `SMTP_PASSWORD` | Email enabled | SMTP password; store in Secret Manager |
| `SMTP_FROM_EMAIL` | Email enabled | Sender address |
| `SMTP_FROM_NAME` | Optional | Human-readable sender name |
| `ADMIN_EMAIL` | Optional | Operational notification recipient |
| `GEOCODING_USER_AGENT` | Geocoding | Identifying Nominatim user agent |

Runtime validation intentionally stops production startup when required settings are absent or
inconsistent. Cloud Run can report this as “container failed to start and listen on `PORT=8080`”;
always inspect the revision logs for the actual configuration exception.

## Authentication

Production currently uses backend-native authentication with JWT access/refresh tokens stored
against the Cloud SQL compatibility `auth` schema.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/signup` | Create a user and provision their profile/role |
| `POST /api/v1/auth/login` | Authenticate email/password and issue a session |
| `POST /api/v1/auth/refresh` | Rotate a refresh token |
| `POST /api/v1/auth/google` | Verify a Google ID token and create/login a user |
| `POST /api/v1/auth/logout` | Revoke the current user's refresh tokens |
| `POST /api/v1/auth/password-reset` | Send a short-lived password recovery link |
| `PUT /api/v1/auth/password` | Set a password using an access or recovery token |
| `GET /api/v1/auth/me` | Return the authenticated user and roles |

Protected calls use:

```http
Authorization: Bearer ACCESS_TOKEN
```

`AUTH_MODE=development` is available only outside production. It accepts `X-User-Id` and
`X-User-Role` headers and is intentionally rejected when `ENVIRONMENT=production`.

## API surface

All domain routes are mounted beneath `/api/v1`. Health endpoints are mounted at the root.

| Area | Main routes |
|---|---|
| Health | `GET /health/live`, `GET /health/ready` |
| Auth | `/api/v1/auth/*` |
| Account | `GET /api/v1/profile`, `PATCH /api/v1/profile/settings` |
| Gardens | `/api/v1/gardens/*`, `/api/v1/garden-requests/*`, `/api/v1/garden-tasks` |
| Inspections | `/api/v1/inspections/*` |
| Admin | `GET /api/v1/admin/dashboard`, `GET /api/v1/admin/users` |
| Marketplace | `GET /api/v1/marketplace/inventory` |
| Orders | `/api/v1/orders` |
| Community | `/api/v1/community/*`, `/api/v1/green-points` |
| Plans | `/api/v1/calculator-plans` |
| Communications | `/api/v1/contact`, `/api/v1/newsletter`, `/api/v1/notifications/*` |
| Geocoding | `/api/v1/geocoding/search`, `/api/v1/geocoding/reverse` |
| Compatibility data API | `/api/v1/data/query`, `/api/v1/data/mutate`, `/api/v1/data/rpc` |

See `docs/API_INVENTORY.md` for the Supabase-to-API mapping. The generated OpenAPI document is
the authoritative request/response reference for the running revision.

## Database schema and migration

The Cloud SQL schema is derived from:

1. `database/cloud_sql/0000_supabase_compatibility.sql`
2. Every `database/supabase_migrations/*.sql` file, sorted by filename

The compatibility layer creates the minimum Supabase-compatible objects needed by preserved
migrations, including roles, `auth.users`, refresh-token storage, `auth.uid()`, and storage tables.

### Bootstrap a PostgreSQL database

```bash
export DATABASE_URL_PSQL='postgresql://USER:PASSWORD@HOST:5432/urban_farming'
./scripts/bootstrap_cloud_sql.sh
```

Use a Cloud SQL Auth Proxy endpoint for a private or non-authorized production instance:

```bash
cloud-sql-proxy stratus-website-496818:europe-west1:urban-farming-db

export DATABASE_URL_PSQL='postgresql://urban_farming:PASSWORD@127.0.0.1:5432/urban_farming'
./scripts/bootstrap_cloud_sql.sh
```

Treat schema replay as a controlled operation. The preserved migrations are ordered migration
files, not a general-purpose “run repeatedly against any state” synchronization engine.

### Export Supabase data

```bash
export SUPABASE_DATABASE_URL='postgresql://...'
./scripts/export_supabase_data.sh /secure/path/urban-farming-data
```

This produces a public-schema custom dump and an auth-users CSV. Both contain sensitive
production data and must never be committed or uploaded to an unsecured location.

### Import into Cloud SQL

```bash
export DATABASE_URL_PSQL='postgresql://urban_farming:PASSWORD@127.0.0.1:5432/urban_farming'
./scripts/import_cloud_sql_data.sh /secure/path/urban-farming-data
```

The current auth export intentionally does not copy password hashes. Imported users must use the
password-reset flow or be recreated before native email/password login will work.

Before switching production traffic, reconcile at minimum:

- User UUIDs, profiles, and roles
- Properties, installations, and active garden requests
- Inspector records, assignments, reports, and photos
- Crop batches, harvests, inventory, orders, and totals
- Workflow stages and event history
- Storage object references

## Frontend integration and CORS

The frontend browser client uses `VITE_API_URL`:

```env
VITE_API_URL=https://urban-farming-backend-git-737493449401.europe-west1.run.app
```

The backend must allow the exact deployed frontend origin:

```env
ALLOWED_ORIGINS=https://urban-farming-git-737493449401.europe-west1.run.app,http://localhost:3000,http://localhost:5173,http://localhost:8081
```

Because commas are meaningful to the `gcloud` dictionary flag parser, use a custom separator when
updating this variable:

```bash
gcloud run services update urban-farming-backend-git \
  --project=stratus-website-496818 \
  --region=europe-west1 \
  --update-env-vars='^@^ALLOWED_ORIGINS=https://urban-farming-git-737493449401.europe-west1.run.app,http://localhost:3000,http://localhost:5173,http://localhost:8081'
```

An `OPTIONS` response without `Access-Control-Allow-Origin` means the origin is missing or does
not match exactly. A successful preflight followed by a `4xx` or `5xx` means CORS is working and
the application/database error should be investigated separately.

## Cloud Run deployment

The production image starts Uvicorn on `0.0.0.0:${PORT}`. Cloud Run provides `PORT=8080`; do not
hardcode a different container listener.

Build and deploy using the checked-in Cloud Build configuration:

```bash
gcloud builds submit \
  --project=stratus-website-496818 \
  --config=cloudbuild.yaml
```

The current `cloudbuild.yaml` targets `europe-west1` and service
`urban-farming-backend-git`.

### Required production configuration

Configure the Cloud SQL attachment, non-secret environment variables, and Secret Manager values
on the Cloud Run service:

```bash
gcloud run services update urban-farming-backend-git \
  --project=stratus-website-496818 \
  --region=europe-west1 \
  --add-cloudsql-instances=stratus-website-496818:europe-west1:urban-farming-db \
  --update-env-vars='^@^ENVIRONMENT=production@DATA_BACKEND=postgres@AUTH_MODE=native@STORAGE_BACKEND=gcs@GCS_BUCKET=urban-farming-inspection-photos@GCP_PROJECT_ID=stratus-website-496818@ALLOWED_ORIGINS=https://urban-farming-git-737493449401.europe-west1.run.app' \
  --update-secrets='JWT_SECRET=jwt-secret:latest,DATABASE_URL=database-url:latest'
```

Store SMTP passwords and other credentials in Secret Manager as well; do not place them directly
in commands, `cloudbuild.yaml`, Docker build arguments, or committed environment files.

The runtime service account needs:

- Cloud SQL Client
- Secret Manager Secret Accessor for the specific runtime secrets
- Minimum required Cloud Storage object permissions on the upload bucket

### Verify a deployment

```bash
API_URL='https://urban-farming-backend-git-737493449401.europe-west1.run.app'

curl -fsS "$API_URL/health/live"
curl -fsS "$API_URL/health/ready"
curl -fsS "$API_URL/openapi.json" >/dev/null
```

Test CORS preflight:

```bash
curl -i -X OPTIONS "$API_URL/api/v1/auth/login" \
  -H 'Origin: https://urban-farming-git-737493449401.europe-west1.run.app' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

## Quality checks

```bash
make lint
make test
docker build -t urban-farming-backend .
```

Individual commands:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=app --cov-report=term-missing
```

## Operational troubleshooting

### Cloud Run says the container did not listen on `PORT=8080`

The Docker entrypoint already binds to the Cloud Run port. Inspect revision logs before changing
ports or extending the health-check timeout:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="urban-farming-backend-git"' \
  --project=stratus-website-496818 \
  --limit=100 \
  --order=desc
```

Typical startup causes:

- Missing `DATABASE_URL` while `DATA_BACKEND=postgres`
- Missing `JWT_SECRET` while `AUTH_MODE=native`
- Missing `GCS_BUCKET` while `STORAGE_BACKEND=gcs`
- Production configured with `AUTH_MODE=development`
- Secret Manager permission failure
- Cloud SQL attachment, credentials, or socket mismatch

### Login returns `500`

Inspect the traceback. `relation "auth.users" does not exist` means the Cloud SQL compatibility
schema was not applied. Run the schema bootstrap before retrying. Once the route returns
`401 invalid_credentials`, the database path is healthy and the remaining issue is user/password
state rather than infrastructure.

### Login returns `401` after importing users

The default export/import scripts preserve user identity metadata but not password hashes. Use
password reset or recreate the account. Also verify the corresponding `profiles` and `user_roles`
rows exist.

### Browser reports a CORS failure

Confirm the browser's exact `Origin` is present in `ALLOWED_ORIGINS`, deploy a new revision, and
test the preflight independently. Do not use `*` with credentialed browser requests.

### Readiness returns `503`

`/health/live` only proves the process is alive. `/health/ready` pings the selected data backend.
A `503` points to database/network/credential availability and should prevent traffic promotion.

## Security expectations

- Keep secrets in Secret Manager and grant access only to the runtime service account.
- Rotate any credential that has been pasted into terminals, logs, tickets, or chat systems.
- Never expose the database directly to the browser.
- Keep production CORS origins explicit.
- Use least-privilege Cloud SQL, Cloud Storage, and Secret Manager IAM roles.
- Preserve server-side authorization even when PostgreSQL RLS policies exist.
- Treat exported auth CSVs and database dumps as sensitive production data.
- Keep `AUTH_MODE=development` disabled in production.
- Add rate limiting and account lockout controls before high-volume public authentication traffic.

## Related documentation

- `docs/API_INVENTORY.md` — Supabase-to-API contract mapping
- `docs/DEPLOY_CLOUD_RUN.md` — focused Cloud Run deployment notes
- `/docs` on a running service — generated interactive API documentation

