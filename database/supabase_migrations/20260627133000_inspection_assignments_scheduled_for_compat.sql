ALTER TABLE public.inspection_assignments
  ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;

UPDATE public.inspection_assignments
SET scheduled_for = due_date::timestamptz
WHERE scheduled_for IS NULL;

ALTER TABLE public.inspection_assignments
  ALTER COLUMN scheduled_for SET NOT NULL;

CREATE OR REPLACE FUNCTION public.sync_inspection_assignment_schedule()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  IF NEW.scheduled_for IS NULL AND NEW.due_date IS NOT NULL THEN
    NEW.scheduled_for := NEW.due_date::timestamptz;
  END IF;

  IF NEW.due_date IS NULL AND NEW.scheduled_for IS NOT NULL THEN
    NEW.due_date := NEW.scheduled_for::date;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    IF NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for THEN
      NEW.due_date := NEW.scheduled_for::date;
    ELSIF NEW.due_date IS DISTINCT FROM OLD.due_date THEN
      NEW.scheduled_for := NEW.due_date::timestamptz;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_inspection_assignment_schedule ON public.inspection_assignments;
CREATE TRIGGER sync_inspection_assignment_schedule
BEFORE INSERT OR UPDATE ON public.inspection_assignments
FOR EACH ROW EXECUTE FUNCTION public.sync_inspection_assignment_schedule();

CREATE INDEX IF NOT EXISTS inspection_assignments_inspector_scheduled_idx
ON public.inspection_assignments (inspector_id, scheduled_for);
