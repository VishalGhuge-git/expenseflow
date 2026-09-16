# ExpenseFlow — Production Readiness Gap Audit

Scope: this audits the current code (`app/`, `ui/`) against a production bar, not the PoC bar it was built for (see `CLAUDE.md`: "PoC, not production"). Every item below is a real gap in the current repo, not a hypothetical.

## Summary

| Area | Classification | Rough effort |
|---|---|---|
| Authentication & key rotation | Blocking | 3–5 days (auth) + 1–2 days (rotation) |
| Input validation | Blocking (size/DoS bounds) / Deferrable (currency whitelist) | Hours–0.5 day |
| Rate limiting | Blocking | 1–2 days |
| Observability & logging | Blocking | 3–5 days |
| Error handling | Blocking (global handler) / Deferrable (retry/backoff) | 1 day / 2–3 days |
| DB migrations & pooling | Blocking (migrations) / Deferrable (pooling, while on SQLite) | 2–3 days / hours |
| Secrets management | Blocking | 0.5–1 day |
| Tests and coverage | Blocking | 5–8 days |
| Deployment & health checks | Blocking | 1–2 days |
| Data privacy for expense data | Blocking | 2–4 days |

## 1. Authentication and key rotation

**Current state**: none of the six endpoints (`POST /expenses`, `GET /expenses`, `GET /expenses/{id}`, `POST /expenses/{id}/approve`, `POST /expenses/{id}/reject`, `GET /reports/insights`) has any authentication or authorization. `submitted_by` and `decided_by` are unverified free-text strings supplied by the caller — anyone who can reach the service can submit an expense as anyone, or approve/reject anyone else's expense. There is no key-rotation mechanism for the one secret in use (`ANTHROPIC_API_KEY`): rotating it means editing `.env` and restarting the process, with no support for overlapping old/new keys during a rotation window.

**Gap**: no authn, no authz/RBAC (nothing stops a submitter from approving their own expense), no key rotation story.

**Classification**: Blocking — approve/reject on financial data with no identity verification is a non-starter for production.

**Effort**: Medium–Large. Adding an auth layer (API key or JWT, plus mapping verified identity → `submitted_by`/`decided_by`, plus an approver role check) is roughly 3–5 days depending on whether an identity provider already exists to integrate with. Key rotation support (reading from a secrets manager that supports versioning, e.g. AWS Secrets Manager/Vault, instead of a static `.env` value) is 1–2 days once an auth/secrets approach is chosen.

## 2. Input validation

**Current state**: pydantic v2 enforces some shape constraints in `app/schemas.py` — `description`/`category`/`submitted_by`/`decided_by` require `min_length=1`, `amount_minor` requires `> 0`, `currency` must match `^[A-Z]{3}$`. A DB-level `CHECK` constraint also enforces the `status` enum. There is no upper bound on any string field's length, no upper bound on `amount_minor`, no request body size limit, and `currency` is only shape-validated (any 3 uppercase letters pass, not just real ISO 4217 codes).

**Gap**: unbounded string/number inputs are a resource-exhaustion vector (e.g. a multi-megabyte `description` on every request, or an absurd `amount_minor`); no payload size ceiling at the ASGI or reverse-proxy layer.

**Classification**: Blocking for the missing size/length bounds (basic DoS hygiene expected at a prod bar). Deferrable for a real ISO 4217 currency whitelist — it's a correctness gap, not a security one, and is moot until the FX-stub is replaced with a real rate lookup anyway (see `docs/HANDOFF.md`).

**Effort**: Small — a few hours to add `max_length` constraints to the string fields and a sane upper bound on `amount_minor`, plus a body-size limit (ASGI middleware or reverse-proxy config). A static ISO 4217 whitelist is another few hours; sourcing it from whatever FX provider is eventually chosen is effectively free once that integration exists.

## 3. Rate limiting

**Current state**: none. No per-IP, per-key, or per-endpoint throttling anywhere; no `429` response is possible today.

**Gap**: every endpoint can be hit without limit. `GET /reports/insights` is the sharpest instance — each call makes a real, billed Anthropic API request with no caching or debouncing, so an unthrottled loop directly costs money and can exhaust API quota; `POST /expenses` can also be used to flood the database.

**Classification**: Blocking, especially for `/reports/insights` given its direct external cost.

**Effort**: Small–Medium, 1–2 days — e.g. `slowapi`/`starlette`-based limiter middleware with a stricter, separate limit on the insights endpoint. (Note: per `CLAUDE.md`, adding this dependency needs sign-off first.)

## 4. Observability and logging

**Current state**: the only logging call in the entire app is `logger.error(...)` in `app/insights.py`, fired when the Anthropic call fails. There is no request/response logging beyond Uvicorn's default access log, no request IDs/correlation IDs, no structured logging, no metrics (latency, error rate, DB timing), no tracing, and no alerting.

**Gap**: can't reconstruct "who called what, when, with what result" beyond what's implicitly in the `expenses` table (`decided_by`/`decided_at`) — failed attempts, 404s, 409 conflicts, and unauthenticated/malformed requests leave no trace. No visibility into Anthropic API health or latency beyond it silently falling back to a fixed string.

**Classification**: Blocking — structured request logging and basic error/metrics visibility are table stakes for operating anything in production.

**Effort**: Medium, 3–5 days — request-logging middleware (method, path, status, latency, request ID), shipping logs somewhere queryable, an error tracker (e.g. Sentry) for unhandled exceptions, and minimal latency/error-rate metrics.

## 5. Error handling

**Current state**: FastAPI's defaults handle most of this today — pydantic validation failures return `422` automatically, and `routes.py` raises explicit `HTTPException(404)`/`HTTPException(409)` for not-found and already-decided expenses. `app/insights.py` catches `anthropic.APIError` (the SDK's shared base class, so this also covers connection/timeout/rate-limit errors from Anthropic) and returns a fixed fallback string rather than propagating the failure. There is no global exception handler for anything else — an unhandled exception (e.g. the SQLite file being locked or corrupted) falls through to FastAPI's generic `500`, and there's no retry/backoff around the single Anthropic call attempt.

**Gap**: no standardized error response envelope for unhandled failures; no resilience (retry/backoff/circuit breaker) around the one external dependency.

**Classification**: Blocking for a global exception handler with a consistent error shape (so clients never see an inconsistent or leaky error format). Deferrable for retry/backoff on the Anthropic call — it already degrades gracefully today, this would just make that degrade less often.

**Effort**: Small, about 1 day for a global handler with a consistent JSON error envelope. Medium, 2–3 days, for retry/backoff/circuit-breaker behavior around the Anthropic call.

## 6. Database migrations and pooling

**Current state**: there is no migrations tool (no Alembic, nothing else) anywhere in the repo. The schema is created by `Base.metadata.create_all()` in `app/db.py`, invoked on every startup via the `lifespan` in `app/main.py` — this only creates missing tables, it never alters existing ones. The SQLAlchemy engine is created with no pooling configuration at all (`create_engine(DATABASE_URL, connect_args=...)` — no `pool_size`, `max_overflow`, or `pool_pre_ping`), and the SQLite-specific `check_same_thread=False` is the only connection tuning present.

**Gap**: any schema change (new column, changed constraint) has no versioned, repeatable path today — it means manual DB surgery or a destructive drop/recreate. Pooling has never been tuned, which is invisible on SQLite at low volume but becomes a real problem the moment the DB moves to Postgres/MySQL or traffic increases.

**Classification**: Blocking for migrations — no schema versioning is a hard blocker for any app expected to evolve in production. Deferrable for pooling while still on SQLite at low traffic; Blocking the moment a real RDBMS or concurrent load is introduced.

**Effort**: Medium, 2–3 days, to introduce Alembic and generate a baseline migration matching the current schema (also needs a heads-up conversation, since `CLAUDE.md` requires approval before adding new dependencies). Pooling configuration once a real RDBMS is chosen is small, a few hours.

## 7. Secrets management

**Current state**: the only secret is `ANTHROPIC_API_KEY`, read from `.env` via `python-dotenv`. **There is no `.gitignore` file in this repository at all** — `.env` currently shows as untracked in `git status`, but nothing stops a future `git add -A`/`git add .` from committing it and pushing the real key to remote history. There's also no `.env.example` documenting required variables without the real values, and no integration with any secrets manager (Vault, AWS/GCP secret stores) — the key lives in a plaintext local file.

**Gap**: no `.gitignore` protecting `.env` (and, per item 10 below, no `.gitignore` protecting the SQLite DB file either) is a live accidental-commit risk today, not a theoretical one.

**Classification**: Blocking — this is the single cheapest, highest-value fix in this whole audit and should happen regardless of anything else.

**Effort**: Small, well under a day — add a `.gitignore` (`.env`, `.venv/`, `expenseflow.db`, `__pycache__/`), add a checked-in `.env.example` with variable names only, and rotate `ANTHROPIC_API_KEY` if there's any chance the current value has been shared outside this machine. Full secrets-manager integration (for rotation, per item 1) is separately another 1–2 days.

## 8. Tests and coverage

**Current state**: `pytest` is installed and `python -m pytest -q` is the documented convention (`CLAUDE.md`, `README.md`), but **there are currently zero test files anywhere in the repository**. There is no coverage tooling configured, and no CI pipeline invoking any of this.

**Gap**: no automated verification exists for the state machine (pending→approved/rejected, the `409` conflict path, the `404` path), for input validation edge cases, or for the insights-endpoint fallback behavior. Every change today is verified manually or not at all.

**Classification**: Blocking — shipping to production with no test suite means every deploy is a manual regression risk, especially around the approve/reject race-condition logic that `docs/ARCHITECTURE.md` explicitly calls out as a designed-for edge case with nothing verifying it holds.

**Effort**: Large, roughly 5–8 days for a first meaningful suite — unit tests for schema validation, integration tests for all six endpoints (happy path + 404/409/422), a mocked-Anthropic test for the insights fallback path, and wiring coverage reporting into CI.

## 9. Deployment and health checks

**Current state**: the documented run command is `python -m uvicorn app.main:app --reload`, which is explicitly a dev command (auto-reload, no host/worker configuration). There is no `/health` or `/ping` endpoint anywhere in `app/routes.py`, no Dockerfile, no process-manager config (systemd unit, supervisor config), and no documented deployment target at all.

**Gap**: nothing to point a load balancer or orchestrator's liveness/readiness probe at; no production-grade process supervision; `--reload` and the default `127.0.0.1` bind are not deployment-appropriate.

**Classification**: Blocking — can't deploy behind any standard orchestrator (Kubernetes, ECS, etc.) or load balancer without a health check, and shouldn't run `--reload` in production regardless.

**Effort**: Small–Medium, 1–2 days — add a trivial `/health` endpoint (and ideally a DB-connectivity check within it), a production Uvicorn/Gunicorn invocation without `--reload`, and a Dockerfile or equivalent packaging plus process-manager config.

## 10. Data privacy for expense data

**Current state**: expense records (amount, category, description, submitter/approver names) are stored in a single unencrypted SQLite file (`expenseflow.db`) with **no `.gitignore` protecting it** (same gap as item 7 — it currently shows as untracked, nothing stops it from being committed). There is no encryption at rest, no data-retention policy, no PII handling review (submitter names are personal data; `description` is free text that could easily contain client names, meeting details, or other sensitive business information), and no access controls distinguishing who can read which expenses (any caller can `GET /expenses` and see everyone's records — compounds directly with the missing authz in item 1).

**Gap**: sensitive financial and personal data has no encryption at rest, no retention/deletion policy, no audit trail of who *read* it (only who decided it), and a real risk of accidental commit to version control.

**Classification**: Blocking — expense data is both financial and personal data; shipping this without at minimum access control and an accidental-commit guard is not acceptable at a production bar.

**Effort**: Medium, 2–4 days for the essentials — `.gitignore` for the DB file (shared fix with item 7), read-access control tied to the auth work in item 1, a documented retention/deletion policy, and disk-level encryption at rest (typically an infrastructure/platform setting rather than app code). A full privacy/compliance review (e.g. if this ever needs to meet GDPR/local data-protection requirements) is out of scope for an effort estimate here and would need its own separate review.
