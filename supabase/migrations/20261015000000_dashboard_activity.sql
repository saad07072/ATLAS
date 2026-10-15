-- ATLAS Phase 14: Dashboard & Activity Migration
-- Creates performance indices for chronological user activity retrieval.

CREATE INDEX IF NOT EXISTS atlas_workflow_events_user_created_idx
    ON public.atlas_workflow_events (user_id, created_at DESC);

-- Ensure RLS is verified on activity event queries
COMMENT ON TABLE public.atlas_workflow_events IS 'Stores chronological audit and lifecycle events for ATLAS workflows';

