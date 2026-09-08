ALTER TABLE IF EXISTS public.assessment_leads
  DROP CONSTRAINT IF EXISTS assessment_leads_status_check;

ALTER TABLE IF EXISTS public.assessment_leads
  ADD CONSTRAINT assessment_leads_status_check
  CHECK (status IN ('new', 'contacted', 'scheduled', 'assessed', 'converted', 'not_viable', 'closed'));
