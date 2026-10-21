CREATE TABLE public.inspector_application_options (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  category TEXT NOT NULL CHECK (category IN ('growing_system', 'availability', 'transport_access')),
  value TEXT NOT NULL,
  label TEXT NOT NULL,
  featured BOOLEAN NOT NULL DEFAULT false,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT true,
  UNIQUE (category, value)
);

INSERT INTO public.inspector_application_options (category, value, label, featured, sort_order)
VALUES
  ('growing_system', 'soil_beds', 'Soil beds', true, 10),
  ('growing_system', 'raised_beds', 'Raised beds', true, 20),
  ('growing_system', 'container_growing', 'Container growing', true, 30),
  ('growing_system', 'hydroponics', 'Hydroponics', true, 40),
  ('growing_system', 'vertical_gardens', 'Vertical gardens', true, 50),
  ('growing_system', 'composting_soil_care', 'Composting and soil care', true, 60),
  ('growing_system', 'aquaponics', 'Aquaponics', false, 70),
  ('growing_system', 'aeroponics', 'Aeroponics', false, 80),
  ('growing_system', 'rooftop_growing', 'Rooftop growing', false, 90),
  ('growing_system', 'balcony_growing', 'Balcony growing', false, 100),
  ('growing_system', 'greenhouses', 'Greenhouses', false, 110),
  ('growing_system', 'shade_houses', 'Shade houses', false, 120),
  ('growing_system', 'seedling_propagation', 'Seedling propagation', false, 130),
  ('growing_system', 'irrigation_systems', 'Irrigation systems', false, 140),
  ('growing_system', 'pest_disease_management', 'Pest and disease management', false, 150),
  ('growing_system', 'community_food_gardens', 'Community food gardens', false, 160),
  ('availability', 'weekdays', 'Mostly weekdays', true, 10),
  ('availability', 'weekends', 'Mostly weekends', true, 20),
  ('availability', 'flexible', 'Flexible', true, 30),
  ('transport_access', 'own_vehicle', 'Own vehicle', true, 10),
  ('transport_access', 'public_transport', 'Public transport', true, 20),
  ('transport_access', 'mixed', 'A mix of both', true, 30),
  ('transport_access', 'limited', 'Limited transport', true, 40)
ON CONFLICT (category, value) DO UPDATE SET
  label = EXCLUDED.label,
  featured = EXCLUDED.featured,
  sort_order = EXCLUDED.sort_order,
  active = true;

GRANT SELECT ON public.inspector_application_options TO anon, authenticated;
GRANT ALL ON public.inspector_application_options TO service_role;
ALTER TABLE public.inspector_application_options ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read active inspector application options"
  ON public.inspector_application_options FOR SELECT TO anon, authenticated
  USING (active = true);
