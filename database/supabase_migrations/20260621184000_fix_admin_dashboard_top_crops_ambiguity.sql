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

GRANT EXECUTE ON FUNCTION public.admin_dashboard_top_crops(integer) TO authenticated;
