CREATE TABLE IF NOT EXISTS public.assessment_leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name TEXT NOT NULL,
  email VARCHAR(255) NOT NULL,
  phone TEXT,
  suburb TEXT NOT NULL,
  city TEXT,
  space_type TEXT NOT NULL CHECK (
    space_type IN (
      'backyard',
      'front_yard',
      'balcony',
      'patio',
      'courtyard',
      'rooftop',
      'windowsill',
      'indoor',
      'vertical_wall',
      'community_plot',
      'other'
    )
  ),
  available_space_m2 NUMERIC(10,2),
  sunlight_hours NUMERIC(4,1),
  water_access TEXT NOT NULL DEFAULT 'unknown' CHECK (
    water_access IN ('none', 'limited', 'reliable', 'unknown')
  ),
  interest_type TEXT NOT NULL DEFAULT 'not_sure' CHECK (
    interest_type IN (
      'personal_harvest',
      'learn_to_grow',
      'community_contribution',
      'payout',
      'buyer_supply',
      'not_sure'
    )
  ),
  message TEXT,
  source TEXT NOT NULL DEFAULT 'assessment_page',
  status TEXT NOT NULL DEFAULT 'new' CHECK (
    status IN ('new', 'contacted', 'scheduled', 'assessed', 'not_viable', 'closed')
  ),
  admin_notes TEXT,
  reviewed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS assessment_leads_status_created_idx
  ON public.assessment_leads (status, created_at DESC);
CREATE INDEX IF NOT EXISTS assessment_leads_suburb_idx
  ON public.assessment_leads (suburb);
CREATE INDEX IF NOT EXISTS assessment_leads_email_idx
  ON public.assessment_leads (email);

DROP TRIGGER IF EXISTS set_assessment_leads_updated_at ON public.assessment_leads;
CREATE TRIGGER set_assessment_leads_updated_at
BEFORE UPDATE ON public.assessment_leads
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
