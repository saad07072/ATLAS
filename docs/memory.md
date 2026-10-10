# Persistent memory setup

ATLAS stores only explicitly submitted memories in Supabase PostgreSQL. The
memory service does not save conversation messages or unreviewed model output.
Each row belongs to a Supabase Auth user. The backend validates the access-token
subject, scopes each SQL operation to that owner, and applies the authenticated
role/claims in the database transaction so the row-level security policies
remain active for the direct PostgreSQL connection.

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
3. Configure the backend's server-side `DATABASE_URL` with the project's
   PostgreSQL connection string. Prefer the session pooler for deployed
   environments when direct database connectivity is unavailable. Never put
   this credential in frontend configuration or Git.

No pgvector extension or external vector store is required. Retrieval uses
PostgreSQL full-text search, recency, bounded result counts, and per-user
filters.

## Authentication boundary

Memory endpoints require the authenticated-user dependency and reject missing
or invalid tokens. Database role switching and owner-scoped RLS are described
in the [authentication setup guide](./authentication.md). Never replace this
boundary with a client-supplied user ID.

Memory creation is explicit. Reusing the same `(user, type, memory_key)`
updates that entry, so newer information replaces rather than silently
duplicating the keyed fact. Task outcomes are marked as explicitly selected.
Deleted rows are hard-deleted and cannot appear in retrieval.
