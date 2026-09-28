# Urban Farming support projection approval record

**Status:** Pending owner decisions. This document does not grant access or approve processing.

## Requested purpose

Allow an authorized support operator to look up the lifecycle state of an existing Urban Farming garden request when responding to a grower support case. The Help Center reads a bounded snapshot on demand. It must not become a channel for creating requests, changing request status, deciding eligibility, marketing, or product analytics.

## Proposed data contract

The projection returns only:

- HMAC-derived `case_ref`, `tenant_scope_ref`, and `requester_ref` values.
- Fixed category `garden_request`.
- The existing garden-request lifecycle status.
- Request creation and update timestamps.

It excludes names, email addresses, phone numbers, addresses, suburb/city, garden labels, free text, photos, inspection notes, contact messages, account credentials, and administrator notes. The status and timestamps still describe a real person's request; the HMAC references are pseudonymous and must not be treated as anonymous data.

## Required decisions before production access

Record a named approver, decision, and date for each item:

| Decision | Required owner | Decision | Approver / date |
| --- | --- | --- | --- |
| Confirm this support purpose and the exact lifecycle fields above | Urban Farming product owner | Pending | |
| Confirm the applicable privacy notice/legal basis, support-agent use, and source retention | Privacy/data owner | Pending | |
| Approve the dedicated connector principal, token audience, invocation policy, key custody, and rotation procedure | Security/IAM owner | Pending | |
| Approve each grower-owner scope to be available to the Help Center operators | Product/data owner for that tenant | Pending | |
| Confirm central read-through, no persistence/cache, and payload-free logging | Help Center service owner | Pending | |

## Product-side implementation gates

1. Apply `database/supabase_migrations/20260928130000_help_center_tenant_scopes.sql` through the controlled Cloud SQL migration path. Verify table structure and grants from database metadata only; do not inspect request or contact rows for this verification.
2. After privacy and tenant approvals, create a dedicated `SUPPORT_REFERENCE_SECRET` in Secret Manager. Use it only for domain-separated HMAC references; never reuse auth, database, SMTP, or Help Center secrets.
3. Provision only the exact approved `(tenant_scope_ref, owner_id)` mappings through the restricted database-owner process. The product runtime role must retain SELECT-only access; no wildcard or product-wide mapping.
4. After security approval, configure the exact caller email and production Cloud Run audience on the product API and authorize only that dedicated principal to invoke it. Confirm the central service uses the dedicated identity for this source.
5. Keep `HELP_CENTER_PROJECTION_ENABLED=false` until all decisions and gates above are verified. Then perform an authenticated two-scope test with authorized real accounts, verifying that the second scope is excluded and no response payload is logged or persisted.

## Current evidence and hold

- Product route: `GET /api/v1/integrations/help-center/garden-requests`.
- Product backend revision observed: `urban-farming-backend-prod-00018-7sn` at 100% traffic.
- Product service has no `HELP_CENTER_*` or `SUPPORT_*` environment settings; an unauthenticated placeholder-scope request returns HTTP 404.
- The supplied deployment update reports no product or tenant-scope grants and an unapplied mapping migration.
- Current ADC cannot read production Cloud SQL metadata because it lacks `cloudsql.instances.get`. No product rows or contact messages were read.
- Therefore the production migration, mapping table, identity configuration, data-purpose approval, and authenticated support behavior remain unverified. Feed stays disabled.
