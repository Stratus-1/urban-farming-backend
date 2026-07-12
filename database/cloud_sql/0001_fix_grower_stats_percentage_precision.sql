-- Percentage values include 100.00, which does not fit NUMERIC(4,2).
-- NUMERIC(5,2) supports the complete 0.00-100.00 domain.
ALTER TABLE IF EXISTS public.grower_stats
  ALTER COLUMN reliability_score TYPE NUMERIC(5,2),
  ALTER COLUMN crop_success_rate TYPE NUMERIC(5,2);
