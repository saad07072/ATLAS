# Persistent conversations

ATLAS stores authenticated users' chat conversations and messages in the
existing Supabase PostgreSQL database. Conversation history is separate from
long-term memory: the memory service does not copy messages into memory.
Conversation content is untrusted context for the existing agent; it does not
change system instructions or authorize tools.

## Apply the database migration manually

Review `supabase/migrations/20261012000000_conversation_system.sql` and apply it
to the intended Supabase project using the project's normal change process.
For a linked project, an operator can apply checked-in migrations with:

```powershell
supabase link --project-ref <project-ref>
supabase db push
```

Confirm the project reference before applying. ATLAS does not link to or apply
migrations to a live Supabase project automatically. No new environment
variable is required: conversations use the server-side `DATABASE_URL` already
used by persistent memory. The backend database role must be able to assume
the `authenticated` role; missing configuration or failed role/RLS setup
returns an unavailable response rather than bypassing access controls.

The migration creates owner-scoped conversation and message tables, bounded
content constraints, cascading message deletion, activity/history indexes,
and row-level security policies. The policies require both the verified
`auth.uid()` owner and an `atlas_backend` transaction claim. Only the backend
sets this claim after validating the Supabase access token; browser clients
must use the authenticated API rather than writing conversation rows directly.
Every backend query also filters by the verified user ID.

## API

All routes use the `/api/v1` prefix and require a valid Supabase access token:

- `POST /conversations` creates a conversation.
- `GET /conversations?limit=50&offset=0` lists conversations by most recent
  activity and reports whether another page exists.
- `GET /conversations/{id}?limit=100&offset=0` returns a bounded page of the
  conversation's messages in chronological order; message history is capped at
  200 per request and can be paged toward older messages with `offset`.
- `PATCH /conversations/{id}` renames an owned conversation.
- `DELETE /conversations/{id}` deletes an owned conversation and its messages.
- `POST /chat` accepts an optional `conversation_id`, persists the user message,
  invokes the existing agent with server-loaded context, persists a successful
  assistant response, and returns the selected `conversation_id`. When no ID
  is supplied, the backend creates a conversation for compatibility with
  existing chat clients.

Message text is bounded and checked for credential-like content before it is
stored. If generation fails, the persisted user message remains available in
the conversation; no assistant message is written for an unsuccessful
generation. Long-term memory remains opt-in and independent of chat history.
