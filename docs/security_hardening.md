# ATLAS Security Hardening & Rate Limiting

Phase 15 implements comprehensive defense-in-depth security hardening across the ATLAS backend and frontend architectures. It introduces centralized rate limiting, strict request body limits, automated credential redaction in logs, security headers, hardened CORS policies, and robust error handling.

---

## 1. Threat Model & Defensive Strategy

ATLAS operates as a multi-user, autonomous AI assistant capable of interacting with external tools, APIs, and persisted user data. The threat model prioritizes realistic attack vectors:

| Threat Category | Attack Vector | Mitigation / Control |
|---|---|---|
| **API Abuse & Floods** | Excessive requests to expensive LLM and workflow execution paths | Centralized sliding-window rate limiting; throttled requests abort before invoking LLM or tools. |
| **Header Spoofing** | Forging `X-Forwarded-For` to bypass IP-based rate limits | Forwarding headers are rejected unless `TRUST_PROXY_HEADERS=true` AND client is in `TRUSTED_PROXIES`. |
| **Credential & Secret Exposure** | Tokens, OAuth codes, or private keys appearing in log streams or error responses | Regex-based `SensitiveDataRedactingFormatter` automatically strips Bearer tokens, JWTs, private keys, and passwords. |
| **Resource Exhaustion** | Sending multi-megabyte payloads to exhaust memory | Pure ASGI `RequestSizeLimitMiddleware` terminates requests exceeding `MAX_REQUEST_BODY_BYTES` with HTTP 413. |
| **MIME / Framing Attacks** | Clickjacking, drive-by framing, MIME-sniffing | `SecurityHeadersMiddleware` applies `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, and API-scoped `Content-Security-Policy`. |
| **Cross-User Data Leakage** | Tenant A querying or mutating Tenant B's workflows, memories, or chats | Strict `WHERE user_id = :user_id` parameter binding and authenticated RLS role claims. |
| **Integration Escalation** | LLM attempting unauthorized write actions via Google or GitHub | Integration actions remain strictly gated with `actions_enabled=False`. |

---

## 2. Centralized Rate Limiting

Rate limiting is governed by an in-memory sliding-window log engine located in `backend/app/security/rate_limit.py`.

### A. Endpoint Categories & Default Limits

| Category | Endpoints Protected | Default Limit | Key Strategy |
|---|---|---|---|
| **`chat`** | `POST /api/v1/chat` | `60/minute` | `user:<user_id>` (authenticated) or `ip:<client_ip>` |
| **`workflows`** | `POST /api/v1/workflows`<br>`POST /api/v1/workflows/{id}/start`<br>`POST /api/v1/workflows/{id}/resume` | `30/minute` | `user:<user_id>` |
| **`confirmations`** | `POST /api/v1/workflows/{id}/steps/{id}/confirm` | `30/minute` | `user:<user_id>` |
| **`oauth`** | `GET /api/v1/google/oauth/start`<br>`GET /api/v1/google/oauth/callback` | `20/minute` | `ip:<client_ip>` |
| **`authenticated`** | General authenticated endpoints (default) | `120/minute` | `user:<user_id>` |
| **`unauthenticated`** | Public / unauthenticated endpoints (default) | `60/minute` | `ip:<client_ip>` |

### B. Client Identity Resolution

Identity is resolved deterministically without trusting spoofable request headers:
- **Authenticated requests**: Derived from verified JWT claims (`user:<user_id>`).
- **Unauthenticated requests**: Derived from `request.client.host`. The `X-Forwarded-For` header is only parsed if:
  1. `settings.trust_proxy_headers` is explicitly `True`.
  2. The connecting client host matches `settings.trusted_proxies` (e.g., internal Nginx or Cloudflare proxy IP).

### C. HTTP 429 Response & Headers

When a client exceeds their quota, execution terminates immediately with HTTP 429:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 45
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 45

{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded for chat. Please try again in 45 seconds."
  }
}
```

### D. Architectural Limitations

> [!NOTE] In-Memory Rate Limiting Architecture
> The current rate limiter operates in-memory on the active Python process.
> - **Single Process / Multi-threaded**: Safe and synchronized via thread locks.
> - **Multi-Process / Multi-Worker**: In multi-process deployments (e.g., multiple Uvicorn workers), limits are enforced per-worker.
> - **Process Restarts**: Rate limit windows reset upon service restart.
> If distributed multi-node rate limiting is required in the future, the storage backend can be backed by a shared Redis cluster.

---

## 3. Security Headers & CORS Policy

### A. Security Headers

The `SecurityHeadersMiddleware` (`backend/app/core/security_middleware.py`) applies the following headers to all responses:

- `X-Content-Type-Options: nosniff` (Prevents browsers from interpreting files as a different MIME type).
- `X-Frame-Options: DENY` (Prevents clickjacking and framing).
- `Referrer-Policy: strict-origin-when-cross-origin` (Protects user query parameters in referrers).
- `Permissions-Policy: geolocation=(), camera=(), microphone=(self)` (Restricts browser sensor access).
- `X-Permitted-Cross-Domain-Policies: none` (Prevents Flash/PDF cross-domain leaks).
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` (Prevents injection or framing of API responses).
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (Active when `ENABLE_HSTS=true` or in production).

### B. CORS Configuration

CORS is strictly configured via `settings.cors_allow_origins`:
- Only designated trusted origins are permitted (default: `http://localhost:3000`, `http://127.0.0.1:3000`).
- Wildcard `*` origins are prohibited when `allow_credentials=True`.
- Allowed HTTP methods are limited to `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `HEAD`.

---

## 4. Request Body Size Limits

The `RequestSizeLimitMiddleware` protects server memory from denial-of-service attempts:
- Default threshold: `MAX_REQUEST_BODY_BYTES=1048576` (1 MB).
- Checks `Content-Length` header for early rejection.
- Monitored chunk-by-chunk for chunked/streaming requests to ensure chunked payloads cannot bypass content-length checks.
- Returns HTTP 413 `payload_too_large` with a structured error payload and full security headers (wrapped by `SecurityHeadersMiddleware`).

---

## 5. Automated Sensitive Data Redaction

Logging in `backend/app/core/logging_config.py` uses `SensitiveDataRedactingFormatter`:
- Intercepts all log records emitted by the root logger.
- Automatically redacts:
  - Bearer tokens: `Bearer [REDACTED]`
  - JWT tokens: `[REDACTED_JWT]`
  - PEM private keys: `[REDACTED_PRIVATE_KEY]`
  - OAuth codes: `code=[REDACTED]`
  - Sensitive key-value pairs across query params, headers, and JSON strings (`"client_secret": "[REDACTED]"`, `"auth_token": "[REDACTED]"`, `password=[REDACTED]`, `api_key=[REDACTED]`) while preserving valid JSON syntax.

---

## 6. Frontend Usability & Retry-After Handling

- **`ApiError` Class**: Defined in `frontend/services/api.ts` to capture HTTP status codes, error codes, and `Retry-After` seconds.
- **Rate Limit Notifications**: Displays exact countdown messages in the chat panel: *"Rate limit reached. Please wait X seconds before trying again."*
- **Double-Submit Prevention**: Chat and workflow actions disable submit controls while requests are in-flight, preventing accidental duplicate requests.

