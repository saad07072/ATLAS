# Supabase Auth setup

ATLAS uses Supabase Auth email magic links for application sign-in. The browser
uses the Supabase publishable/anon key, stores the session using
`@supabase/ssr` cookie storage, and exchanges the callback code on the server.
The Next.js proxy refreshes the session and protects application pages. API
requests send the current Supabase access token as a Bearer token.

The FastAPI dependency validates access-token signatures, expiry, audience,
issuer, authenticated role, and UUID subject. Asymmetric Supabase signing keys
are verified against the project's public JWKS endpoint. Legacy HS256 projects
can instead set the server-only `SUPABASE_JWT_SECRET`; the value must never be
sent to the frontend. Missing or invalid tokens receive a 401 response,
non-authenticated token roles receive 403, and unavailable verification
configuration/JWKS fails closed with 503.

## Local setup

1. In Supabase project settings, enable email sign-in and sign-ups. Configure
   email confirmation as desired. For production, configure a trusted SMTP
   provider and require email confirmation.
2. In Supabase Auth URL configuration, set the local Site URL to
   `http://localhost:3000` and allow these exact redirect URLs:
   `http://localhost:3000/auth/callback` and
   `http://127.0.0.1:3000/auth/callback`.
3. For production, set the Site URL and allow only the production HTTPS
   callback URL. Do not allow arbitrary wildcard redirects.
4. Copy the Supabase project URL and publishable/anon key into
   `frontend/.env.local` as `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
5. Configure the same project URL on the backend as `SUPABASE_URL`. If that
   project's signing keys use legacy HS256, set `SUPABASE_JWT_SECRET` in the
   backend environment using the current signing secret from the Supabase
   dashboard. Do not set this value for asymmetric signing keys and never put
   it in frontend variables.
6. Set the frontend callback URL in the Supabase Auth dashboard to
   `http://localhost:3000/auth/callback` for local development.

`supabase/config.toml` contains local redirect allow-list entries only. No
cloud Auth settings are changed by this implementation. Hosted Supabase
dashboard settings and production redirect URLs must be configured manually.

## Memory authorization and database RLS

Memory routes require the verified token subject; requests cannot choose a
`user_id`. The PostgreSQL repository connects with the server-side
`DATABASE_URL`, then inside each transaction switches to the `authenticated`
database role and sets the validated Supabase `sub`/role claims before running
parameterized SQL. This makes the migration's `auth.uid() = user_id` RLS
policies apply even when the connection string uses an elevated database
account. Queries also explicitly scope every operation by the verified owner.
If role switching, RLS context setup, or the database operation fails, the
request fails safely instead of bypassing row policies.

Use a trusted server-side Supabase PostgreSQL connection string that can assume
the `authenticated` role. Never use the Supabase `service_role` API key as a
database substitute and never expose database credentials to the browser.
Apply the memory migration following [the memory setup guide](./memory.md).

## Integration ownership

Google credentials are currently stored in one encrypted application-wide
SQLite record, and GitHub uses one application-wide App installation. Neither
credential source is scoped to a Supabase user. Until per-user ownership and
authorization are implemented:

- `GET /api/v1/google/oauth/start` and
  `GET /api/v1/google/oauth/callback` fail with 503 and do not create or save
  credentials.
- Google and GitHub status endpoints report configuration only;
  `connected` and `actions_enabled` are false because no user-owned connection
  is available.
- The standard Google and GitHub tool executors have no registered integration
  actions, so chat or other callers cannot execute operations with shared
  credentials.

Do not enable these actions or restore the shared OAuth callback until
credentials and OAuth state are bound to the authenticated owner and every
operation verifies that ownership. Google/GitHub credentials are not exposed
by the status endpoints.
