
-- ============ ENUMS ============
CREATE TYPE public.app_role AS ENUM ('grower','operator','buyer','admin');
CREATE TYPE public.grower_level AS ENUM ('seedling','grower','farmer','master_farmer');
CREATE TYPE public.installation_status AS ENUM ('planned','installed','active','paused','decommissioned');
CREATE TYPE public.batch_status AS ENUM ('planned','planted','growing','ready','harvested','failed');
CREATE TYPE public.collection_status AS ENUM ('scheduled','in_transit','collected','delivered_hub','qc_passed','qc_failed');
CREATE TYPE public.order_status AS ENUM ('draft','pending','confirmed','fulfilling','shipped','delivered','cancelled');
CREATE TYPE public.buyer_type AS ENUM ('restaurant','hotel','organic_store','retail_chain','subscriber');

-- ============ PROFILES ============
CREATE TABLE public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name TEXT,
  phone TEXT,
  avatar_url TEXT,
  city TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.profiles TO authenticated;
GRANT ALL ON public.profiles TO service_role;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Profiles viewable by owner" ON public.profiles FOR SELECT TO authenticated USING (auth.uid() = id);
CREATE POLICY "Profiles updatable by owner" ON public.profiles FOR UPDATE TO authenticated USING (auth.uid() = id);
CREATE POLICY "Profiles insertable by owner" ON public.profiles FOR INSERT TO authenticated WITH CHECK (auth.uid() = id);

-- ============ USER ROLES ============
CREATE TABLE public.user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role public.app_role NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, role)
);
GRANT SELECT ON public.user_roles TO authenticated;
GRANT ALL ON public.user_roles TO service_role;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own roles" ON public.user_roles FOR SELECT TO authenticated USING (auth.uid() = user_id);

CREATE OR REPLACE FUNCTION public.has_role(_user_id UUID, _role public.app_role)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS(SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role = _role)
$$;

-- ============ GROWER STATS / GAMIFICATION ============
CREATE TABLE public.grower_stats (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  level public.grower_level NOT NULL DEFAULT 'seedling',
  total_harvests INT NOT NULL DEFAULT 0,
  total_kg NUMERIC(12,2) NOT NULL DEFAULT 0,
  total_earnings NUMERIC(12,2) NOT NULL DEFAULT 0,
  reliability_score NUMERIC(4,2) NOT NULL DEFAULT 100,
  crop_success_rate NUMERIC(4,2) NOT NULL DEFAULT 100,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.grower_stats TO authenticated;
GRANT ALL ON public.grower_stats TO service_role;
ALTER TABLE public.grower_stats ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Grower sees own stats" ON public.grower_stats FOR SELECT TO authenticated USING (auth.uid() = user_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Grower inserts own stats" ON public.grower_stats FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

-- ============ BUYER PROFILES ============
CREATE TABLE public.buyer_profiles (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  business_name TEXT NOT NULL,
  buyer_type public.buyer_type NOT NULL DEFAULT 'restaurant',
  contact_email TEXT,
  address TEXT,
  city TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.buyer_profiles TO authenticated;
GRANT ALL ON public.buyer_profiles TO service_role;
ALTER TABLE public.buyer_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Buyer manages own profile" ON public.buyer_profiles FOR ALL TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ============ PROPERTIES ============
CREATE TABLE public.properties (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  address TEXT,
  city TEXT,
  lat NUMERIC(9,6),
  lng NUMERIC(9,6),
  available_space_m2 NUMERIC(8,2),
  sunlight_hours NUMERIC(4,1),
  photos JSONB NOT NULL DEFAULT '[]'::jsonb,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.properties TO authenticated;
GRANT ALL ON public.properties TO service_role;
ALTER TABLE public.properties ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Grower manages own properties" ON public.properties FOR ALL TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))
  WITH CHECK (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

-- ============ INSTALLATIONS ============
CREATE TABLE public.installations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id UUID NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  installation_code TEXT UNIQUE NOT NULL DEFAULT ('UF-' || substr(gen_random_uuid()::text,1,8)),
  install_type TEXT NOT NULL DEFAULT 'modular_bed',
  size_m2 NUMERIC(6,2) NOT NULL DEFAULT 4,
  capacity_units INT NOT NULL DEFAULT 12,
  status public.installation_status NOT NULL DEFAULT 'planned',
  installed_at DATE,
  photos JSONB NOT NULL DEFAULT '[]'::jsonb,
  maintenance_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.installations TO authenticated;
GRANT ALL ON public.installations TO service_role;
ALTER TABLE public.installations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Installations visible to owner and ops" ON public.installations FOR SELECT TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Installations writable by ops" ON public.installations FOR INSERT TO authenticated
  WITH CHECK (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Installations updatable by ops" ON public.installations FOR UPDATE TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

-- ============ CROP CATALOG ============
CREATE TABLE public.crops (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  variety TEXT,
  category TEXT,
  growth_days INT NOT NULL DEFAULT 45,
  est_yield_kg_per_unit NUMERIC(6,2) NOT NULL DEFAULT 0.5,
  price_per_kg NUMERIC(8,2) NOT NULL DEFAULT 0,
  image_url TEXT,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT ON public.crops TO anon, authenticated;
GRANT ALL ON public.crops TO service_role;
ALTER TABLE public.crops ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Crops publicly readable" ON public.crops FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Crops writable by ops" ON public.crops FOR ALL TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))
  WITH CHECK (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

-- ============ CROP BATCHES ============
CREATE TABLE public.crop_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  installation_id UUID NOT NULL REFERENCES public.installations(id) ON DELETE CASCADE,
  crop_id UUID NOT NULL REFERENCES public.crops(id),
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  planted_at DATE,
  expected_harvest_at DATE,
  units INT NOT NULL DEFAULT 12,
  expected_yield_kg NUMERIC(8,2) NOT NULL DEFAULT 0,
  status public.batch_status NOT NULL DEFAULT 'planned',
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.crop_batches TO authenticated;
GRANT ALL ON public.crop_batches TO service_role;
ALTER TABLE public.crop_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Batches visible to owner and ops" ON public.crop_batches FOR SELECT TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Batches writable by ops" ON public.crop_batches FOR ALL TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))
  WITH CHECK (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

-- ============ HARVESTS ============
CREATE TABLE public.harvests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  crop_batch_id UUID NOT NULL REFERENCES public.crop_batches(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES auth.users(id),
  crop_id UUID NOT NULL REFERENCES public.crops(id),
  harvested_at DATE NOT NULL DEFAULT CURRENT_DATE,
  yield_kg NUMERIC(8,2) NOT NULL DEFAULT 0,
  quality_grade TEXT DEFAULT 'A',
  grower_earnings NUMERIC(10,2) NOT NULL DEFAULT 0,
  available_kg NUMERIC(8,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.harvests TO authenticated;
GRANT ALL ON public.harvests TO service_role;
ALTER TABLE public.harvests ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Harvests visible to owner and ops" ON public.harvests FOR SELECT TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Harvests writable by ops" ON public.harvests FOR ALL TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))
  WITH CHECK (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

-- ============ COLLECTIONS ============
CREATE TABLE public.collections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  installation_id UUID NOT NULL REFERENCES public.installations(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES auth.users(id),
  scheduled_at TIMESTAMPTZ NOT NULL,
  status public.collection_status NOT NULL DEFAULT 'scheduled',
  driver_name TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.collections TO authenticated;
GRANT ALL ON public.collections TO service_role;
ALTER TABLE public.collections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Collections visible to owner and ops" ON public.collections FOR SELECT TO authenticated
  USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Collections writable by ops" ON public.collections FOR ALL TO authenticated
  USING (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))
  WITH CHECK (public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

-- ============ ORDERS ============
CREATE TABLE public.orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  buyer_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status public.order_status NOT NULL DEFAULT 'pending',
  total NUMERIC(10,2) NOT NULL DEFAULT 0,
  delivery_date DATE,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.orders TO authenticated;
GRANT ALL ON public.orders TO service_role;
ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Orders visible to buyer and ops" ON public.orders FOR SELECT TO authenticated
  USING (auth.uid() = buyer_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));
CREATE POLICY "Buyer creates orders" ON public.orders FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = buyer_id);
CREATE POLICY "Buyer/ops update orders" ON public.orders FOR UPDATE TO authenticated
  USING (auth.uid() = buyer_id OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'));

CREATE TABLE public.order_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
  crop_id UUID NOT NULL REFERENCES public.crops(id),
  quantity_kg NUMERIC(8,2) NOT NULL,
  unit_price NUMERIC(8,2) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.order_items TO authenticated;
GRANT ALL ON public.order_items TO service_role;
ALTER TABLE public.order_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Order items visible to buyer and ops" ON public.order_items FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND (o.buyer_id = auth.uid() OR public.has_role(auth.uid(),'operator') OR public.has_role(auth.uid(),'admin'))));
CREATE POLICY "Buyer adds items" ON public.order_items FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND o.buyer_id = auth.uid()));

-- ============ AGGREGATED INVENTORY VIEW ============
CREATE OR REPLACE VIEW public.inventory_aggregate AS
  SELECT c.id AS crop_id, c.name, c.category, c.price_per_kg, c.image_url,
         COALESCE(SUM(h.available_kg),0) AS available_kg,
         COUNT(DISTINCT h.owner_id) FILTER (WHERE h.available_kg > 0) AS contributing_growers
  FROM public.crops c
  LEFT JOIN public.harvests h ON h.crop_id = c.id
  GROUP BY c.id;
GRANT SELECT ON public.inventory_aggregate TO anon, authenticated;

-- ============ AUTO-CREATE PROFILE + DEFAULT ROLE ============
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
  RETURN NEW;
EXCEPTION
  WHEN undefined_table THEN
    RETURN NEW;
END; $$;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============ SEED CROP CATALOG ============
INSERT INTO public.crops (name, variety, category, growth_days, est_yield_kg_per_unit, price_per_kg, description) VALUES
  ('Basil','Genovese','Herbs',45,0.25,18.00,'Aromatic Italian basil, perfect for pesto and finishing dishes.'),
  ('Cherry Tomatoes','Sungold','Fruiting',75,1.20,12.00,'Sweet golden cherry tomatoes with bright acidity.'),
  ('Butter Lettuce','Buttercrunch','Leafy Greens',55,0.30,9.50,'Tender, buttery leaves for refined salads.'),
  ('Arugula','Wild Rocket',  'Leafy Greens',35,0.20,14.00,'Peppery wild rocket with a delicate bite.'),
  ('Mint','Spearmint','Herbs',50,0.20,16.00,'Fresh spearmint for teas, cocktails and garnishes.'),
  ('Kale','Lacinato','Leafy Greens',60,0.50,8.50,'Dark Tuscan kale, hearty and nutrient dense.'),
  ('Strawberries','Albion','Fruiting',90,0.40,22.00,'Sun-ripened everbearing strawberries.'),
  ('Chillies','Birds Eye','Fruiting',80,0.15,28.00,'Bright, fiery chillies for chefs and home kitchens.');
