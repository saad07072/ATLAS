CREATE TABLE IF NOT EXISTS public.atlas_workflows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES public.atlas_conversations (id) ON DELETE SET NULL,
    title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 120),
    user_request text NOT NULL CHECK (length(btrim(user_request)) BETWEEN 1 AND 4000),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'running', 'waiting_for_confirmation', 'completed', 'partially_completed', 'failed', 'cancelled')),
    current_step_id text,
    step_count int NOT NULL DEFAULT 0 CHECK (step_count >= 0),
    completed_step_count int NOT NULL DEFAULT 0 CHECK (completed_step_count >= 0),
    result_summary text,
    error_summary text,
    version int NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (user_id, id)
);

CREATE TABLE IF NOT EXISTS public.atlas_workflow_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL,
    step_id text NOT NULL CHECK (length(btrim(step_id)) BETWEEN 1 AND 64),
    step_order int NOT NULL CHECK (step_order >= 0),
    title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 120),
    tool_name text NOT NULL CHECK (length(btrim(tool_name)) BETWEEN 1 AND 100),
    arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
    dependencies jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'ready', 'running', 'waiting_for_confirmation', 'completed', 'failed', 'skipped', 'cancelled')),
    attempt_count int NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_retries int NOT NULL DEFAULT 0 CHECK (max_retries >= 0 AND max_retries <= 5),
    risk_level text NOT NULL DEFAULT 'low'
        CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    permission_required boolean NOT NULL DEFAULT false,
    permission_decision text,
    confirmation_state text NOT NULL DEFAULT 'not_requested'
        CHECK (confirmation_state IN ('not_requested', 'pending', 'confirmed')),
    confirmation_hash text,
    started_at timestamptz,
    completed_at timestamptz,
    result_data jsonb,
    error_info jsonb,
    verification_status text NOT NULL DEFAULT 'unverified'
        CHECK (verification_status IN ('unverified', 'verified', 'failed')),
    verification_details text,
    CONSTRAINT atlas_workflow_steps_owner_fk
        FOREIGN KEY (user_id, workflow_id)
        REFERENCES public.atlas_workflows (user_id, id)
        ON DELETE CASCADE,
    UNIQUE (workflow_id, step_id)
);

CREATE TABLE IF NOT EXISTS public.atlas_workflow_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL,
    step_id text,
    event_type text NOT NULL CHECK (length(btrim(event_type)) BETWEEN 1 AND 64),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT atlas_workflow_events_owner_fk
        FOREIGN KEY (user_id, workflow_id)
        REFERENCES public.atlas_workflows (user_id, id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS atlas_workflows_user_idx
    ON public.atlas_workflows (user_id, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS atlas_workflow_steps_workflow_idx
    ON public.atlas_workflow_steps (user_id, workflow_id, step_order ASC);

CREATE INDEX IF NOT EXISTS atlas_workflow_events_workflow_idx
    ON public.atlas_workflow_events (user_id, workflow_id, created_at ASC);

ALTER TABLE public.atlas_workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atlas_workflow_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atlas_workflow_events ENABLE ROW LEVEL SECURITY;

-- Workflows RLS
DROP POLICY IF EXISTS atlas_workflows_select_own ON public.atlas_workflows;
CREATE POLICY atlas_workflows_select_own
    ON public.atlas_workflows FOR SELECT TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_workflows_insert_own ON public.atlas_workflows;
CREATE POLICY atlas_workflows_insert_own
    ON public.atlas_workflows FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_workflows_update_own ON public.atlas_workflows;
CREATE POLICY atlas_workflows_update_own
    ON public.atlas_workflows FOR UPDATE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    )
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_workflows_delete_own ON public.atlas_workflows;
CREATE POLICY atlas_workflows_delete_own
    ON public.atlas_workflows FOR DELETE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

-- Workflow Steps RLS
DROP POLICY IF EXISTS atlas_workflow_steps_select_own ON public.atlas_workflow_steps;
CREATE POLICY atlas_workflow_steps_select_own
    ON public.atlas_workflow_steps FOR SELECT TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1 FROM public.atlas_workflows AS wf
            WHERE wf.id = workflow_id AND wf.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS atlas_workflow_steps_insert_own ON public.atlas_workflow_steps;
CREATE POLICY atlas_workflow_steps_insert_own
    ON public.atlas_workflow_steps FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1 FROM public.atlas_workflows AS wf
            WHERE wf.id = workflow_id AND wf.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS atlas_workflow_steps_update_own ON public.atlas_workflow_steps;
CREATE POLICY atlas_workflow_steps_update_own
    ON public.atlas_workflow_steps FOR UPDATE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1 FROM public.atlas_workflows AS wf
            WHERE wf.id = workflow_id AND wf.user_id = auth.uid()
        )
    )
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1 FROM public.atlas_workflows AS wf
            WHERE wf.id = workflow_id AND wf.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS atlas_workflow_steps_delete_own ON public.atlas_workflow_steps;
CREATE POLICY atlas_workflow_steps_delete_own
    ON public.atlas_workflow_steps FOR DELETE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

-- Workflow Events RLS
DROP POLICY IF EXISTS atlas_workflow_events_select_own ON public.atlas_workflow_events;
CREATE POLICY atlas_workflow_events_select_own
    ON public.atlas_workflow_events FOR SELECT TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1 FROM public.atlas_workflows AS wf
            WHERE wf.id = workflow_id AND wf.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS atlas_workflow_events_insert_own ON public.atlas_workflow_events;
CREATE POLICY atlas_workflow_events_insert_own
    ON public.atlas_workflow_events FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1 FROM public.atlas_workflows AS wf
            WHERE wf.id = workflow_id AND wf.user_id = auth.uid()
        )
    );

