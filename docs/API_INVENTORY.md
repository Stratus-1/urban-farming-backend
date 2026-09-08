# Supabase-to-API inventory

This service consolidates the backend contracts previously split across browser-side Supabase
queries, Postgres RPCs, storage calls, and TanStack server functions.

## Domain mapping

| Existing capability | Existing Supabase seam | New API seam |
|---|---|---|
| Signup (role in user metadata) | `supabase.auth.signUp` | `POST /api/v1/auth/signup` |
| Login | `supabase.auth.signInWithPassword` | `POST /api/v1/auth/login` |
| Session refresh | `supabase.auth` autorefresh | `POST /api/v1/auth/refresh` |
| Logout | `supabase.auth.signOut` | `POST /api/v1/auth/logout` |
| Password reset / update | `supabase.auth.resetPasswordForEmail`, `updateUser` | `POST /api/v1/auth/password-reset`, `PUT /api/v1/auth/password` |
| Current user + roles | `supabase.auth.getUser` + `user_roles` select | `GET /api/v1/auth/me` |
| Google sign-in | browser-side OAuth helper | `POST /api/v1/auth/google` (redirect/callback code exchange in AUTH_MODE=native; no browser-side Google token handling) |
| Grower dashboard and gardens | `properties`, `installations`, `crop_batches`, `garden_requests`, `garden_tasks`, `garden_activity_logs`, `grower_stats` | `GET /api/v1/gardens/overview` |
| Public assessment lead | first-touch marketing/qualification form | `POST /api/v1/assessment-leads` |
| Submit garden request | `garden_requests.insert` plus notification server function | `POST /api/v1/garden-requests` |
| Admin request workflow | `garden_requests.update` | `PATCH /api/v1/garden-requests/{id}` |
| Admin assessment lead inbox | operator follow-up status tracking | `GET/PATCH /api/v1/admin/assessment-leads` |
| Inspection allocation | `recordGardenAllocation` TanStack server function | `POST /api/v1/garden-requests/{id}/allocation` |
| Grower care action | `recordGrowerCareAction` TanStack server function | `POST /api/v1/gardens/{id}/care-actions` |
| Inspector assignments | Direct reads across inspector tables | `GET /api/v1/inspections/assignments` |
| Start/submit inspection | `start_inspection_report`, `submit_inspection_report` RPCs | `/api/v1/inspections/reports/*` |
| Inspection photo storage | Supabase Storage `inspection-photos` | `POST /api/v1/inspections/reports/{id}/photos` |
| Admin reporting | Nine reporting RPCs | `GET /api/v1/admin/dashboard`, `GET /api/v1/admin/users` |
| Calculator saves | `calculator_plans` | `/api/v1/calculator-plans` |
| Marketplace | `inventory_aggregate`, `orders`, `order_items` | `/api/v1/marketplace/inventory`, `/api/v1/orders` |
| Profile/settings | `profiles`, `user_settings`, `grower_stats` | `/api/v1/profile` |
| Mobile push registration | `mobile_push_tokens` | `/api/v1/mobile/push-tokens` |
| Mobile push delivery | `mobile_push_tokens` | `POST /api/v1/mobile/notifications/send` |
| Events/community/points | grower content and green point tables | `/api/v1/community/*`, `/api/v1/green-points` |
| Contact/newsletter | tables plus SMTP server functions | `/api/v1/contact`, `/api/v1/newsletter` |
| Geocoding | Nominatim TanStack server functions | `/api/v1/geocoding/*` |

## Preserved database assets

All 18 SQL migrations from the frontend repository are copied into
`database/supabase_migrations`. They are treated as the current schema source during migration.
`database/cloud_sql/0000_supabase_compatibility.sql` supplies the minimal `auth` and `storage`
objects needed to replay those migrations on Cloud SQL.

## Remaining frontend cutover work

The React application still calls Supabase directly. Move one domain hook at a time to this API,
starting with write operations, then dashboard reads, then admin reporting. Do not remove Supabase
RLS or direct-query code until traffic and reconciliation show that the corresponding API route is
stable.
