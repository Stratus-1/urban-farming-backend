-- Live admin reporting functions built on top of the core business tables.
-- These are intentionally views/RPCs, not duplicate tables, so the dashboard
-- always reflects current source-of-truth data.

CREATE OR REPLACE FUNCTION public.admin_dashboard_summary()
RETURNS TABLE (
  total_users integer,
  active_farms integer,
  inactive_farms integer,
  total_crops integer,
  total_orders integer,
  revenue numeric,
  pending_requests integer,
  open_messages integer,
  newsletter_subscriptions integer,
  total_area_m2 numeric,
  verified_users integer,
  active_this_month_users integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    (SELECT COUNT(*)::integer FROM auth.users),
    (SELECT COUNT(*)::integer FROM public.installations WHERE status = 'active'),
    (SELECT COUNT(*)::integer FROM public.installations WHERE status <> 'active'),
    (SELECT COUNT(*)::integer FROM public.inventory_aggregate),
    (SELECT COUNT(*)::integer FROM public.orders),
    COALESCE((SELECT SUM(total) FROM public.orders), 0),
    (SELECT COUNT(*)::integer
     FROM public.garden_requests
     WHERE status IN ('submitted', 'inspection_scheduled', 'accepted')),
    (SELECT COUNT(*)::integer FROM public.contact_messages WHERE status = 'new'),
    (SELECT COUNT(*)::integer FROM public.newsletter_subscriptions WHERE subscribed IS TRUE),
    COALESCE((SELECT SUM(size_m2) FROM public.installations), 0),
    (SELECT COUNT(*)::integer FROM auth.users WHERE email_confirmed_at IS NOT NULL),
    (SELECT COUNT(*)::integer
     FROM auth.users
     WHERE last_sign_in_at >= date_trunc('month', now()));
END; $$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_overview(range_days integer DEFAULT 7)
RETURNS TABLE (
  day_key text,
  label text,
  revenue numeric,
  orders integer,
  requests integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  effective_days integer := GREATEST(COALESCE(range_days, 7), 1);
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  WITH buckets AS (
    SELECT generate_series(
      date_trunc('day', now()) - ((effective_days - 1) * interval '1 day'),
      date_trunc('day', now()),
      interval '1 day'
    ) AS bucket_date
  )
  SELECT
    to_char(b.bucket_date, 'YYYY-MM-DD') AS day_key,
    to_char(b.bucket_date, 'Mon DD') AS label,
    COALESCE((
      SELECT SUM(o.total)
      FROM public.orders o
      WHERE o.created_at >= b.bucket_date
        AND o.created_at < b.bucket_date + interval '1 day'
    ), 0) AS revenue,
    COALESCE((
      SELECT COUNT(*)::integer
      FROM public.orders o
      WHERE o.created_at >= b.bucket_date
        AND o.created_at < b.bucket_date + interval '1 day'
    ), 0) AS orders,
    COALESCE((
      SELECT COUNT(*)::integer
      FROM public.garden_requests gr
      WHERE gr.created_at >= b.bucket_date
        AND gr.created_at < b.bucket_date + interval '1 day'
    ), 0) AS requests
  FROM buckets b
  ORDER BY b.bucket_date ASC;
END; $$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_order_status()
RETURNS TABLE (
  name text,
  value integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    o.status::text AS name,
    COUNT(*)::integer AS value
  FROM public.orders o
  GROUP BY o.status
  ORDER BY value DESC, name ASC;
END; $$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_top_crops(limit_count integer DEFAULT 5)
RETURNS TABLE (
  crop_id uuid,
  name text,
  category text,
  image_url text,
  available_kg numeric,
  contributing_growers integer,
  share integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
#variable_conflict use_column
DECLARE
  effective_limit integer := GREATEST(COALESCE(limit_count, 5), 1);
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  WITH ranked AS (
    SELECT
      ia.crop_id,
      ia.name,
      ia.category,
      ia.image_url,
      COALESCE(ia.available_kg, 0) AS crop_available_kg,
      COALESCE(ia.contributing_growers, 0)::integer AS contributing_growers
    FROM public.inventory_aggregate ia
    ORDER BY COALESCE(ia.available_kg, 0) DESC, ia.name ASC
    LIMIT effective_limit
  ),
  totals AS (
    SELECT NULLIF(SUM(ranked.crop_available_kg), 0) AS total_available
    FROM ranked
  )
  SELECT
    r.crop_id,
    r.name,
    r.category,
    r.image_url,
    r.crop_available_kg AS available_kg,
    r.contributing_growers,
    COALESCE(ROUND((r.crop_available_kg * 100.0) / t.total_available, 0), 0)::integer AS share
  FROM ranked r
  CROSS JOIN totals t
  ORDER BY r.crop_available_kg DESC, r.name ASC;
END; $$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_recent_orders(limit_count integer DEFAULT 5)
RETURNS TABLE (
  id uuid,
  status public.order_status,
  total numeric,
  created_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  effective_limit integer := GREATEST(COALESCE(limit_count, 5), 1);
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    o.id,
    o.status,
    o.total,
    o.created_at
  FROM public.orders o
  ORDER BY o.created_at DESC
  LIMIT effective_limit;
END; $$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_recent_messages(limit_count integer DEFAULT 4)
RETURNS TABLE (
  id uuid,
  subject text,
  name text,
  email text,
  status text,
  created_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  effective_limit integer := GREATEST(COALESCE(limit_count, 4), 1);
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    m.id,
    m.subject,
    m.name,
    m.email,
    m.status,
    m.created_at
  FROM public.contact_messages m
  ORDER BY m.created_at DESC
  LIMIT effective_limit;
END; $$;

GRANT EXECUTE ON FUNCTION public.admin_dashboard_summary() TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_dashboard_overview(integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_dashboard_order_status() TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_dashboard_top_crops(integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_dashboard_recent_orders(integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_dashboard_recent_messages(integer) TO authenticated;
