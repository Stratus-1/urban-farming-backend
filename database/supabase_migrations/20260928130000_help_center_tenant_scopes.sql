-- Exact, owner-provisioned mapping from an opaque Help Center tenant reference
-- to one or more product request owners. The application can read this mapping
-- only through the dedicated tenant-scoped projection query.
CREATE TABLE IF NOT EXISTS public.help_center_tenant_scopes (
    tenant_scope_ref TEXT NOT NULL,
    owner_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT help_center_tenant_scopes_pk PRIMARY KEY (tenant_scope_ref, owner_id),
    CONSTRAINT help_center_tenant_scopes_owner_unique UNIQUE (owner_id),
    CONSTRAINT help_center_tenant_scopes_scope_format
        CHECK (tenant_scope_ref ~ '^uf-tenant-[0-9a-f]{64}$')
);

REVOKE ALL ON TABLE public.help_center_tenant_scopes FROM PUBLIC;
GRANT SELECT ON TABLE public.help_center_tenant_scopes TO urban_farming;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON TABLE public.help_center_tenant_scopes FROM urban_farming;

COMMENT ON TABLE public.help_center_tenant_scopes IS
    'Owner-provisioned mapping for the disabled, read-only Help Center garden-request projection. No public intake or self-service writes.';
