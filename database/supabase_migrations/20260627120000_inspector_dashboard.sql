DO $$
BEGIN
  ALTER TYPE public.app_role ADD VALUE IF NOT EXISTS 'inspector';
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE public.inspectors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  phone TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT inspectors_status_check CHECK (status IN ('active', 'inactive', 'suspended'))
);
CREATE INDEX inspectors_user_id_idx ON public.inspectors (user_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inspectors TO authenticated;
GRANT ALL ON public.inspectors TO service_role;
ALTER TABLE public.inspectors ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Inspectors visible to owner and ops" ON public.inspectors
  FOR SELECT TO authenticated
  USING (
    auth.uid() = user_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspectors insertable by owner and ops" ON public.inspectors
  FOR INSERT TO authenticated
  WITH CHECK (
    auth.uid() = user_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspectors updatable by owner and ops" ON public.inspectors
  FOR UPDATE TO authenticated
  USING (
    auth.uid() = user_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    auth.uid() = user_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspectors deletable by ops" ON public.inspectors
  FOR DELETE TO authenticated
  USING (
    public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE TABLE public.inspection_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  inspector_id UUID NOT NULL REFERENCES public.inspectors(id) ON DELETE CASCADE,
  garden_id UUID NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
  due_date DATE NOT NULL,
  priority TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'pending',
  admin_notes TEXT,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT inspection_assignments_priority_check CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
  CONSTRAINT inspection_assignments_status_check CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'flagged'))
);
CREATE INDEX inspection_assignments_inspector_due_idx ON public.inspection_assignments (inspector_id, due_date);
CREATE INDEX inspection_assignments_garden_id_idx ON public.inspection_assignments (garden_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inspection_assignments TO authenticated;
GRANT ALL ON public.inspection_assignments TO service_role;
ALTER TABLE public.inspection_assignments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Inspection assignments visible to inspector and ops" ON public.inspection_assignments
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspectors i
      WHERE i.id = inspection_assignments.inspector_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspection assignments writable by inspector and ops" ON public.inspection_assignments
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspectors i
      WHERE i.id = inspection_assignments.inspector_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.inspectors i
      WHERE i.id = inspection_assignments.inspector_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE TABLE public.inspection_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id UUID NOT NULL UNIQUE REFERENCES public.inspection_assignments(id) ON DELETE CASCADE,
  inspector_id UUID NOT NULL REFERENCES public.inspectors(id) ON DELETE CASCADE,
  garden_id UUID NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
  overall_status TEXT NOT NULL DEFAULT 'pending',
  notes TEXT,
  follow_up_required BOOLEAN NOT NULL DEFAULT false,
  gps_lat DOUBLE PRECISION,
  gps_lng DOUBLE PRECISION,
  started_at TIMESTAMPTZ,
  submitted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT inspection_reports_overall_status_check CHECK (overall_status IN ('pending', 'pass', 'warning', 'fail'))
);
CREATE INDEX inspection_reports_inspector_submitted_idx ON public.inspection_reports (inspector_id, submitted_at DESC);
CREATE INDEX inspection_reports_garden_id_idx ON public.inspection_reports (garden_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inspection_reports TO authenticated;
GRANT ALL ON public.inspection_reports TO service_role;
ALTER TABLE public.inspection_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Inspection reports visible to inspector and ops" ON public.inspection_reports
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspectors i
      WHERE i.id = inspection_reports.inspector_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspection reports writable by inspector and ops" ON public.inspection_reports
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspectors i
      WHERE i.id = inspection_reports.inspector_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.inspectors i
      WHERE i.id = inspection_reports.inspector_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE TABLE public.inspection_checklist_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID NOT NULL REFERENCES public.inspection_reports(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  item_name TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT 'na',
  comment TEXT,
  requires_photo BOOLEAN NOT NULL DEFAULT false,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT inspection_checklist_items_result_check CHECK (result IN ('pass', 'warning', 'fail', 'na'))
);
CREATE INDEX inspection_checklist_items_report_sort_idx ON public.inspection_checklist_items (report_id, sort_order);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inspection_checklist_items TO authenticated;
GRANT ALL ON public.inspection_checklist_items TO service_role;
ALTER TABLE public.inspection_checklist_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Inspection checklist visible to inspector and ops" ON public.inspection_checklist_items
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspection_reports r
      JOIN public.inspectors i ON i.id = r.inspector_id
      WHERE r.id = inspection_checklist_items.report_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspection checklist writable by inspector and ops" ON public.inspection_checklist_items
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspection_reports r
      JOIN public.inspectors i ON i.id = r.inspector_id
      WHERE r.id = inspection_checklist_items.report_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.inspection_reports r
      JOIN public.inspectors i ON i.id = r.inspector_id
      WHERE r.id = inspection_checklist_items.report_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE TABLE public.inspection_photos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID NOT NULL REFERENCES public.inspection_reports(id) ON DELETE CASCADE,
  checklist_item_id UUID REFERENCES public.inspection_checklist_items(id) ON DELETE SET NULL,
  image_url TEXT NOT NULL,
  label TEXT NOT NULL,
  photo_type TEXT NOT NULL DEFAULT 'extra',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT inspection_photos_photo_type_check CHECK (
    photo_type IN ('full_garden_view', 'crop_close_up', 'irrigation', 'problem_area', 'extra')
  )
);
CREATE INDEX inspection_photos_report_id_idx ON public.inspection_photos (report_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inspection_photos TO authenticated;
GRANT ALL ON public.inspection_photos TO service_role;
ALTER TABLE public.inspection_photos ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Inspection photos visible to inspector and ops" ON public.inspection_photos
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspection_reports r
      JOIN public.inspectors i ON i.id = r.inspector_id
      WHERE r.id = inspection_photos.report_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
CREATE POLICY "Inspection photos writable by inspector and ops" ON public.inspection_photos
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.inspection_reports r
      JOIN public.inspectors i ON i.id = r.inspector_id
      WHERE r.id = inspection_photos.report_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.inspection_reports r
      JOIN public.inspectors i ON i.id = r.inspector_id
      WHERE r.id = inspection_photos.report_id
        AND i.user_id = auth.uid()
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

DROP TRIGGER IF EXISTS set_inspectors_updated_at ON public.inspectors;
CREATE TRIGGER set_inspectors_updated_at
BEFORE UPDATE ON public.inspectors
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_inspection_assignments_updated_at ON public.inspection_assignments;
CREATE TRIGGER set_inspection_assignments_updated_at
BEFORE UPDATE ON public.inspection_assignments
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_inspection_reports_updated_at ON public.inspection_reports;
CREATE TRIGGER set_inspection_reports_updated_at
BEFORE UPDATE ON public.inspection_reports
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_inspection_checklist_items_updated_at ON public.inspection_checklist_items;
CREATE TRIGGER set_inspection_checklist_items_updated_at
BEFORE UPDATE ON public.inspection_checklist_items
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_inspection_photos_updated_at ON public.inspection_photos;
CREATE TRIGGER set_inspection_photos_updated_at
BEFORE UPDATE ON public.inspection_photos
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

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

  IF to_regclass('public.inspectors') IS NOT NULL AND user_role = 'inspector' THEN
    INSERT INTO public.inspectors (user_id, name)
    VALUES (NEW.id, COALESCE(user_name, split_part(NEW.email, '@', 1), 'Inspector'))
    ON CONFLICT (user_id) DO UPDATE
      SET name = EXCLUDED.name,
          updated_at = now();
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

CREATE OR REPLACE FUNCTION public.start_inspection_report(
  p_assignment_id UUID,
  p_gps_lat DOUBLE PRECISION DEFAULT NULL,
  p_gps_lng DOUBLE PRECISION DEFAULT NULL
)
RETURNS public.inspection_reports
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  v_inspector_id UUID;
  v_assignment public.inspection_assignments%ROWTYPE;
  v_report public.inspection_reports%ROWTYPE;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  SELECT id
  INTO v_inspector_id
  FROM public.inspectors
  WHERE user_id = auth.uid();

  IF v_inspector_id IS NULL THEN
    RAISE EXCEPTION 'Inspector profile not found';
  END IF;

  SELECT *
  INTO v_assignment
  FROM public.inspection_assignments
  WHERE id = p_assignment_id
    AND inspector_id = v_inspector_id
  FOR UPDATE;

  IF v_assignment.id IS NULL THEN
    RAISE EXCEPTION 'Assignment not found';
  END IF;

  SELECT *
  INTO v_report
  FROM public.inspection_reports
  WHERE assignment_id = p_assignment_id
  LIMIT 1;

  IF v_report.id IS NULL THEN
    INSERT INTO public.inspection_reports (
      assignment_id,
      inspector_id,
      garden_id,
      overall_status,
      notes,
      gps_lat,
      gps_lng,
      started_at
    ) VALUES (
      v_assignment.id,
      v_inspector_id,
      v_assignment.garden_id,
      'pending',
      NULL,
      p_gps_lat,
      p_gps_lng,
      now()
    )
    RETURNING * INTO v_report;

    UPDATE public.inspection_assignments
    SET status = 'in_progress',
        started_at = COALESCE(started_at, now()),
        updated_at = now()
    WHERE id = v_assignment.id;

    INSERT INTO public.inspection_checklist_items (
      report_id,
      category,
      item_name,
      result,
      comment,
      requires_photo,
      sort_order
    )
    VALUES
      (v_report.id, 'Garden condition', 'Full garden view', 'na', NULL, true, 1),
      (v_report.id, 'Crop health', 'Leaf and growth check', 'na', NULL, true, 2),
      (v_report.id, 'Irrigation status', 'Watering and delivery system', 'na', NULL, true, 3),
      (v_report.id, 'Pest and disease', 'Signs of pests or disease', 'na', NULL, true, 4),
      (v_report.id, 'Soil and beds', 'Bed structure and soil condition', 'na', NULL, false, 5),
      (v_report.id, 'Safety and access', 'Safe access and working area', 'na', NULL, false, 6),
      (v_report.id, 'User compliance', 'Site usage and access checks', 'na', NULL, false, 7),
      (v_report.id, 'Yield progress', 'Expected progress and maturity', 'na', NULL, false, 8);
  END IF;

  RETURN v_report;
END; $$;

CREATE OR REPLACE FUNCTION public.submit_inspection_report(
  p_report_id UUID,
  p_overall_status TEXT,
  p_notes TEXT DEFAULT NULL,
  p_follow_up_required BOOLEAN DEFAULT false,
  p_gps_lat DOUBLE PRECISION DEFAULT NULL,
  p_gps_lng DOUBLE PRECISION DEFAULT NULL
)
RETURNS public.inspection_reports
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  v_inspector_id UUID;
  v_report public.inspection_reports%ROWTYPE;
  v_assignment public.inspection_assignments%ROWTYPE;
  v_status TEXT;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  IF p_overall_status NOT IN ('pass', 'warning', 'fail') THEN
    RAISE EXCEPTION 'Invalid inspection status';
  END IF;

  SELECT id
  INTO v_inspector_id
  FROM public.inspectors
  WHERE user_id = auth.uid();

  IF v_inspector_id IS NULL THEN
    RAISE EXCEPTION 'Inspector profile not found';
  END IF;

  SELECT *
  INTO v_report
  FROM public.inspection_reports
  WHERE id = p_report_id
    AND inspector_id = v_inspector_id
  FOR UPDATE;

  IF v_report.id IS NULL THEN
    RAISE EXCEPTION 'Inspection report not found';
  END IF;

  SELECT *
  INTO v_assignment
  FROM public.inspection_assignments
  WHERE id = v_report.assignment_id
  FOR UPDATE;

  v_status := CASE
    WHEN p_overall_status = 'fail' THEN 'failed'
    WHEN p_follow_up_required THEN 'flagged'
    ELSE 'completed'
  END;

  UPDATE public.inspection_reports
  SET overall_status = p_overall_status,
      notes = p_notes,
      follow_up_required = p_follow_up_required,
      gps_lat = p_gps_lat,
      gps_lng = p_gps_lng,
      submitted_at = now(),
      updated_at = now()
  WHERE id = p_report_id
  RETURNING * INTO v_report;

  UPDATE public.inspection_assignments
  SET status = v_status,
      completed_at = now(),
      updated_at = now()
  WHERE id = v_assignment.id;

  RETURN v_report;
END; $$;

GRANT EXECUTE ON FUNCTION public.start_inspection_report(UUID, DOUBLE PRECISION, DOUBLE PRECISION) TO authenticated;
GRANT EXECUTE ON FUNCTION public.submit_inspection_report(UUID, TEXT, TEXT, BOOLEAN, DOUBLE PRECISION, DOUBLE PRECISION) TO authenticated;

INSERT INTO storage.buckets (id, name, public)
VALUES ('inspection-photos', 'inspection-photos', true)
ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
  IF to_regclass('storage.objects') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Inspection photos inserted by inspector and ops" ON storage.objects;
    CREATE POLICY "Inspection photos inserted by inspector and ops" ON storage.objects
      FOR INSERT TO authenticated
      WITH CHECK (
        bucket_id = 'inspection-photos'
        AND (
          split_part(name, '/', 1) = auth.uid()::text
          OR public.has_role(auth.uid(), 'operator')
          OR public.has_role(auth.uid(), 'admin')
        )
      );

    DROP POLICY IF EXISTS "Inspection photos updated by inspector and ops" ON storage.objects;
    CREATE POLICY "Inspection photos updated by inspector and ops" ON storage.objects
      FOR UPDATE TO authenticated
      USING (
        bucket_id = 'inspection-photos'
        AND (
          split_part(name, '/', 1) = auth.uid()::text
          OR public.has_role(auth.uid(), 'operator')
          OR public.has_role(auth.uid(), 'admin')
        )
      )
      WITH CHECK (
        bucket_id = 'inspection-photos'
        AND (
          split_part(name, '/', 1) = auth.uid()::text
          OR public.has_role(auth.uid(), 'operator')
          OR public.has_role(auth.uid(), 'admin')
        )
      );

    DROP POLICY IF EXISTS "Inspection photos deleted by inspector and ops" ON storage.objects;
    CREATE POLICY "Inspection photos deleted by inspector and ops" ON storage.objects
      FOR DELETE TO authenticated
      USING (
        bucket_id = 'inspection-photos'
        AND (
          split_part(name, '/', 1) = auth.uid()::text
          OR public.has_role(auth.uid(), 'operator')
          OR public.has_role(auth.uid(), 'admin')
        )
      );
  END IF;
END $$;
