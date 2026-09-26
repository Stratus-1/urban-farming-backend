-- Keep the workflow's visible current stage aligned with the audited stage record.
CREATE OR REPLACE FUNCTION public.sync_current_operational_workflow_stage()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_status TEXT;
BEGIN
  SELECT status INTO v_status
  FROM public.operational_workflows
  WHERE id = NEW.workflow_id;

  IF v_status IS NULL OR v_status IN ('completed', 'cancelled') THEN
    RETURN NEW;
  END IF;

  UPDATE public.operational_workflows
  SET current_stage = NEW.stage_key,
      status = CASE
        WHEN NEW.status = 'rejected'
          OR NEW.evidence ->> 'decision' = 'cancelled'
        THEN 'cancelled'
        ELSE status
      END,
      completed_at = CASE
        WHEN NEW.status = 'rejected'
          OR NEW.evidence ->> 'decision' = 'cancelled'
        THEN COALESCE(completed_at, now())
        ELSE completed_at
      END
  WHERE id = NEW.workflow_id;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_current_operational_workflow_stage ON public.workflow_stages;
CREATE TRIGGER sync_current_operational_workflow_stage
AFTER UPDATE OF status, evidence ON public.workflow_stages
FOR EACH ROW
EXECUTE FUNCTION public.sync_current_operational_workflow_stage();
