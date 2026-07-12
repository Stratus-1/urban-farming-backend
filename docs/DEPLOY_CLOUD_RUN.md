# Deploying to Cloud Run (project `stratus-website-496818`)

## Why the deploy failed

The revision crashed at startup: with no environment variables configured on the
Cloud Run service, `Settings.validate_runtime()` raises (no data-backend config),
uvicorn exits, and the container never listens on `$PORT` — which Cloud Run reports
as "container failed to start and listen on the port". The fix is configuration,
not code: set the env vars below on the service.

The Dockerfile honours `$PORT`, so the service's port setting (8000 or 8080) does
not matter.

## One-time setup

```bash
gcloud auth login          # tokens on this machine have expired
gcloud config set project stratus-website-496818

# 1. Secrets
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | \
  gcloud secrets create jwt-secret --data-file=-

# DATABASE_URL for Cloud SQL over the built-in unix socket:
#   postgresql+asyncpg://USER:PASSWORD@/urban_farming?host=/cloudsql/CONNECTION_NAME
# Find CONNECTION_NAME (project:region:instance) with: gcloud sql instances list
echo -n 'postgresql+asyncpg://urban_farming:DB_PASSWORD@/urban_farming?host=/cloudsql/stratus-website-496818:REGION:INSTANCE' | \
  gcloud secrets create database-url --data-file=-

# 2. Replay the schema into Cloud SQL (compatibility shim + all migrations,
#    including the handle_new_user trigger and auth.refresh_tokens):
cloud-sql-proxy stratus-website-496818:REGION:INSTANCE &
DATABASE_URL_PSQL=postgresql://urban_farming:DB_PASSWORD@127.0.0.1:5432/urban_farming \
  scripts/bootstrap_cloud_sql.sh

# 3. Bucket for inspection photos
gcloud storage buckets create gs://urban-farming-inspection-photos-us-central1 --location=us-central1

# 4. Give the service account access
#    (default compute SA or the one on the Cloud Run service)
SA=$(gcloud run services describe urban-farming-backend-git --region=us-central1 \
  --format='value(spec.template.spec.serviceAccountName)')
SA=${SA:-$(gcloud iam service-accounts list --filter='displayName:Compute Engine default' --format='value(email)')}
gcloud projects add-iam-policy-binding stratus-website-496818 \
  --member="serviceAccount:${SA}" --role=roles/cloudsql.client
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding database-url \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor
gcloud storage buckets add-iam-policy-binding gs://urban-farming-inspection-photos-us-central1 \
  --member="serviceAccount:${SA}" --role=roles/storage.objectAdmin
```

## Configure the service (fixes the failing deploy)

```bash
gcloud run services update urban-farming-backend-git \
  --region=us-central1 \
  --add-cloudsql-instances=stratus-website-496818:REGION:INSTANCE \
  --set-env-vars="ENVIRONMENT=production,DATA_BACKEND=postgres,AUTH_MODE=native,STORAGE_BACKEND=gcs,GCS_BUCKET=urban-farming-inspection-photos-us-central1,GCP_PROJECT_ID=stratus-website-496818,ALLOWED_ORIGINS=https://YOUR-FRONTEND-DOMAIN,ADMIN_EMAIL=admin@stratsol.co.za,SMTP_HOST=smtp.gmail.com,SMTP_PORT=587,SMTP_USER=admin@stratsol.co.za,SMTP_FROM_EMAIL=admin@stratsol.co.za,GOOGLE_CLIENT_ID=YOUR_OAUTH_CLIENT_ID" \
  --set-secrets="JWT_SECRET=jwt-secret:latest,DATABASE_URL=database-url:latest"

# SMTP password (or put it in Secret Manager too):
gcloud run services update urban-farming-backend-git --region=us-central1 \
  --update-env-vars="SMTP_PASSWORD=..."
```

Env vars set this way persist: the GitHub trigger only swaps the container image on
each push, it does not reset service configuration.

Verify after deploy:

```bash
curl https://SERVICE_URL/health/ready
curl -X POST https://SERVICE_URL/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"secret123","full_name":"You","role":"grower"}'
```

## Google sign-in

1. GCP console → APIs & Services → Credentials → Create credentials → OAuth client ID
   (type **Web application**; add the frontend origin to authorised JS origins).
2. Set the client ID as `GOOGLE_CLIENT_ID` on the Cloud Run service (above) and in the
   frontend.
3. Frontend uses Google Identity Services to obtain an **ID token**, then calls
   `POST /api/v1/auth/google` with `{"id_token": "..."}` and receives the same
   `{user, session, roles}` payload as `/auth/login`.

## Auth endpoints summary (AUTH_MODE=native)

| Endpoint | Notes |
|---|---|
| `POST /api/v1/auth/signup` | bcrypt-hashes password into `auth.users`; role (`grower/buyer/operator/inspector`) provisioned via trigger + idempotent fallback |
| `POST /api/v1/auth/login` | returns `{user, session:{access_token, refresh_token, expires_in}, roles}` |
| `POST /api/v1/auth/refresh` | rotates the refresh token (old one is revoked) |
| `POST /api/v1/auth/google` | verifies a Google ID token, creates the user on first sign-in |
| `POST /api/v1/auth/logout` | revokes all refresh tokens for the user |
| `POST /api/v1/auth/password-reset` | emails a 30-minute recovery link via SMTP |
| `PUT /api/v1/auth/password` | accepts an access or recovery token; revokes existing sessions |
| `GET /api/v1/auth/me` | id, email, roles |
