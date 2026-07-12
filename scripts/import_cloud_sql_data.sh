#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL_PSQL:-}" ]]; then
  echo "DATABASE_URL_PSQL is required." >&2
  exit 1
fi

INPUT_PREFIX="${1:-urban-farming-data}"
PUBLIC_DUMP="${INPUT_PREFIX}-public.dump"
AUTH_CSV="$(cd "$(dirname "${INPUT_PREFIX}")" && pwd)/$(basename "${INPUT_PREFIX}")-auth-users.csv"
if [[ ! -f "${PUBLIC_DUMP}" || ! -f "${AUTH_CSV}" ]]; then
  echo "Expected ${PUBLIC_DUMP} and ${AUTH_CSV}." >&2
  exit 1
fi

psql "${DATABASE_URL_PSQL}" -v ON_ERROR_STOP=1 -c "\copy auth.users (
  id, email, raw_app_meta_data, raw_user_meta_data,
  email_confirmed_at, last_sign_in_at, created_at, updated_at
) FROM '${AUTH_CSV}' CSV HEADER"

pg_restore \
  --dbname="${DATABASE_URL_PSQL}" \
  --data-only \
  --no-owner \
  --no-privileges \
  --disable-triggers \
  --exit-on-error \
  "${PUBLIC_DUMP}"

echo "Cloud SQL data import complete. Run reconciliation before switching writes."
