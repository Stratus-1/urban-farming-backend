-- Keep the app and RLS aligned for admin access.
-- Add more emails here if the admin set expands.

INSERT INTO public.user_roles (user_id, role)
SELECT id, 'admin'::public.app_role
FROM auth.users
WHERE lower(email) IN ('danielmommsen2@gmail.com')
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION public.has_role(_user_id UUID, _role public.app_role)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, auth AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_roles
    WHERE user_id = _user_id
      AND role = _role
  )
  OR (
    _role = 'admin'
    AND EXISTS (
      SELECT 1
      FROM auth.users
      WHERE id = _user_id
        AND lower(email) IN ('danielmommsen2@gmail.com')
    )
  )
$$;

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  user_role public.app_role;
  user_name text;
BEGIN
  user_role := CASE
    WHEN lower(COALESCE(NEW.email, '')) IN ('danielmommsen2@gmail.com') THEN 'admin'
    ELSE COALESCE(
      NULLIF((NEW.raw_user_meta_data->>'role'), '')::public.app_role,
      'grower'
    )
  END;
  user_name := NULLIF(
    btrim(COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email, '')),
    ''
  );

  IF to_regclass('public.profiles') IS NOT NULL THEN
    INSERT INTO public.profiles (id, full_name)
    VALUES (NEW.id, user_name)
    ON CONFLICT (id) DO NOTHING;
  END IF;

  IF to_regclass('public.user_roles') IS NOT NULL THEN
    INSERT INTO public.user_roles (user_id, role)
    VALUES (NEW.id, user_role)
    ON CONFLICT DO NOTHING;
  END IF;

  IF to_regclass('public.grower_stats') IS NOT NULL THEN
    INSERT INTO public.grower_stats (user_id) VALUES (NEW.id)
    ON CONFLICT DO NOTHING;
  END IF;

  IF to_regclass('public.user_settings') IS NOT NULL THEN
    INSERT INTO public.user_settings (user_id)
    VALUES (NEW.id)
    ON CONFLICT DO NOTHING;
  END IF;

  RETURN NEW;
EXCEPTION
  WHEN undefined_table THEN
    RETURN NEW;
END; $$;

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
    COALESCE(NULLIF(btrim(p.full_name), ''), split_part(u.email, '@', 1)) AS full_name,
    u.email,
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
