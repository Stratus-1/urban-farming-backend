CREATE TABLE public.inspector_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT NOT NULL,
  city TEXT NOT NULL,
  region TEXT NOT NULL,
  "current_role" TEXT NOT NULL,
  years_growing_experience INTEGER NOT NULL CHECK (years_growing_experience BETWEEN 0 AND 80),
  growing_systems JSONB NOT NULL DEFAULT '[]'::jsonb,
  inspection_experience TEXT NOT NULL,
  crop_and_site_knowledge TEXT NOT NULL,
  availability TEXT NOT NULL CHECK (availability IN ('weekdays', 'weekends', 'flexible')),
  transport_access TEXT NOT NULL CHECK (transport_access IN ('own_vehicle', 'public_transport', 'mixed', 'limited')),
  smartphone_access BOOLEAN NOT NULL DEFAULT false,
  gps_and_photo_ready BOOLEAN NOT NULL DEFAULT false,
  safety_ready BOOLEAN NOT NULL DEFAULT false,
  motivation TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'under_review', 'approved', 'rejected')),
  admin_notes TEXT,
  reviewed_by UUID REFERENCES auth.users(id),
  reviewed_at TIMESTAMPTZ,
  source TEXT NOT NULL DEFAULT 'inspector_application',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX inspector_applications_status_created_idx
  ON public.inspector_applications (status, created_at DESC);

GRANT INSERT ON public.inspector_applications TO anon, authenticated;
GRANT SELECT, UPDATE ON public.inspector_applications TO authenticated;
GRANT ALL ON public.inspector_applications TO service_role;
ALTER TABLE public.inspector_applications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can submit inspector applications"
  ON public.inspector_applications FOR INSERT TO anon, authenticated
  WITH CHECK (true);

CREATE POLICY "Admins can review inspector applications"
  ON public.inspector_applications FOR SELECT TO authenticated
  USING (public.has_role(auth.uid(), 'admin') OR public.has_role(auth.uid(), 'operator'));

CREATE POLICY "Admins can update inspector applications"
  ON public.inspector_applications FOR UPDATE TO authenticated
  USING (public.has_role(auth.uid(), 'admin') OR public.has_role(auth.uid(), 'operator'))
  WITH CHECK (public.has_role(auth.uid(), 'admin') OR public.has_role(auth.uid(), 'operator'));
