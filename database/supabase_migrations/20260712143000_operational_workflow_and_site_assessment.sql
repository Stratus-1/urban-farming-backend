-- One auditable resident-to-impact workflow, plus structured inspector assessment data.
ALTER TABLE public.inspection_reports
  ADD COLUMN IF NOT EXISTS sunlight_hours NUMERIC(4,1),
  ADD COLUMN IF NOT EXISTS water_access TEXT,
  ADD COLUMN IF NOT EXISTS usable_space_m2 NUMERIC(10,2),
  ADD COLUMN IF NOT EXISTS installation_types TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS measurements JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS risks JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS suitability_score INTEGER,
  ADD COLUMN IF NOT EXISTS score_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS suitability_band TEXT,
  ADD COLUMN IF NOT EXISTS recommended_crops TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS recommended_infrastructure TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS assessment_status TEXT NOT NULL DEFAULT 'draft';

ALTER TABLE public.inspection_reports
  DROP CONSTRAINT IF EXISTS inspection_reports_water_access_check,
  ADD CONSTRAINT inspection_reports_water_access_check
    CHECK (water_access IS NULL OR water_access IN ('none', 'limited', 'reliable')),
  DROP CONSTRAINT IF EXISTS inspection_reports_score_check,
  ADD CONSTRAINT inspection_reports_score_check
    CHECK (suitability_score IS NULL OR suitability_score BETWEEN 0 AND 100),
  DROP CONSTRAINT IF EXISTS inspection_reports_band_check,
  ADD CONSTRAINT inspection_reports_band_check
    CHECK (suitability_band IS NULL OR suitability_band IN ('suitable', 'conditional', 'not_suitable')),
  DROP CONSTRAINT IF EXISTS inspection_reports_assessment_status_check,
  ADD CONSTRAINT inspection_reports_assessment_status_check
    CHECK (assessment_status IN ('draft', 'submitted_for_approval', 'approved', 'revision_requested', 'rejected'));

CREATE TABLE IF NOT EXISTS public.operational_workflows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  garden_request_id UUID NOT NULL UNIQUE REFERENCES public.garden_requests(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  current_stage TEXT NOT NULL DEFAULT 'resident_signup',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_hold', 'completed', 'cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.workflow_stages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id UUID NOT NULL REFERENCES public.operational_workflows(id) ON DELETE CASCADE,
  stage_key TEXT NOT NULL,
  sequence_no INTEGER NOT NULL,
  owner_role TEXT NOT NULL,
  owner_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'not_started' CHECK (
    status IN ('not_started', 'ready', 'in_progress', 'blocked', 'submitted', 'approved', 'completed', 'rejected', 'skipped')
  ),
  required_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  completion_criteria TEXT NOT NULL,
  next_action TEXT NOT NULL,
  started_at TIMESTAMPTZ,
  submitted_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (workflow_id, stage_key),
  UNIQUE (workflow_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS public.workflow_stage_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  stage_id UUID NOT NULL REFERENCES public.workflow_stages(id) ON DELETE CASCADE,
  actor_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  evidence_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workflow_stages_workflow_sequence_idx
  ON public.workflow_stages (workflow_id, sequence_no);
CREATE INDEX IF NOT EXISTS workflow_stage_events_stage_created_idx
  ON public.workflow_stage_events (stage_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.seed_operational_workflow(p_request_id UUID, p_owner_id UUID)
RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_workflow_id UUID;
BEGIN
  INSERT INTO public.operational_workflows (garden_request_id, owner_id)
  VALUES (p_request_id, p_owner_id)
  ON CONFLICT (garden_request_id) DO UPDATE SET owner_id = EXCLUDED.owner_id
  RETURNING id INTO v_workflow_id;

  INSERT INTO public.workflow_stages
    (workflow_id, stage_key, sequence_no, owner_role, status, required_evidence, completion_criteria, next_action)
  VALUES
    (v_workflow_id,'resident_signup',1,'resident','completed','["verified resident identity"]','Resident account exists and identity is verified.','Capture address and property details.'),
    (v_workflow_id,'property_details',2,'resident','in_progress','["address","property coordinates","available space"]','Address and minimum property facts are complete.','Run preliminary suitability assessment.'),
    (v_workflow_id,'preliminary_assessment',3,'system','not_started','["property details","pre-screen result"]','Automated pre-screen has a recorded result.','Assign and schedule an inspector.'),
    (v_workflow_id,'inspector_visit',4,'inspector','not_started','["GPS check-in","site photographs","measurements"]','Inspector completes the on-site assessment.','Generate the site score.'),
    (v_workflow_id,'site_score',5,'inspector','not_started','["score breakdown","risk flags"]','A deterministic 0-100 suitability score is stored.','Recommend crops and infrastructure.'),
    (v_workflow_id,'garden_recommendation',6,'inspector','not_started','["crop recommendations","infrastructure recommendations"]','At least one crop and infrastructure recommendation is submitted.','Submit for operations approval.'),
    (v_workflow_id,'approval',7,'admin','not_started','["inspection report","approval decision"]','An authorised reviewer approves, rejects, or requests revision.','Schedule installation when approved.'),
    (v_workflow_id,'installation',8,'operator','not_started','["installation checklist","completion photos"]','Approved infrastructure is installed and signed off.','Allocate crops.'),
    (v_workflow_id,'crop_allocation',9,'operator','not_started','["crop batch","planting plan"]','Crops are allocated to the installed garden.','Generate maintenance tasks.'),
    (v_workflow_id,'maintenance_tasks',10,'grower','not_started','["task completion logs","exception evidence"]','Required recurring care tasks are current.','Record harvest when produce is ready.'),
    (v_workflow_id,'harvest_recording',11,'grower','not_started','["crop","weight","harvest date"]','A verified harvest record exists.','Record collection or household use.'),
    (v_workflow_id,'produce_disposition',12,'resident','not_started','["collection receipt or household-use record"]','All harvested produce has a recorded destination.','Calculate Green Points and impact.'),
    (v_workflow_id,'impact_reporting',13,'system','not_started','["Green Points transaction","impact metrics"]','Points and impact metrics reconcile to verified activity.','Continue the next growing cycle.')
  ON CONFLICT (workflow_id, stage_key) DO NOTHING;
  RETURN v_workflow_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_garden_request_workflow()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  PERFORM public.seed_operational_workflow(NEW.id, NEW.owner_id);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS create_garden_request_workflow ON public.garden_requests;
CREATE TRIGGER create_garden_request_workflow
AFTER INSERT ON public.garden_requests
FOR EACH ROW EXECUTE FUNCTION public.create_garden_request_workflow();

SELECT public.seed_operational_workflow(id, owner_id) FROM public.garden_requests;

ALTER TABLE public.operational_workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workflow_stage_events ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON public.operational_workflows, public.workflow_stages, public.workflow_stage_events TO authenticated;
GRANT INSERT, UPDATE ON public.workflow_stages, public.workflow_stage_events TO authenticated;
GRANT ALL ON public.operational_workflows, public.workflow_stages, public.workflow_stage_events TO service_role;

CREATE POLICY "Workflow visible to resident and delivery team" ON public.operational_workflows
FOR SELECT TO authenticated USING (
  owner_id = auth.uid() OR public.has_role(auth.uid(),'inspector') OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin')
);
CREATE POLICY "Stages visible through workflow" ON public.workflow_stages
FOR SELECT TO authenticated USING (
  EXISTS (SELECT 1 FROM public.operational_workflows w WHERE w.id = workflow_id AND (w.owner_id = auth.uid() OR public.has_role(auth.uid(),'inspector') OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin')))
);
CREATE POLICY "Delivery team updates stages" ON public.workflow_stages
FOR UPDATE TO authenticated USING (
  public.has_role(auth.uid(),'inspector') OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin')
) WITH CHECK (
  public.has_role(auth.uid(),'inspector') OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin')
);
CREATE POLICY "Stage events visible through stage" ON public.workflow_stage_events
FOR SELECT TO authenticated USING (
  EXISTS (SELECT 1 FROM public.workflow_stages s JOIN public.operational_workflows w ON w.id=s.workflow_id WHERE s.id=stage_id AND (w.owner_id=auth.uid() OR public.has_role(auth.uid(),'inspector') OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin')))
);
CREATE POLICY "Delivery team records stage events" ON public.workflow_stage_events
FOR INSERT TO authenticated WITH CHECK (
  public.has_role(auth.uid(),'inspector') OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin')
);

DROP TRIGGER IF EXISTS set_operational_workflows_updated_at ON public.operational_workflows;
CREATE TRIGGER set_operational_workflows_updated_at BEFORE UPDATE ON public.operational_workflows
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS set_workflow_stages_updated_at ON public.workflow_stages;
CREATE TRIGGER set_workflow_stages_updated_at BEFORE UPDATE ON public.workflow_stages
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
