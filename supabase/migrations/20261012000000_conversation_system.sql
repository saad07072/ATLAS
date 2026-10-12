CREATE TABLE IF NOT EXISTS public.atlas_conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    title text NOT NULL DEFAULT 'New conversation'
        CHECK (length(btrim(title)) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, id)
);

CREATE TABLE IF NOT EXISTS public.atlas_conversation_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 8000),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT atlas_conversation_messages_owner_fk
        FOREIGN KEY (user_id, conversation_id)
        REFERENCES public.atlas_conversations (user_id, id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS atlas_conversations_user_activity_idx
    ON public.atlas_conversations (user_id, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS atlas_conversation_messages_history_idx
    ON public.atlas_conversation_messages
        (user_id, conversation_id, created_at DESC, id DESC);

ALTER TABLE public.atlas_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atlas_conversation_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS atlas_conversations_select_own
    ON public.atlas_conversations;
CREATE POLICY atlas_conversations_select_own
    ON public.atlas_conversations FOR SELECT TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_conversations_insert_own
    ON public.atlas_conversations;
CREATE POLICY atlas_conversations_insert_own
    ON public.atlas_conversations FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_conversations_update_own
    ON public.atlas_conversations;
CREATE POLICY atlas_conversations_update_own
    ON public.atlas_conversations FOR UPDATE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    )
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_conversations_delete_own
    ON public.atlas_conversations;
CREATE POLICY atlas_conversations_delete_own
    ON public.atlas_conversations FOR DELETE TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
    );

DROP POLICY IF EXISTS atlas_conversation_messages_select_own
    ON public.atlas_conversation_messages;
CREATE POLICY atlas_conversation_messages_select_own
    ON public.atlas_conversation_messages FOR SELECT TO authenticated
    USING (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1
            FROM public.atlas_conversations AS conversation
            WHERE conversation.id = conversation_id
              AND conversation.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS atlas_conversation_messages_insert_own
    ON public.atlas_conversation_messages;
CREATE POLICY atlas_conversation_messages_insert_own
    ON public.atlas_conversation_messages FOR INSERT TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND auth.jwt() ->> 'atlas_backend' = 'true'
        AND EXISTS (
            SELECT 1
            FROM public.atlas_conversations AS conversation
            WHERE conversation.id = conversation_id
              AND conversation.user_id = auth.uid()
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.atlas_conversations TO authenticated;
GRANT SELECT, INSERT
    ON public.atlas_conversation_messages TO authenticated;
