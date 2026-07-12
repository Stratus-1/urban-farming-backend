-- ============ GROWER DASHBOARD CONTENT ============
CREATE TABLE public.grower_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT,
  event_type TEXT NOT NULL DEFAULT 'workshop',
  delivery_mode TEXT NOT NULL DEFAULT 'online',
  location TEXT,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  registration_url TEXT,
  capacity INT,
  status TEXT NOT NULL DEFAULT 'scheduled',
  visible BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT grower_events_status_check CHECK (status IN ('draft', 'scheduled', 'open', 'full', 'cancelled', 'completed')),
  CONSTRAINT grower_events_delivery_mode_check CHECK (delivery_mode IN ('online', 'in_person', 'hybrid'))
);
CREATE INDEX grower_events_visible_starts_idx ON public.grower_events (visible, starts_at);
GRANT SELECT ON public.grower_events TO anon, authenticated;
GRANT INSERT, UPDATE, DELETE ON public.grower_events TO authenticated;
GRANT ALL ON public.grower_events TO service_role;
ALTER TABLE public.grower_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Published grower events are readable" ON public.grower_events
  FOR SELECT TO anon, authenticated
  USING (visible = TRUE AND status <> 'draft');

CREATE POLICY "Ops manage grower events" ON public.grower_events
  FOR ALL TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.grower_event_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES public.grower_events(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'registered',
  registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  attended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(event_id, user_id),
  CONSTRAINT grower_event_registrations_status_check CHECK (status IN ('registered', 'waitlisted', 'cancelled', 'attended', 'completed'))
);
CREATE INDEX grower_event_registrations_user_status_idx ON public.grower_event_registrations (user_id, status);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.grower_event_registrations TO authenticated;
GRANT ALL ON public.grower_event_registrations TO service_role;
ALTER TABLE public.grower_event_registrations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Growers read own event registrations" ON public.grower_event_registrations
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id OR public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE POLICY "Growers register themselves for events" ON public.grower_event_registrations
  FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Growers update own event registrations" ON public.grower_event_registrations
  FOR UPDATE TO authenticated
  USING (auth.uid() = user_id OR public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (auth.uid() = user_id OR public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.grower_dashboard_tips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  icon_key TEXT NOT NULL DEFAULT 'leaf',
  href TEXT,
  read_time_minutes INT NOT NULL DEFAULT 2,
  priority INT NOT NULL DEFAULT 100,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX grower_dashboard_tips_active_priority_idx ON public.grower_dashboard_tips (active, priority);
GRANT SELECT ON public.grower_dashboard_tips TO anon, authenticated;
GRANT INSERT, UPDATE, DELETE ON public.grower_dashboard_tips TO authenticated;
GRANT ALL ON public.grower_dashboard_tips TO service_role;
ALTER TABLE public.grower_dashboard_tips ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Active grower dashboard tips are readable" ON public.grower_dashboard_tips
  FOR SELECT TO anon, authenticated
  USING (active = TRUE);

CREATE POLICY "Ops manage grower dashboard tips" ON public.grower_dashboard_tips
  FOR ALL TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.community_spotlights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  action_label TEXT NOT NULL DEFAULT 'Read story',
  href TEXT,
  avatar_label TEXT,
  image_url TEXT,
  priority INT NOT NULL DEFAULT 100,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX community_spotlights_active_priority_idx ON public.community_spotlights (active, priority);
GRANT SELECT ON public.community_spotlights TO anon, authenticated;
GRANT INSERT, UPDATE, DELETE ON public.community_spotlights TO authenticated;
GRANT ALL ON public.community_spotlights TO service_role;
ALTER TABLE public.community_spotlights ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Active community spotlights are readable" ON public.community_spotlights
  FOR SELECT TO anon, authenticated
  USING (
    active = TRUE
    AND (starts_at IS NULL OR starts_at <= now())
    AND (ends_at IS NULL OR ends_at >= now())
  );

CREATE POLICY "Ops manage community spotlights" ON public.community_spotlights
  FOR ALL TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.grower_impact_factors (
  metric_key TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  multiplier NUMERIC(12,4) NOT NULL,
  unit TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT ON public.grower_impact_factors TO authenticated;
GRANT INSERT, UPDATE, DELETE ON public.grower_impact_factors TO authenticated;
GRANT ALL ON public.grower_impact_factors TO service_role;
ALTER TABLE public.grower_impact_factors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Growers read active impact factors" ON public.grower_impact_factors
  FOR SELECT TO authenticated
  USING (active = TRUE);

CREATE POLICY "Ops manage impact factors" ON public.grower_impact_factors
  FOR ALL TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.green_point_rules (
  activity_type TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  points INT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT ON public.green_point_rules TO authenticated;
GRANT INSERT, UPDATE, DELETE ON public.green_point_rules TO authenticated;
GRANT ALL ON public.green_point_rules TO service_role;
ALTER TABLE public.green_point_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Growers read active point rules" ON public.green_point_rules
  FOR SELECT TO authenticated
  USING (active = TRUE);

CREATE POLICY "Ops manage point rules" ON public.green_point_rules
  FOR ALL TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.green_point_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,
  source_id UUID,
  points INT NOT NULL,
  description TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX green_point_transactions_source_idx
  ON public.green_point_transactions (source_type, source_id)
  WHERE source_id IS NOT NULL;
CREATE INDEX green_point_transactions_owner_occurred_idx
  ON public.green_point_transactions (owner_id, occurred_at DESC);
GRANT SELECT ON public.green_point_transactions TO authenticated;
GRANT ALL ON public.green_point_transactions TO service_role;
ALTER TABLE public.green_point_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Growers read own green point transactions" ON public.green_point_transactions
  FOR SELECT TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

DROP TRIGGER IF EXISTS set_grower_events_updated_at ON public.grower_events;
CREATE TRIGGER set_grower_events_updated_at
BEFORE UPDATE ON public.grower_events
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_grower_event_registrations_updated_at ON public.grower_event_registrations;
CREATE TRIGGER set_grower_event_registrations_updated_at
BEFORE UPDATE ON public.grower_event_registrations
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_grower_dashboard_tips_updated_at ON public.grower_dashboard_tips;
CREATE TRIGGER set_grower_dashboard_tips_updated_at
BEFORE UPDATE ON public.grower_dashboard_tips
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_community_spotlights_updated_at ON public.community_spotlights;
CREATE TRIGGER set_community_spotlights_updated_at
BEFORE UPDATE ON public.community_spotlights
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_grower_impact_factors_updated_at ON public.grower_impact_factors;
CREATE TRIGGER set_grower_impact_factors_updated_at
BEFORE UPDATE ON public.grower_impact_factors
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_green_point_rules_updated_at ON public.green_point_rules;
CREATE TRIGGER set_green_point_rules_updated_at
BEFORE UPDATE ON public.green_point_rules
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION public.record_green_points_for_activity_log()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  awarded_points integer;
BEGIN
  SELECT points INTO awarded_points
  FROM public.green_point_rules
  WHERE activity_type = NEW.activity_type
    AND active = TRUE;

  IF awarded_points IS NULL THEN
    SELECT points INTO awarded_points
    FROM public.green_point_rules
    WHERE activity_type = 'note'
      AND active = TRUE;
  END IF;

  IF COALESCE(awarded_points, 0) > 0 THEN
    INSERT INTO public.green_point_transactions (
      owner_id,
      source_type,
      source_id,
      points,
      description,
      occurred_at,
      metadata
    ) VALUES (
      NEW.owner_id,
      'garden_activity_log',
      NEW.id,
      awarded_points,
      NEW.title,
      NEW.occurred_at,
      jsonb_build_object('activity_type', NEW.activity_type)
    )
    ON CONFLICT (source_type, source_id) WHERE source_id IS NOT NULL
    DO UPDATE SET
      points = EXCLUDED.points,
      description = EXCLUDED.description,
      occurred_at = EXCLUDED.occurred_at,
      metadata = EXCLUDED.metadata;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS record_green_points_on_activity_log ON public.garden_activity_logs;
CREATE TRIGGER record_green_points_on_activity_log
AFTER INSERT OR UPDATE OF activity_type, title, occurred_at ON public.garden_activity_logs
FOR EACH ROW EXECUTE FUNCTION public.record_green_points_for_activity_log();

CREATE OR REPLACE FUNCTION public.record_green_points_for_event_registration()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  awarded_points integer;
  event_title text;
BEGIN
  IF NEW.status NOT IN ('attended', 'completed') THEN
    RETURN NEW;
  END IF;

  SELECT points INTO awarded_points
  FROM public.green_point_rules
  WHERE activity_type = 'workshop'
    AND active = TRUE;

  SELECT title INTO event_title
  FROM public.grower_events
  WHERE id = NEW.event_id;

  IF COALESCE(awarded_points, 0) > 0 THEN
    INSERT INTO public.green_point_transactions (
      owner_id,
      source_type,
      source_id,
      points,
      description,
      occurred_at,
      metadata
    ) VALUES (
      NEW.user_id,
      'grower_event_registration',
      NEW.id,
      awarded_points,
      COALESCE(event_title, 'Workshop attended'),
      COALESCE(NEW.attended_at, NEW.updated_at, now()),
      jsonb_build_object('event_id', NEW.event_id, 'status', NEW.status)
    )
    ON CONFLICT (source_type, source_id) WHERE source_id IS NOT NULL
    DO UPDATE SET
      points = EXCLUDED.points,
      description = EXCLUDED.description,
      occurred_at = EXCLUDED.occurred_at,
      metadata = EXCLUDED.metadata;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS record_green_points_on_event_registration ON public.grower_event_registrations;
CREATE TRIGGER record_green_points_on_event_registration
AFTER INSERT OR UPDATE OF status, attended_at ON public.grower_event_registrations
FOR EACH ROW EXECUTE FUNCTION public.record_green_points_for_event_registration();

-- ============ SEED DASHBOARD CONTENT + RULES ============
INSERT INTO public.grower_dashboard_tips (slug, title, description, icon_key, href, read_time_minutes, priority)
VALUES
  ('morning-watering', 'Water early in the morning.', 'Early watering reduces evaporation and improves absorption in warm weather.', 'leaf', '/resources/watering-calculator', 2, 10),
  ('compost-kitchen-waste', 'Compost kitchen waste.', 'Turn scraps into soil nutrition and reduce household waste at the same time.', 'sprout', '/resources', 3, 20),
  ('track-sun-exposure', 'Track sun exposure.', 'Most vegetables need consistent sunlight to stay productive.', 'shield', '/resources/plant-spacing', 2, 30)
ON CONFLICT (slug) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  icon_key = EXCLUDED.icon_key,
  href = EXCLUDED.href,
  read_time_minutes = EXCLUDED.read_time_minutes,
  priority = EXCLUDED.priority,
  active = TRUE;

INSERT INTO public.grower_events (slug, title, description, event_type, delivery_mode, location, starts_at, ends_at, status, visible)
VALUES
  ('urban-gardening-101', 'Urban Gardening 101', 'Practical basics for getting a small-space garden productive.', 'workshop', 'online', 'Online', date_trunc('day', now()) + interval '7 days 10 hours', date_trunc('day', now()) + interval '7 days 11 hours 30 minutes', 'open', TRUE),
  ('composting-made-easy', 'Composting Made Easy', 'Build soil nutrition from household scraps and low-cost inputs.', 'workshop', 'in_person', 'Community Center', date_trunc('day', now()) + interval '12 days 11 hours', date_trunc('day', now()) + interval '12 days 12 hours 30 minutes', 'open', TRUE),
  ('community-garden-meetup', 'Community Garden Meetup', 'Meet local growers and compare what is working this season.', 'meetup', 'in_person', 'Greenview Park', date_trunc('day', now()) + interval '20 days 16 hours', date_trunc('day', now()) + interval '20 days 18 hours', 'open', TRUE)
ON CONFLICT (slug) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  event_type = EXCLUDED.event_type,
  delivery_mode = EXCLUDED.delivery_mode,
  location = EXCLUDED.location,
  status = EXCLUDED.status,
  visible = EXCLUDED.visible;

INSERT INTO public.community_spotlights (slug, title, description, action_label, href, avatar_label, priority, active)
VALUES
  ('community-grower-maya', 'Community grower story', 'A featured grower turning a small urban space into a more productive food source.', 'Read story', '/community', 'UF', 10, TRUE)
ON CONFLICT (slug) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  action_label = EXCLUDED.action_label,
  href = EXCLUDED.href,
  avatar_label = EXCLUDED.avatar_label,
  priority = EXCLUDED.priority,
  active = TRUE;

INSERT INTO public.grower_impact_factors (metric_key, label, multiplier, unit)
VALUES
  ('water_saved_l_per_kg', 'Water Saved', 26, 'L'),
  ('co2_reduced_kg_per_kg', 'CO2 Reduced', 1.2, 'kg'),
  ('lives_impacted_per_garden', 'Lives Impacted', 1, 'people'),
  ('lives_impacted_per_workshop', 'Lives Impacted', 1, 'people')
ON CONFLICT (metric_key) DO UPDATE SET
  label = EXCLUDED.label,
  multiplier = EXCLUDED.multiplier,
  unit = EXCLUDED.unit,
  active = TRUE;

INSERT INTO public.green_point_rules (activity_type, label, points)
VALUES
  ('watering', 'Watering recorded', 10),
  ('feeding', 'Feeding recorded', 15),
  ('pruning', 'Pruning recorded', 15),
  ('inspection', 'Inspection recorded', 10),
  ('pest_control', 'Pest check recorded', 15),
  ('harvest', 'Harvest recorded', 25),
  ('planting', 'Planting recorded', 50),
  ('installation', 'Garden installed', 50),
  ('task_completed', 'Task completed', 20),
  ('share_update', 'Community update shared', 10),
  ('workshop', 'Workshop attended', 30),
  ('note', 'Garden note added', 5)
ON CONFLICT (activity_type) DO UPDATE SET
  label = EXCLUDED.label,
  points = EXCLUDED.points,
  active = TRUE;

INSERT INTO public.green_point_transactions (
  owner_id,
  source_type,
  source_id,
  points,
  description,
  occurred_at,
  metadata
)
SELECT
  log.owner_id,
  'garden_activity_log',
  log.id,
  COALESCE(rule.points, fallback.points, 0),
  log.title,
  log.occurred_at,
  jsonb_build_object('activity_type', log.activity_type)
FROM public.garden_activity_logs log
LEFT JOIN public.green_point_rules rule
  ON rule.activity_type = log.activity_type
  AND rule.active = TRUE
LEFT JOIN public.green_point_rules fallback
  ON fallback.activity_type = 'note'
  AND fallback.active = TRUE
WHERE COALESCE(rule.points, fallback.points, 0) > 0
ON CONFLICT (source_type, source_id) WHERE source_id IS NOT NULL DO NOTHING;

INSERT INTO public.green_point_transactions (
  owner_id,
  source_type,
  source_id,
  points,
  description,
  occurred_at,
  metadata
)
SELECT
  h.owner_id,
  'harvest',
  h.id,
  COALESCE(rule.points, 25),
  'Harvest recorded',
  COALESCE(h.harvested_at::timestamptz, h.created_at),
  jsonb_build_object('yield_kg', h.yield_kg, 'crop_id', h.crop_id)
FROM public.harvests h
LEFT JOIN public.green_point_rules rule
  ON rule.activity_type = 'harvest'
  AND rule.active = TRUE
ON CONFLICT (source_type, source_id) WHERE source_id IS NOT NULL DO NOTHING;
