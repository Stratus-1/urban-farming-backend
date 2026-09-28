#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL_PSQL:-}" ]]; then
  echo "DATABASE_URL_PSQL is required (schema-owner PostgreSQL URL)." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATION="${ROOT_DIR}/database/supabase_migrations/20260928130000_help_center_tenant_scopes.sql"

current_user="$(psql "${DATABASE_URL_PSQL}" -XAtq -v ON_ERROR_STOP=1 -c "SELECT current_user")"
if [[ "${current_user}" == "urban_farming" ]]; then
  echo "Refusing to apply the scope map as the urban_farming runtime login." >&2
  exit 1
fi

echo "Applying the Help Center scope map as schema owner ${current_user}."
psql "${DATABASE_URL_PSQL}" -v ON_ERROR_STOP=1 -f "${MIGRATION}"

# Transfer ownership to the dedicated migration principal even if an earlier
# bootstrap created the table under a different role. This query reads metadata only.
psql "${DATABASE_URL_PSQL}" -v ON_ERROR_STOP=1 \
  -c "ALTER TABLE public.help_center_tenant_scopes OWNER TO CURRENT_USER"

verification="$(psql "${DATABASE_URL_PSQL}" -XAtq -v ON_ERROR_STOP=1 -c "
SELECT CASE
  WHEN pg_get_userbyid(table_meta.relowner) <> 'urban_farming'
    AND (SELECT count(*) = 3
         FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'help_center_tenant_scopes')
    AND EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'help_center_tenant_scopes'
                  AND column_name = 'tenant_scope_ref' AND data_type = 'text'
                  AND is_nullable = 'NO')
    AND EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'help_center_tenant_scopes'
                  AND column_name = 'owner_id' AND data_type = 'uuid'
                  AND is_nullable = 'NO')
    AND EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'help_center_tenant_scopes'
                  AND column_name = 'created_at' AND data_type = 'timestamp with time zone'
                  AND is_nullable = 'NO')
    AND EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = table_meta.oid
                  AND conname = 'help_center_tenant_scopes_pk'
                  AND contype = 'p' AND convalidated)
    AND EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = table_meta.oid
                  AND conname = 'help_center_tenant_scopes_owner_unique'
                  AND contype = 'u' AND convalidated)
    AND EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = table_meta.oid
                  AND conname = 'help_center_tenant_scopes_scope_format'
                  AND contype = 'c' AND convalidated)
    AND has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'SELECT')
    AND NOT has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'INSERT')
    AND NOT has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'UPDATE')
    AND NOT has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'DELETE')
    AND NOT has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'TRUNCATE')
    AND NOT has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'REFERENCES')
    AND NOT has_table_privilege('urban_farming', 'public.help_center_tenant_scopes', 'TRIGGER')
  THEN 'verified'
  ELSE 'failed'
END
FROM pg_class AS table_meta
JOIN pg_namespace AS schema_meta ON schema_meta.oid = table_meta.relnamespace
WHERE schema_meta.nspname = 'public'
  AND table_meta.relname = 'help_center_tenant_scopes'
  AND table_meta.relkind = 'r'
")"

if [[ "${verification}" != "verified" ]]; then
  echo "Scope map ownership/privileges did not pass verification; do not provision mappings." >&2
  exit 1
fi

echo "Scope map schema and runtime SELECT-only privileges verified. No product rows were queried."
