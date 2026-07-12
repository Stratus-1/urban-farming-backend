#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL_PSQL:-}" ]]; then
  echo "DATABASE_URL_PSQL is required (standard PostgreSQL URL for psql)." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

psql "${DATABASE_URL_PSQL}" -v ON_ERROR_STOP=1 \
  -f "${ROOT_DIR}/database/cloud_sql/0000_supabase_compatibility.sql"

for migration in "${ROOT_DIR}"/database/supabase_migrations/*.sql; do
  echo "Applying $(basename "${migration}")"
  psql "${DATABASE_URL_PSQL}" -v ON_ERROR_STOP=1 -f "${migration}"
done

echo "Cloud SQL schema bootstrap complete."

