-- ============ GARDEN CROP SEED ============
INSERT INTO public.crops (name, variety, category, growth_days, est_yield_kg_per_unit, price_per_kg, description)
VALUES
  (
    'Lettuce',
    'Buttercrunch',
    'Leafy Greens',
    55,
    0.30,
    9.50,
    'Tender lettuce for salads and harvest rotation.'
  ),
  (
    'Tomato',
    'Cherry',
    'Fruiting',
    75,
    1.20,
    12.00,
    'Compact tomatoes that perform well in raised beds.'
  ),
  (
    'Spinach',
    'Baby Leaf',
    'Leafy Greens',
    40,
    0.22,
    10.50,
    'Fast-growing spinach for quick harvest cycles.'
  )
ON CONFLICT (name) DO NOTHING;
