ALTER TABLE public.inspector_application_options
  DROP CONSTRAINT inspector_application_options_category_check;

ALTER TABLE public.inspector_application_options
  ADD CONSTRAINT inspector_application_options_category_check
  CHECK (category IN ('growing_system', 'inspection_experience', 'crop_site_knowledge', 'availability', 'transport_access'));

ALTER TABLE public.inspector_applications
  ALTER COLUMN inspection_experience TYPE JSONB USING to_jsonb(inspection_experience),
  ALTER COLUMN crop_and_site_knowledge TYPE JSONB USING to_jsonb(crop_and_site_knowledge);

INSERT INTO public.inspector_application_options (category, value, label, featured, sort_order)
VALUES
  ('inspection_experience', 'site_assessments', 'Site assessments', true, 10),
  ('inspection_experience', 'farm_inspections', 'Farm or garden inspections', true, 20),
  ('inspection_experience', 'crop_planning', 'Crop planning', true, 30),
  ('inspection_experience', 'soil_assessment', 'Soil or growing-medium assessment', true, 40),
  ('inspection_experience', 'water_assessment', 'Water and irrigation assessment', true, 50),
  ('inspection_experience', 'sunlight_assessment', 'Sunlight and exposure assessment', true, 60),
  ('inspection_experience', 'safety_checks', 'Safety or access checks', true, 70),
  ('inspection_experience', 'quality_audits', 'Quality or compliance audits', true, 80),
  ('inspection_experience', 'field_data_collection', 'Field data collection', true, 90),
  ('inspection_experience', 'photo_documentation', 'Photo documentation and reporting', true, 100),
  ('inspection_experience', 'community_facilitation', 'Community or grower facilitation', true, 110),
  ('inspection_experience', 'training_and_mentoring', 'Training or mentoring growers', true, 120),
  ('crop_site_knowledge', 'crop_selection', 'Crop selection and crop fit', true, 10),
  ('crop_site_knowledge', 'seasonal_planning', 'Seasonal growing planning', true, 20),
  ('crop_site_knowledge', 'sunlight_and_orientation', 'Sunlight and site orientation', true, 30),
  ('crop_site_knowledge', 'water_availability', 'Water availability and access', true, 40),
  ('crop_site_knowledge', 'soil_quality', 'Soil quality and preparation', true, 50),
  ('crop_site_knowledge', 'drainage', 'Drainage and flood risk', true, 60),
  ('crop_site_knowledge', 'pest_management', 'Pest and disease risk', true, 70),
  ('crop_site_knowledge', 'food_safety', 'Food safety basics', true, 80),
  ('crop_site_knowledge', 'space_measurement', 'Space measurement and layout', true, 90),
  ('crop_site_knowledge', 'access_and_logistics', 'Access and harvest logistics', true, 100),
  ('crop_site_knowledge', 'microclimates', 'Urban microclimates', true, 110),
  ('crop_site_knowledge', 'sustainable_practice', 'Sustainable growing practices', true, 120)
ON CONFLICT (category, value) DO UPDATE SET
  label = EXCLUDED.label,
  featured = EXCLUDED.featured,
  sort_order = EXCLUDED.sort_order,
  active = true;
