CREATE TABLE IF NOT EXISTS public.atlas_memories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    memory_type text NOT NULL CHECK (
        memory_type IN (
            'user_preference',
            'durable_fact',
            'project_context',
            'task_outcome'
        )
    ),
    memory_key text NOT NULL CHECK (
        length(memory_key) BETWEEN 1 AND 120
        AND memory_key ~ '^[a-z0-9][a-z0-9._-]*$'
    ),
    content text NOT NULL CHECK (length(content) BETWEEN 1 AND 4000),
    source text NOT NULL CHECK (source IN ('user', 'explicit_selection')),
    search_document tsvector GENERATED ALWAYS AS (
        to_tsvector('simple'::regconfig, content)
    ) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, memory_type, memory_key)
);

CREATE OR REPLACE FUNCTION public.set_atlas_memories_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS atlas_memories_updated_at ON public.atlas_memories;
CREATE TRIGGER atlas_memories_updated_at
    BEFORE UPDATE ON public.atlas_memories
    FOR EACH ROW EXECUTE FUNCTION public.set_atlas_memories_updated_at();

CREATE INDEX IF NOT EXISTS atlas_memories_user_updated_idx
    ON public.atlas_memories (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS atlas_memories_user_type_updated_idx
    ON public.atlas_memories (user_id, memory_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS atlas_memories_search_document_idx
    ON public.atlas_memories USING gin (search_document);

ALTER TABLE public.atlas_memories ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS atlas_memories_select_own ON public.atlas_memories;
CREATE POLICY atlas_memories_select_own
    ON public.atlas_memories FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS atlas_memories_insert_own ON public.atlas_memories;
CREATE POLICY atlas_memories_insert_own
    ON public.atlas_memories FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS atlas_memories_update_own ON public.atlas_memories;
CREATE POLICY atlas_memories_update_own
    ON public.atlas_memories FOR UPDATE TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS atlas_memories_delete_own ON public.atlas_memories;
CREATE POLICY atlas_memories_delete_own
    ON public.atlas_memories FOR DELETE TO authenticated
    USING (auth.uid() = user_id);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.atlas_memories TO authenticated;
