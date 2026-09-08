-- ============ MOBILE PUSH TOKENS ============
CREATE TABLE public.mobile_push_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  token TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL,
  device_name TEXT,
  app_version TEXT,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX mobile_push_tokens_user_id_idx ON public.mobile_push_tokens (user_id);
CREATE INDEX mobile_push_tokens_platform_idx ON public.mobile_push_tokens (platform);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.mobile_push_tokens TO authenticated;
GRANT ALL ON public.mobile_push_tokens TO service_role;
ALTER TABLE public.mobile_push_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Mobile push tokens visible to owner" ON public.mobile_push_tokens
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "Mobile push tokens insertable by owner" ON public.mobile_push_tokens
  FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Mobile push tokens updatable by owner" ON public.mobile_push_tokens
  FOR UPDATE TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Mobile push tokens deletable by owner" ON public.mobile_push_tokens
  FOR DELETE TO authenticated
  USING (auth.uid() = user_id);

DROP TRIGGER IF EXISTS set_mobile_push_tokens_updated_at ON public.mobile_push_tokens;
CREATE TRIGGER set_mobile_push_tokens_updated_at
BEFORE UPDATE ON public.mobile_push_tokens
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
