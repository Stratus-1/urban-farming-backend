-- Align the RPC return shape with auth.users.email, which can be varchar(255)
-- in some Supabase setups. Returning it as explicit text avoids 42804 errors.

CREATE OR REPLACE FUNCTION public.admin_users_directory()
RETURNS TABLE (
  id uuid,
  full_name text,
  email text,
  role public.app_role,
  status text,
  join_date timestamptz,
  last_active timestamptz,
  location text,
  avatar_url text,
  verified boolean,
  active_this_month boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
#variable_conflict use_column
BEGIN
  IF auth.uid() IS NULL OR NOT (
    public.has_role(auth.uid(), 'admin')
    OR public.has_role(auth.uid(), 'operator')
  ) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  RETURN QUERY
  SELECT
    u.id,
    COALESCE(NULLIF(btrim(p.full_name), ''), split_part(u.email::text, '@', 1)) AS full_name,
    u.email::text AS email,
    COALESCE(ur.user_role, 'grower'::public.app_role) AS role,
    CASE
      WHEN u.email_confirmed_at IS NULL THEN 'Pending Approval'
      WHEN u.last_sign_in_at IS NULL THEN 'Inactive'
      WHEN u.last_sign_in_at >= now() - interval '30 days' THEN 'Verified'
      ELSE 'Inactive'
    END AS status,
    u.created_at AS join_date,
    u.last_sign_in_at AS last_active,
    COALESCE(NULLIF(btrim(p.city), ''), NULLIF(btrim(bp.city), ''), 'Unknown') AS location,
    p.avatar_url,
    u.email_confirmed_at IS NOT NULL AS verified,
    u.last_sign_in_at >= date_trunc('month', now()) AS active_this_month
  FROM auth.users u
  LEFT JOIN public.profiles p ON p.id = u.id
  LEFT JOIN public.buyer_profiles bp ON bp.user_id = u.id
  LEFT JOIN LATERAL (
    SELECT ur2.role AS user_role
    FROM public.user_roles ur2
    WHERE ur2.user_id = u.id
    ORDER BY
      CASE ur2.role
        WHEN 'admin' THEN 1
        WHEN 'operator' THEN 2
        WHEN 'buyer' THEN 3
        ELSE 4
      END
    LIMIT 1
  ) ur ON TRUE
  ORDER BY u.created_at DESC;
END; $$;

GRANT EXECUTE ON FUNCTION public.admin_users_directory() TO authenticated;
