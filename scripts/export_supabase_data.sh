#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SUPABASE_DATABASE_URL:-}" ]]; then
  echo "SUPABASE_DATABASE_URL is required." >&2
  exit 1
fi

OUTPUT_PREFIX="${1:-urban-farming-data}"
PUBLIC_DUMP="${OUTPUT_PREFIX}-public.dump"
AUTH_CSV="$(cd "$(dirname "${OUTPUT_PREFIX}")" && pwd)/$(basename "${OUTPUT_PREFIX}")-auth-users.csv"

pg_dump "${SUPABASE_DATABASE_URL}" \
  --format=custom \
  --data-only \
  --no-owner \
  --no-privileges \
  --schema=public \
  --file="${PUBLIC_DUMP}"

psql "${SUPABASE_DATABASE_URL}" -v ON_ERROR_STOP=1 -c "\copy (
  SELECT id, email, raw_app_meta_data, raw_user_meta_data,
         email_confirmed_at, last_sign_in_at, created_at, updated_at
  FROM auth.users
) TO '${AUTH_CSV}' CSV HEADER"

chmod 600 "${PUBLIC_DUMP}" "${AUTH_CSV}"

echo "Created ${PUBLIC_DUMP} and ${AUTH_CSV}. Treat both as sensitive production data."
