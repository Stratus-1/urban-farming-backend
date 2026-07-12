-- ============ GARDEN TASKS ============
CREATE TABLE public.garden_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  property_id UUID REFERENCES public.properties(id) ON DELETE CASCADE,
  installation_id UUID REFERENCES public.installations(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  notes TEXT,
  task_type TEXT NOT NULL DEFAULT 'general',
  status TEXT NOT NULL DEFAULT 'pending',
  due_at DATE,
  completed_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT garden_tasks_status_check CHECK (status IN ('pending', 'in_progress', 'blocked', 'done', 'cancelled')),
  CONSTRAINT garden_tasks_task_type_check CHECK (
    task_type IN ('general', 'watering', 'feeding', 'pruning', 'inspection', 'pest_control', 'harvest', 'setup')
  )
);
CREATE INDEX garden_tasks_owner_status_due_idx ON public.garden_tasks (owner_id, status, due_at);
CREATE INDEX garden_tasks_property_id_idx ON public.garden_tasks (property_id);
CREATE INDEX garden_tasks_installation_id_idx ON public.garden_tasks (installation_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.garden_tasks TO authenticated;
GRANT ALL ON public.garden_tasks TO service_role;
ALTER TABLE public.garden_tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Garden tasks visible to owner and ops" ON public.garden_tasks
  FOR SELECT TO authenticated
  USING (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Garden tasks insertable by owner and ops" ON public.garden_tasks
  FOR INSERT TO authenticated
  WITH CHECK (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Garden tasks updatable by owner and ops" ON public.garden_tasks
  FOR UPDATE TO authenticated
  USING (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Garden tasks deletable by owner and ops" ON public.garden_tasks
  FOR DELETE TO authenticated
  USING (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

-- ============ GARDEN ACTIVITY LOGS ============
CREATE TABLE public.garden_activity_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  property_id UUID REFERENCES public.properties(id) ON DELETE CASCADE,
  installation_id UUID REFERENCES public.installations(id) ON DELETE CASCADE,
  activity_type TEXT NOT NULL DEFAULT 'note',
  title TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT garden_activity_logs_activity_type_check CHECK (
    activity_type IN (
      'note',
      'planting',
      'watering',
      'feeding',
      'pruning',
      'pest_control',
      'inspection',
      'harvest',
      'share_update',
      'task_completed',
      'installation'
    )
  )
);
CREATE INDEX garden_activity_logs_owner_occurred_idx ON public.garden_activity_logs (owner_id, occurred_at DESC);
CREATE INDEX garden_activity_logs_property_id_idx ON public.garden_activity_logs (property_id);
CREATE INDEX garden_activity_logs_installation_id_idx ON public.garden_activity_logs (installation_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.garden_activity_logs TO authenticated;
GRANT ALL ON public.garden_activity_logs TO service_role;
ALTER TABLE public.garden_activity_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Garden activity visible to owner and ops" ON public.garden_activity_logs
  FOR SELECT TO authenticated
  USING (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Garden activity insertable by owner and ops" ON public.garden_activity_logs
  FOR INSERT TO authenticated
  WITH CHECK (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Garden activity updatable by owner and ops" ON public.garden_activity_logs
  FOR UPDATE TO authenticated
  USING (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  )
  WITH CHECK (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Garden activity deletable by owner and ops" ON public.garden_activity_logs
  FOR DELETE TO authenticated
  USING (
    auth.uid() = owner_id
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

-- ============ UPDATED_AT TRIGGERS ============
DROP TRIGGER IF EXISTS set_garden_tasks_updated_at ON public.garden_tasks;
CREATE TRIGGER set_garden_tasks_updated_at
BEFORE UPDATE ON public.garden_tasks
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_garden_activity_logs_updated_at ON public.garden_activity_logs;
CREATE TRIGGER set_garden_activity_logs_updated_at
BEFORE UPDATE ON public.garden_activity_logs
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============ DEFAULT GARDEN TASK SEEDING ============
CREATE OR REPLACE FUNCTION public.seed_garden_tasks_for_property()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO public.garden_tasks (
    owner_id,
    property_id,
    installation_id,
    title,
    notes,
    task_type,
    status,
    due_at
  ) VALUES
    (
      NEW.owner_id,
      NEW.id,
      NULL,
      'Water ' || NEW.label,
      'Check moisture and water the bed evenly.',
      'watering',
      'pending',
      CURRENT_DATE
    ),
    (
      NEW.owner_id,
      NEW.id,
      NULL,
      'Inspect ' || NEW.label,
      'Look for pests, wilting leaves, or dry spots.',
      'inspection',
      'pending',
      CURRENT_DATE + 1
    ),
    (
      NEW.owner_id,
      NEW.id,
      NULL,
      'Add compost to ' || NEW.label,
      'Top up organic matter before the next growth cycle.',
      'feeding',
      'pending',
      CURRENT_DATE + 3
    );

  INSERT INTO public.garden_activity_logs (
    owner_id,
    property_id,
    installation_id,
    activity_type,
    title,
    details
  ) VALUES (
    NEW.owner_id,
    NEW.id,
    NULL,
    'installation',
    NEW.label || ' added to My Gardens',
    jsonb_build_object('message', 'Starter tasks were created for this garden.')
  );

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS seed_garden_tasks_on_property_created ON public.properties;
CREATE TRIGGER seed_garden_tasks_on_property_created
AFTER INSERT ON public.properties
FOR EACH ROW EXECUTE FUNCTION public.seed_garden_tasks_for_property();

-- ============ BACKFILL EXISTING GARDENS ============
INSERT INTO public.garden_tasks (
  owner_id,
  property_id,
  installation_id,
  title,
  notes,
  task_type,
  status,
  due_at
)
SELECT
  p.owner_id,
  p.id,
  NULL,
  'Water ' || p.label,
  'Check moisture and water the bed evenly.',
  'watering',
  'pending',
  CURRENT_DATE
FROM public.properties p
WHERE NOT EXISTS (
  SELECT 1
  FROM public.garden_tasks gt
  WHERE gt.property_id = p.id
);

INSERT INTO public.garden_tasks (
  owner_id,
  property_id,
  installation_id,
  title,
  notes,
  task_type,
  status,
  due_at
)
SELECT
  p.owner_id,
  p.id,
  NULL,
  'Inspect ' || p.label,
  'Look for pests, wilting leaves, or dry spots.',
  'inspection',
  'pending',
  CURRENT_DATE + 1
FROM public.properties p
WHERE NOT EXISTS (
  SELECT 1
  FROM public.garden_tasks gt
  WHERE gt.property_id = p.id AND gt.task_type = 'inspection'
);

INSERT INTO public.garden_tasks (
  owner_id,
  property_id,
  installation_id,
  title,
  notes,
  task_type,
  status,
  due_at
)
SELECT
  p.owner_id,
  p.id,
  NULL,
  'Add compost to ' || p.label,
  'Top up organic matter before the next growth cycle.',
  'feeding',
  'pending',
  CURRENT_DATE + 3
FROM public.properties p
WHERE NOT EXISTS (
  SELECT 1
  FROM public.garden_tasks gt
  WHERE gt.property_id = p.id AND gt.task_type = 'feeding'
);
