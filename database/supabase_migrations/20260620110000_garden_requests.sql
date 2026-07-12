-- ============ GARDEN REQUESTS ============
CREATE TYPE public.garden_request_status AS ENUM (
  'submitted',
  'inspection_scheduled',
  'accepted',
  'needing_implements',
  'implements_installed',
  'seeds',
  'final_install',
  'live',
  'rejected',
  'cancelled'
);

CREATE TABLE public.garden_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  property_id UUID UNIQUE REFERENCES public.properties(id) ON DELETE SET NULL,
  label TEXT NOT NULL,
  city TEXT,
  address TEXT,
  available_space_m2 NUMERIC(8,2),
  sunlight_hours NUMERIC(4,1),
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  status public.garden_request_status NOT NULL DEFAULT 'submitted',
  admin_notes TEXT,
  reviewed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON public.garden_requests TO authenticated;
GRANT ALL ON public.garden_requests TO service_role;
ALTER TABLE public.garden_requests ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Garden requests visible to owner and ops" ON public.garden_requests FOR SELECT TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

CREATE POLICY "Garden requests insertable by owner" ON public.garden_requests FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = owner_id);

CREATE POLICY "Garden requests manageable by ops" ON public.garden_requests FOR UPDATE TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))
  WITH CHECK (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

CREATE POLICY "Garden requests deletable by ops" ON public.garden_requests FOR DELETE TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
