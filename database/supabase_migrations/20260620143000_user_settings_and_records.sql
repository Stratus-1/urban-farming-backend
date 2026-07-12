-- ============ USER SETTINGS ============
CREATE TABLE public.user_settings (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  phone TEXT,
  address TEXT,
  bio TEXT,
  language TEXT NOT NULL DEFAULT 'English',
  timezone TEXT NOT NULL DEFAULT 'Africa/Johannesburg',
  theme TEXT NOT NULL DEFAULT 'Light',
  email_notifications BOOLEAN NOT NULL DEFAULT TRUE,
  push_notifications BOOLEAN NOT NULL DEFAULT TRUE,
  weekly_digest BOOLEAN NOT NULL DEFAULT TRUE,
  task_reminders BOOLEAN NOT NULL DEFAULT TRUE,
  profile_locked BOOLEAN NOT NULL DEFAULT FALSE,
  activity_tracking BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.user_settings TO authenticated;
GRANT ALL ON public.user_settings TO service_role;
ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "User settings visible to owner" ON public.user_settings
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "User settings insertable by owner" ON public.user_settings
  FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "User settings updatable by owner" ON public.user_settings
  FOR UPDATE TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ============ CONTACT MESSAGES ============
CREATE TABLE public.contact_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  subject TEXT NOT NULL,
  category TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX contact_messages_user_id_idx ON public.contact_messages (user_id);
CREATE INDEX contact_messages_status_idx ON public.contact_messages (status);
GRANT SELECT, INSERT, UPDATE ON public.contact_messages TO authenticated;
GRANT INSERT ON public.contact_messages TO anon;
GRANT ALL ON public.contact_messages TO service_role;
ALTER TABLE public.contact_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Contact messages visible to owner and ops" ON public.contact_messages
  FOR SELECT TO authenticated
  USING (
    user_id = auth.uid()
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );

CREATE POLICY "Contact messages insertable by anonymous visitors" ON public.contact_messages
  FOR INSERT TO anon
  WITH CHECK (user_id IS NULL);

CREATE POLICY "Contact messages insertable by authenticated users" ON public.contact_messages
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid() OR user_id IS NULL);

CREATE POLICY "Contact messages manageable by ops" ON public.contact_messages
  FOR UPDATE TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

-- ============ NEWSLETTER SUBSCRIPTIONS ============
CREATE TABLE public.newsletter_subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL DEFAULT 'landing',
  subscribed BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX newsletter_subscriptions_email_idx ON public.newsletter_subscriptions (email);
GRANT SELECT, INSERT, UPDATE ON public.newsletter_subscriptions TO authenticated;
GRANT INSERT, UPDATE ON public.newsletter_subscriptions TO anon;
GRANT ALL ON public.newsletter_subscriptions TO service_role;
ALTER TABLE public.newsletter_subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Newsletter insertable by anyone" ON public.newsletter_subscriptions
  FOR INSERT TO anon, authenticated
  WITH CHECK (true);

CREATE POLICY "Newsletter updatable by anyone" ON public.newsletter_subscriptions
  FOR UPDATE TO anon, authenticated
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Newsletter visible to ops" ON public.newsletter_subscriptions
  FOR SELECT TO authenticated
  USING (public.has_role(auth.uid(), 'operator') OR public.has_role(auth.uid(), 'admin'));

-- ============ SAVED CALCULATIONS ============
CREATE TABLE public.calculator_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  calculator_type TEXT NOT NULL,
  title TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, calculator_type, title)
);
CREATE INDEX calculator_plans_user_id_idx ON public.calculator_plans (user_id);
CREATE INDEX calculator_plans_type_idx ON public.calculator_plans (calculator_type);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.calculator_plans TO authenticated;
GRANT ALL ON public.calculator_plans TO service_role;
ALTER TABLE public.calculator_plans ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Calculator plans visible to owner" ON public.calculator_plans
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "Calculator plans insertable by owner" ON public.calculator_plans
  FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Calculator plans updatable by owner" ON public.calculator_plans
  FOR UPDATE TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Calculator plans deletable by owner" ON public.calculator_plans
  FOR DELETE TO authenticated
  USING (auth.uid() = user_id);

-- ============ UPDATED_AT TRIGGER ============
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_user_settings_updated_at ON public.user_settings;
CREATE TRIGGER set_user_settings_updated_at
BEFORE UPDATE ON public.user_settings
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_contact_messages_updated_at ON public.contact_messages;
CREATE TRIGGER set_contact_messages_updated_at
BEFORE UPDATE ON public.contact_messages
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_newsletter_subscriptions_updated_at ON public.newsletter_subscriptions;
CREATE TRIGGER set_newsletter_subscriptions_updated_at
BEFORE UPDATE ON public.newsletter_subscriptions
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS set_calculator_plans_updated_at ON public.calculator_plans;
CREATE TRIGGER set_calculator_plans_updated_at
BEFORE UPDATE ON public.calculator_plans
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============ BACKFILL EXISTING USERS ============
INSERT INTO public.user_settings (user_id)
SELECT id FROM auth.users
ON CONFLICT (user_id) DO NOTHING;

-- ============ AUTH USER BOOTSTRAP ============
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  user_role public.app_role;
  user_name text;
BEGIN
  user_role := COALESCE(
    NULLIF((NEW.raw_user_meta_data->>'role'), '')::public.app_role,
    'grower'
  );
  user_name := NULLIF(
    btrim(COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email, '')),
    ''
  );

  IF to_regclass('public.profiles') IS NOT NULL THEN
    INSERT INTO public.profiles (id, full_name)
    VALUES (NEW.id, user_name)
    ON CONFLICT (id) DO NOTHING;
  END IF;

  IF to_regclass('public.user_roles') IS NOT NULL THEN
    INSERT INTO public.user_roles (user_id, role)
    VALUES (NEW.id, user_role)
    ON CONFLICT DO NOTHING;
  END IF;

  IF to_regclass('public.grower_stats') IS NOT NULL THEN
    INSERT INTO public.grower_stats (user_id) VALUES (NEW.id)
    ON CONFLICT DO NOTHING;
  END IF;

  IF to_regclass('public.user_settings') IS NOT NULL THEN
    INSERT INTO public.user_settings (user_id)
    VALUES (NEW.id)
    ON CONFLICT DO NOTHING;
  END IF;

  RETURN NEW;
EXCEPTION
  WHEN undefined_table THEN
    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
