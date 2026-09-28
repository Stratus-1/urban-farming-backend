# Help Center read-only support projection

**State (2026-09-28):** Product authorization for the proposed support purpose, field contract, and safeguards is recorded in `HELP_CENTER_SUPPORT_APPROVAL.md`. The product backend is currently Cloud Run revision `urban-farming-backend-prod-00018-7sn` (100% traffic). A metadata-only production check found no `HELP_CENTER_*` or `SUPPORT_*` service environment settings, and the projection endpoint returned HTTP 404 with a placeholder scope, confirming the feature remains disabled. The current Help Center runtime identity is `stratus-help-center-runtime@stratus-website-496818.iam.gserviceaccount.com`; it is also the general Help Center runtime identity, so a dedicated connector principal has not been established. Product Cloud Run invoker IAM is disabled, making the route's application-level Google OIDC identity check the relevant caller gate. The supplied Help Center deployment update says the mapping migration is unapplied and no product/tenant grants exist. A direct production schema check was blocked because the available ADC identity lacks `cloudsql.instances.get`; no product rows, mappings, or contact messages were queried. Public contact remains separate.

## Contract

`GET /api/v1/integrations/help-center/garden-requests`

- Method is read-only. The route is feature-gated by `HELP_CENTER_PROJECTION_ENABLED` and requires PostgreSQL plus native authentication mode.
- Caller must present a Google-issued OIDC ID token in `Authorization: Bearer`. Signature, expiry, exact audience and the configured `HELP_CENTER_SERVICE_ACCOUNT_EMAIL` are verified. Human product tokens are not accepted.
- The exact expected audience is configured in `HELP_CENTER_PROJECTION_AUDIENCE` and must be the product API Cloud Run URL.
- Caller must send 1–100 repeated `X-Help-Center-Tenant-Scope` headers. Invalid or missing scopes are rejected. PostgreSQL applies these exact opaque refs to the source query through an inner join to `public.help_center_tenant_scopes`; garden-request rows for other owners are not selected into the application process.
- `limit` is bounded to 1–500. If the selected source exceeds the requested limit, the endpoint returns 503 and no partial snapshot.
- The response contract is version `1.0`, product id `urban_farming`, and a bounded snapshot timestamp.

The data query reads only `public.garden_requests` and the owner-provisioned `public.help_center_tenant_scopes` mapping. The mapping table is not exposed through generic data routes. The migration grants SELECT and revokes DML from the `urban_farming` database login, but this is an effective read-only boundary only if that login is not the table owner, a superuser, or a member of another role with write privileges. The controlled Cloud SQL migration must verify table ownership and effective privileges before any mapping is provisioned. The response fields are:

| Field | Source/derivation | Allowed values |
| --- | --- | --- |
| `case_ref` | HMAC of garden request id; truncated to 112 bits | `ufc-` plus 28 lowercase hex characters |
| `tenant_scope_ref` | Domain-separated HMAC of the product-owned request `owner_id` | `uf-tenant-` plus 64 lowercase hex characters |
| `requester_ref` | Separate domain-separated HMAC of the same product-owned `owner_id` | `uf-user-` plus 64 lowercase hex characters |
| `category` | Fixed by the source route | `garden_request` |
| `status` | Existing garden-request lifecycle enum | `submitted`, `inspection_scheduled`, `accepted`, `needing_implements`, `implements_installed`, `seeds`, `final_install`, `live`, `rejected`, `cancelled` |
| `created_at`, `updated_at` | Product request timestamps | UTC-aware timestamps |

The response excludes names, email addresses, phone numbers, addresses, city, garden labels, request details, free text, photos, inspection notes, and admin notes. A separate secret `SUPPORT_REFERENCE_SECRET` is required to derive stable references; do not reuse JWT, database, SMTP or Help Center secrets. Keep it in Secret Manager.

## Explicitly out of scope

- `POST /api/v1/contact` continues to store and email contact submissions; its categories combine support, sales, partnerships, billing and feedback. It is not read by this projection.
- The admin recent-message/dashboard output exposes names and email under a product-user bearer token. It is not a machine identity contract, has no central tenant binding, and must not be connected to the Help Center.
- No contact, assessment lead, account profile, user credential, message body, or attachment enters the central projection.
- The central Help Center reads this snapshot on demand and does not persist it. Its UI sends `Cache-Control: no-store`; support case rows are not copied into the Help Center database.

## Access, abuse, and retention findings

- Contact submission is public and unauthenticated. The backend schema validates email format and limits individual field lengths (message up to 10,000 characters), but no application-level rate limiter, CAPTCHA, or deduplication control was found in the reviewed route or backend middleware. Upstream Cloud Armor/rate controls were not verified.
- No contact-message retention period or automated deletion policy was found in the reviewed backend code or checked-in migrations. Actual database retention/backup behavior remains unverified.
- A separate production owner/security review is required for contact abuse controls and retention. These are not silently folded into the garden-request feed.
- Existing product garden-request retention remains governed by the product system; central retention is zero because the Help Center performs an uncached read-through and does not store responses. Cloud logging must remain payload-free; tenant refs are sent as headers rather than URL query values.

## Rollout gates

1. Product authorization for the garden-request lifecycle purpose, exact field list, and proposed support handling was given by Daniel Mommsen on 2026-09-28 and recorded in `HELP_CENTER_SUPPORT_APPROVAL.md`. Formal privacy/legal review is not evidenced and should be confirmed through the applicable owner process.
2. Provision a dedicated connector service account, distinct from the general Help Center runtime identity, and implement its use by the Help Center workload. Authorize only that principal at the source application layer; configure the same exact principal in `HELP_CENTER_SERVICE_ACCOUNT_EMAIL` and the product service URL as `HELP_CENTER_PROJECTION_AUDIENCE`. Keep the source route disabled until the Help Center code change is reviewed and deployed.
3. Apply `database/supabase_migrations/20260928130000_help_center_tenant_scopes.sql` using `scripts/apply_help_center_scope_migration.sh` and a schema-owner Cloud SQL URL. The general bootstrap deliberately skips this migration. The runner verifies from metadata that the table owner is distinct from the `urban_farming` runtime login and that its effective privileges allow SELECT but deny INSERT, UPDATE, DELETE, and TRUNCATE. If ownership or privileges fail verification, stop before provisioning mappings. Product/security owners create a new random 32-byte-plus `SUPPORT_REFERENCE_SECRET` in Secret Manager, then provision approved `(tenant_scope_ref, owner_id)` mappings through a restricted database-owner process. Never grant product-wide wildcard access.
4. Keep `HELP_CENTER_PROJECTION_ENABLED=false` until the central operator access policy contains explicitly approved `(urban-farming, tenant_scope_ref)` grants and the Help Center source URL/audience point to the verified production service. User authorization did not enumerate tenant scopes; none are approved or provisioned.
5. Deploy the product API with the feature still disabled; verify readiness and confirm an unauthenticated request returns 404. Enabling requires the named decisions above and an authenticated walkthrough using real authorized records.
6. Roll out the Help Center read-through and inspect an authorized browser response, then verify a second tenant scope is hidden and the output contains only the contract fields. Do not copy response bodies into logs, fixtures or tickets.
7. To roll back, set `HELP_CENTER_PROJECTION_ENABLED=false`, redeploy the API, and remove the Help Center's source-service invocation grant. No central records need deletion because the feed is not persisted.

## Verification status

All 50 backend tests pass; focused tests cover allowlisted projection fields, status rejection, Google OIDC audience/service-account verification, exact SQL join/filter shape, and a negative two-tenant query simulation proving only requested-scope rows are selected by the query. Ruff and diff checks pass. Tests do not exercise Google's live token service, Cloud Run IAM, real Cloud SQL rows, the unapplied mapping migration, central IAP, browser access or owner-approved data. The deployed feature remains disabled by default.

The product-side purpose, field limits, data handling, and authorization record are captured in `HELP_CENTER_SUPPORT_APPROVAL.md`. Product authorization is recorded; formal privacy/legal review, database isolation, dedicated connector identity, exact tenant scope approvals, and authenticated behavior still require verification. Do not create tenant mappings or enable the projection until those concrete gates pass.
