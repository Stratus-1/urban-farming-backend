-- Persist buyer onboarding fields on the existing owner-scoped profile record.
ALTER TABLE public.buyer_profiles
  ADD COLUMN IF NOT EXISTS contact_name TEXT,
  ADD COLUMN IF NOT EXISTS organization_type TEXT,
  ADD COLUMN IF NOT EXISTS preferred_channel TEXT,
  ADD COLUMN IF NOT EXISTS operating_region TEXT,
  ADD COLUMN IF NOT EXISTS target_integration TEXT;
