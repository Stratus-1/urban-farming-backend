-- Allow growers to create installations for properties they own.
-- The existing policy only allowed operators/admins, which blocked the garden wizard.

DROP POLICY IF EXISTS "Installations writable by ops" ON public.installations;

CREATE POLICY "Installations writable by owner and ops"
  ON public.installations
  FOR INSERT
  TO authenticated
  WITH CHECK (
    (
      auth.uid() = owner_id
      AND EXISTS (
        SELECT 1
        FROM public.properties p
        WHERE p.id = property_id
          AND p.owner_id = auth.uid()
      )
    )
    OR public.has_role(auth.uid(), 'operator')
    OR public.has_role(auth.uid(), 'admin')
  );
