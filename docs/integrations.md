# Integration configuration and authorization

## Google account connections

Before enabling Google account connection management:

1. Review `supabase/migrations/20261013000000_google_user_connections.sql` and
   apply it manually to the intended Supabase project. No cloud migration is
   run by the application.
2. Set these server-only backend settings:
   - `DATABASE_URL`: a PostgreSQL connection that can assume the
     `authenticated` role.
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REDIRECT_URI`: the exact backend callback URL,
     `https://<backend-host>/api/v1/google/oauth/callback` (use the local
     backend URL for development).
   - `GOOGLE_TOKEN_ENCRYPTION_KEY`: a Fernet-compatible encryption key stored
     outside source control and separate from the OAuth client secret.
3. Register exactly that callback URI in the Google OAuth client. Request only
   the scopes currently used by the existing Calendar and Gmail tools. A
   callback with unsupported or missing scopes is rejected.
4. Restart the backend after setting configuration. Never send database
   credentials, OAuth client secrets, or the encryption key to the browser.

Authenticated users can start OAuth with `GET /api/v1/google/oauth/start`,
inspect their own connection with `GET /api/v1/google/status`, and disconnect
with `DELETE /api/v1/google/connection`. Google calls back to
`GET /api/v1/google/oauth/callback`; the short-lived random state is persisted
only as a hash and consumed atomically. A state-specific, HttpOnly,
SameSite=Lax cookie binds the callback to its initiating browser, and the
state row identifies the authenticated user who initiated it. Callback
parameters cannot select an owner.
Credentials are encrypted before PostgreSQL persistence and are scoped by
RLS plus explicit user predicates. Disconnect deletes the local credential
before attempting provider revocation; a provider outage can prevent remote
revocation, but cannot leave a usable local connection.

Existing encrypted SQLite credential files, if any, are not imported or read
by the new runtime. Do not delete or migrate such files without an explicit
credential-handling procedure.

Google `actions_enabled` remains false. Chat does not yet have a verified
user-bound tool execution path; OAuth connection management must not be
mistaken for permission to execute Calendar or Gmail actions.

## GitHub App authorization status

The configured GitHub App and installation identify the App and grant it
access to the repositories selected for that installation. An installation
token is not a signed-in ATLAS user's GitHub identity or consent. ATLAS does
not currently have a GitHub user OAuth/identity link or a per-user grant
policy for repositories in the shared installation.

Consequently GitHub status reports App configuration only, and GitHub
operations remain disabled in the standard runtime. The existing API client
and tools are not wired to an authenticated public execution endpoint. Do not
enable repository reads or issue creation until an explicit user authorization
model is chosen and enforced on every execution, with repository membership
verified against the selected installation. Issue creation must continue to
require the existing high-risk confirmation decision.

## Security and operations

- Do not use request-body user IDs as evidence of identity; backend operations
  use the verified Supabase `sub`.
- Database RLS policies are applied under the `authenticated` role with
  transaction-local claims set by the backend after authentication (or from
  the one-time OAuth state record in the callback).
- Do not log authorization codes, provider tokens, OAuth client secrets,
  encryption keys, or credential payloads.
- Normal automated tests use fake provider transports and isolated stores;
  they do not verify live Google OAuth, GitHub installation access, or the
  Supabase RLS configuration. Verify those manually in a non-production
  Supabase project before rollout.
