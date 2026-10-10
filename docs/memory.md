# Persistent memory setup

ATLAS stores only explicitly submitted memories in Supabase PostgreSQL. The
memory service does not save conversation messages or unreviewed model output.
Each row belongs to a Supabase Auth user, and row-level security restricts
authenticated Data API access to that owner.

## Apply the migration

1. In the Supabase dashboard, confirm the intended project and review
   `supabase/migrations/20261010000000_memory_system.sql`.
2. Link this repository to that project and apply the checked-in migration:

   ```powershell
   supabase link --project-ref <project-ref>
   supabase db push
   ```

   This uses the linked cloud project; a local Supabase stack or Docker is not
   required.
4. Configure the backend's server-side `DATABASE_URL` with the project's
   PostgreSQL connection string. Prefer the session pooler for deployed
   environments when direct database connectivity is unavailable. Never put
   this credential in frontend configuration or Git.

No pgvector extension or external vector store is required. Retrieval uses
PostgreSQL full-text search, recency, bounded result counts, and per-user
filters.

## Authentication boundary

The current application has no authenticated-user identity provider. The
memory API therefore returns `401 authentication_required` by default, and
chat does not retrieve or persist memory for anonymous requests. Do not replace
this fail-closed behavior with a client-supplied user ID. Integrate a trusted
Supabase Auth identity provider before exposing memory to users; the migration
already enables owner-scoped RLS for authenticated Supabase Data API access.

Memory creation is explicit. Reusing the same `(user, type, memory_key)`
updates that entry, so newer information replaces rather than silently
duplicating the keyed fact. Task outcomes are marked as explicitly selected.
Deleted rows are hard-deleted and cannot appear in retrieval.
