-- Period-over-period trend data for admin cards.
-- The frontend uses this together with a shared percent-change service.

CREATE OR REPLACE FUNCTION public.admin_dashboard_trends(range_days integer DEFAULT 7)
RETURNS TABLE (
  metric text,
  current_value numeric,
  previous_value numeric
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  effective_days integer := GREATEST(COALESCE(range_days, 7), 1);
  previous_cutoff timestamptz := now() - (GREATEST(COALESCE(range_days, 7), 1) * interval '1 day');
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    'total_users'::text,
    (SELECT COUNT(*)::numeric FROM auth.users),
    (SELECT COUNT(*)::numeric FROM auth.users WHERE created_at <= previous_cutoff)
  UNION ALL
  SELECT
    'active_farms'::text,
    (SELECT COUNT(*)::numeric FROM public.installations WHERE status = 'active'),
    (SELECT COUNT(*)::numeric FROM public.installations WHERE status = 'active' AND created_at <= previous_cutoff)
  UNION ALL
  SELECT
    'total_crops'::text,
    (SELECT COUNT(*)::numeric FROM public.crops),
    (SELECT COUNT(*)::numeric FROM public.crops WHERE created_at <= previous_cutoff)
  UNION ALL
  SELECT
    'total_orders'::text,
    (SELECT COUNT(*)::numeric FROM public.orders),
    (SELECT COUNT(*)::numeric FROM public.orders WHERE created_at <= previous_cutoff)
  UNION ALL
  SELECT
    'revenue'::text,
    COALESCE((SELECT SUM(total) FROM public.orders), 0),
    COALESCE((SELECT SUM(total) FROM public.orders WHERE created_at <= previous_cutoff), 0);
END; $$;

CREATE OR REPLACE FUNCTION public.admin_users_trends()
RETURNS TABLE (
  metric text,
  current_value numeric,
  previous_value numeric
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  previous_month_start timestamptz := date_trunc('month', now()) - interval '1 month';
  current_month_start timestamptz := date_trunc('month', now());
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    'total_users'::text,
    (SELECT COUNT(*)::numeric FROM auth.users),
    (SELECT COUNT(*)::numeric FROM auth.users WHERE created_at <= now() - interval '7 days')
  UNION ALL
  SELECT
    'hosts'::text,
    (SELECT COUNT(DISTINCT ur.user_id)::numeric FROM public.user_roles ur WHERE ur.role = 'grower'),
    (SELECT COUNT(DISTINCT ur.user_id)::numeric
     FROM public.user_roles ur
     JOIN auth.users u ON u.id = ur.user_id
     WHERE ur.role = 'grower'
       AND u.created_at <= now() - interval '7 days')
  UNION ALL
  SELECT
    'buyers'::text,
    (SELECT COUNT(DISTINCT ur.user_id)::numeric FROM public.user_roles ur WHERE ur.role = 'buyer'),
    (SELECT COUNT(DISTINCT ur.user_id)::numeric
     FROM public.user_roles ur
     JOIN auth.users u ON u.id = ur.user_id
     WHERE ur.role = 'buyer'
       AND u.created_at <= now() - interval '7 days')
  UNION ALL
  SELECT
    'active_this_month'::text,
    (SELECT COUNT(*)::numeric FROM auth.users WHERE last_sign_in_at >= current_month_start),
    (SELECT COUNT(*)::numeric
     FROM auth.users
     WHERE last_sign_in_at >= previous_month_start
       AND last_sign_in_at < current_month_start)
  UNION ALL
  SELECT
    'verified_users'::text,
    (SELECT COUNT(*)::numeric FROM auth.users WHERE email_confirmed_at IS NOT NULL),
    (SELECT COUNT(*)::numeric FROM auth.users WHERE email_confirmed_at IS NOT NULL AND email_confirmed_at <= now() - interval '7 days');
END; $$;

GRANT EXECUTE ON FUNCTION public.admin_dashboard_trends(integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_users_trends() TO authenticated;
