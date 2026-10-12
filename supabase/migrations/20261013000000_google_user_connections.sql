CREATE TABLE IF NOT EXISTS public.atlas_google_connections (
    user_id uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    credentials_ciphertext bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.atlas_google_oauth_states (
    state_hash text PRIMARY KEY CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    binding_hash text NOT NULL CHECK (binding_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS atlas_google_oauth_states_expiry_idx
    ON public.atlas_google_oauth_states (expires_at);

ALTER TABLE public.atlas_google_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atlas_google_oauth_states ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS atlas_google_connections_select_own
    ON public.atlas_google_connections;
CREATE POLICY atlas_google_connections_select_own
    ON public.atlas_google_connections FOR SELECT TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_google_connections_insert_own
    ON public.atlas_google_connections;
CREATE POLICY atlas_google_connections_insert_own
    ON public.atlas_google_connections FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_google_connections_update_own
    ON public.atlas_google_connections;
CREATE POLICY atlas_google_connections_update_own
    ON public.atlas_google_connections FOR UPDATE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    )
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_google_connections_delete_own
    ON public.atlas_google_connections;
CREATE POLICY atlas_google_connections_delete_own
    ON public.atlas_google_connections FOR DELETE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_google_oauth_states_backend_insert
    ON public.atlas_google_oauth_states;
DROP POLICY IF EXISTS atlas_google_oauth_states_backend_select
    ON public.atlas_google_oauth_states;
CREATE POLICY atlas_google_oauth_states_backend_select
    ON public.atlas_google_oauth_states FOR SELECT TO authenticated
    USING (auth.jwt() ->> 'atlas_backend' = 'true');

CREATE POLICY atlas_google_oauth_states_backend_insert
    ON public.atlas_google_oauth_states FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_google_oauth_states_backend_delete
    ON public.atlas_google_oauth_states;
CREATE POLICY atlas_google_oauth_states_backend_delete
    ON public.atlas_google_oauth_states FOR DELETE TO authenticated
    USING (auth.jwt() ->> 'atlas_backend' = 'true');

GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.atlas_google_connections TO authenticated;
GRANT SELECT, INSERT, DELETE
    ON public.atlas_google_oauth_states TO authenticated;
