# ExpenseFlow Architecture

PoC expense submission and approval API. One user journey: submit an expense, convert it to base currency (INR), approve or reject it. See `CLAUDE.md` for stack and conventions.

**Assumptions made (no auth/user system or FX-rate storage convention specified in the brief):**
- Submitter/approver identity is a plain free-text field — no auth system, no `users` table.
- FX rate is persisted as an integer micro-rate (rate × 1,000,000), not a float, consistent with "money is stored as integer, never float" even though a rate isn't itself money.
- Any 3-letter ISO 4217-shaped currency code is accepted; the httpx FX call is the actual validator — unknown codes fail there, no hardcoded allow-list to maintain.
- Reject accepts an optional free-text reason; approve does not.

---

## 1. SQLite schema — `expenses` table

```sql
CREATE TABLE expenses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    submitted_by        TEXT    NOT NULL,
    description         TEXT    NOT NULL,
    amount_minor        INTEGER NOT NULL,   -- minor units (e.g. cents), in original_currency
    original_currency   TEXT    NOT NULL,   -- ISO 4217 code, e.g. 'USD'
    fx_rate_micros      INTEGER NOT NULL,   -- rate to INR * 1,000,000, captured at submission time
    amount_base_minor   INTEGER NOT NULL,   -- minor units (paise), normalised to INR
    status              TEXT    NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'approved', 'rejected')),
    rejection_reason    TEXT,               -- nullable; only set when status = 'rejected'
    decided_by          TEXT,               -- nullable; set on approve/reject
    created_at          TEXT    NOT NULL,   -- ISO-8601 UTC, set on insert
    decided_at          TEXT                -- nullable; ISO-8601 UTC, set on approve/reject
);
```

| Column | Type | Why |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Stable identifier for `GET`/approve/reject paths. |
| `submitted_by` | `TEXT NOT NULL` | Who filed the expense. No auth system exists, so this is a caller-supplied name, not a foreign key — keeps scope inside the brief. |
| `description` | `TEXT NOT NULL` | Human-readable reason for the expense; required so approvers have context. |
| `amount_minor` | `INTEGER NOT NULL` | The amount as submitted, in minor units of `original_currency`. Kept alongside the converted amount so the original claim is auditable and isn't lost to rounding. |
| `original_currency` | `TEXT NOT NULL` | ISO 4217 code of the submitted amount. Needed to interpret `amount_minor` and to know which FX pair was queried. |
| `fx_rate_micros` | `INTEGER NOT NULL` | The exact rate used for conversion, frozen at submission time, scaled by 1e6 to stay integer. Without freezing this, re-deriving `amount_base_minor` later (e.g. for a dispute) would use a different day's rate and silently disagree with what the approver saw. |
| `amount_base_minor` | `INTEGER NOT NULL` | The normalised INR amount in paise — this is the number approvers and reports actually act on ("Base currency is INR. All amounts are normalised to base on write."). |
| `status` | `TEXT NOT NULL CHECK(...)` | Workflow state. `CHECK` constraint enforces the enum at the DB layer as a second line of defense beyond pydantic validation. |
| `rejection_reason` | `TEXT NULL` | Optional explanation captured only on reject; nullable because approve and pending rows never set it. |
| `decided_by` | `TEXT NULL` | Who approved/rejected; null while pending. |
| `created_at` | `TEXT NOT NULL` | Audit trail / ordering; ISO-8601 string, matches SQLAlchemy's default `DateTime` mapping on SQLite (stored as TEXT). |
| `decided_at` | `TEXT NULL` | Null while pending; set the moment status changes, needed to answer "how long did this sit pending." |

No separate `users` or `currencies` table — both are out of scope per the brief; identity and currency are plain validated strings on the expense row itself.

---

## 2. Endpoints

All four endpoints map directly to the one stated journey (submit → convert → approve/reject) plus the minimum read access needed to act on that journey (you can't approve what you can't see).

| Method & path | Request body | Response | Notes |
|---|---|---|---|
| `POST /expenses` | `{"submitted_by": "priya", "description": "Client dinner", "amount_minor": 4599, "original_currency": "USD"}` | `201` — full expense object (see below), `status: "pending"` | Converts to INR synchronously via the FX call. Errors: `422` (bad shape / non-positive amount / malformed currency code), `502` (FX provider unreachable or no rate for that currency). |
| `GET /expenses/{id}` | — | `200` — full expense object, or `404` | Fetch one expense by id. |
| `GET /expenses?status=pending` | — (optional `status` query param) | `200` — array of expense objects | Lists expenses, optionally filtered by status; needed so an approver has something to act on. |
| `POST /expenses/{id}/approve` | `{"decided_by": "manager_raj"}` | `200` — updated expense, `status: "approved"` | Errors: `404` (no such expense), `409` (not currently `pending`). |
| `POST /expenses/{id}/reject` | `{"decided_by": "manager_raj", "reason": "missing receipt"}` (`reason` optional) | `200` — updated expense, `status: "rejected"`, `rejection_reason` set | Errors: `404`, `409` (same as approve). |

Example full expense object (returned by all endpoints):
```json
{
  "id": 1,
  "submitted_by": "priya",
  "description": "Client dinner",
  "amount_minor": 4599,
  "original_currency": "USD",
  "fx_rate": 83.12,
  "amount_base_minor": 382159,
  "status": "pending",
  "rejection_reason": null,
  "decided_by": null,
  "created_at": "2026-09-10T09:15:00Z",
  "decided_at": null
}
```

---

## 3. File layout

```
app/
  main.py       # FastAPI() app instance, mounts routes, startup event to create tables
  db.py         # SQLAlchemy engine + SessionLocal + Base, get_db() dependency, reads DATABASE_URL from env via python-dotenv
  models.py     # SQLAlchemy ORM model: Expense (maps to the schema in section 1)
  schemas.py    # pydantic v2 models: ExpenseCreate, ExpenseOut, ApproveRequest, RejectRequest
  routes.py     # the 4 endpoint handlers; calls an FX helper (httpx) inline or via a small fx.py if the call needs its own retry/timeout handling
tests/
  test_expenses.py   # submit -> get -> approve, submit -> get -> reject, 404/409 edge cases, FX-failure case (mocked)
.env            # FX_API_URL / FX_API_KEY etc. -- never committed, read via python-dotenv
requirements.txt
```

Notes:
- `routes.py` stays a single file since there's one resource (`expenses`) and four endpoints — splitting into a `routers/` package would be premature for this scope.
- The FX call belongs in `routes.py` (or a tiny `fx.py` if it needs its own timeout/retry constants) — CLAUDE.md says no new dependencies without asking, so this uses `httpx` only, already in the approved stack.
- `db.py` owns table creation on startup (`Base.metadata.create_all`) since there's no migrations tool in the stack (no Alembic mentioned, and adding one would be a new dependency).

---

## 4. Edge cases and how the design handles them

1. **FX provider is slow, down, or returns a stale/missing rate for the requested currency pair.**
   Submission is synchronous — if the external call hangs, the whole `POST /expenses` request hangs with it. The design handles this with an explicit httpx timeout (e.g. 5s) around the FX call in `routes.py`, translating any timeout/non-200/missing-rate response into a `502` rather than letting an unhandled exception surface as a `500` or hanging the request. No rate means no row is written — partial/unconverted expenses are never persisted.

2. **Race on double approve/reject, or approving something already decided.**
   Two concurrent `POST /expenses/{id}/approve` calls (or an approve after a reject) could both succeed and silently overwrite each other's decision. The design handles this by making the status transition conditional: the update only applies `WHERE status = 'pending'`, and if zero rows are affected, the endpoint returns `409 Conflict` instead of silently no-op'ing or double-processing. The `CHECK` constraint on `status` is a second line of defense against an invalid state ever landing in the table.

3. **Rounding drift between the original amount and the converted base amount.**
   Converting `amount_minor` (integer minor units) by a rate produces a fractional result that must become an integer `amount_base_minor`. Left unspecified, different call sites (submission vs. any future recompute) could round differently and produce a base amount that doesn't reconcile with `amount_minor × fx_rate`. The design fixes this by: (a) doing the conversion exactly once, at submission time, in a single place in `routes.py`; (b) always rounding half-up to the nearest paisa; (c) freezing both `fx_rate_micros` and the resulting `amount_base_minor` on the row, so nothing downstream ever recomputes the conversion — `amount_base_minor` is the row's source of truth for INR value, not a derived/re-calculable field.
