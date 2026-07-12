DROP POLICY IF EXISTS "Inspectors can read assigned properties" ON public.properties;
CREATE POLICY "Inspectors can read assigned properties" ON public.properties
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspection_assignments ia
      JOIN public.inspectors i ON i.id = ia.inspector_id
      WHERE ia.garden_id = properties.id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

DROP POLICY IF EXISTS "Inspectors can read assigned garden requests" ON public.garden_requests;
CREATE POLICY "Inspectors can read assigned garden requests" ON public.garden_requests
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspection_assignments ia
      JOIN public.inspectors i ON i.id = ia.inspector_id
      WHERE ia.garden_id = garden_requests.property_id
        AND i.user_id = auth.uid()
    )
    OR auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

DROP POLICY IF EXISTS "Inspectors can read assigned owner profiles" ON public.profiles;
CREATE POLICY "Inspectors can read assigned owner profiles" ON public.profiles
  FOR SELECT TO authenticated
  USING (
    auth.uid() = id
    OR EXISTS (
      SELECT 1
      FROM public.properties p
      JOIN public.inspection_assignments ia ON ia.garden_id = p.id
      JOIN public.inspectors i ON i.id = ia.inspector_id
      WHERE p.owner_id = profiles.id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE OR REPLACE FUNCTION public.apply_inspection_request_decision(
  p_report_id UUID,
  p_request_id UUID,
  p_request_status public.garden_request_status,
  p_notes TEXT DEFAULT NULL
)
RETURNS public.garden_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  v_inspector_id UUID;
  v_request public.garden_requests%ROWTYPE;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  IF p_request_status NOT IN (
    'accepted'::public.garden_request_status,
    'needing_implements'::public.garden_request_status,
    'rejected'::public.garden_request_status
  ) THEN
    RAISE EXCEPTION 'Invalid request decision status';
  END IF;

  SELECT id
  INTO v_inspector_id
  FROM public.inspectors
  WHERE user_id = auth.uid();

  IF v_inspector_id IS NULL THEN
    RAISE EXCEPTION 'Inspector profile not found';
  END IF;

  SELECT gr.*
  INTO v_request
  FROM public.garden_requests gr
  JOIN public.inspection_assignments ia ON ia.garden_id = gr.property_id
  JOIN public.inspection_reports r ON r.assignment_id = ia.id
  WHERE gr.id = p_request_id
    AND r.id = p_report_id
    AND r.inspector_id = v_inspector_id
  FOR UPDATE OF gr;

  IF v_request.id IS NULL THEN
    RAISE EXCEPTION 'Assigned garden request not found';
  END IF;

  UPDATE public.garden_requests
  SET status = p_request_status,
      admin_notes = NULLIF(p_notes, ''),
      reviewed_by = auth.uid(),
      reviewed_at = now(),
      updated_at = now()
  WHERE id = p_request_id
  RETURNING * INTO v_request;

  RETURN v_request;
END;
$$;

GRANT EXECUTE ON FUNCTION public.apply_inspection_request_decision(
  UUID,
  UUID,
  public.garden_request_status,
  TEXT
) TO authenticated;
