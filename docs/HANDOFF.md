# ExpenseFlow — Handoff

## What it does

ExpenseFlow is a small expense submission and approval API (a proof of concept, not a production system). One user journey: submit an expense, normalize it to a base currency (INR), then approve or reject it. It exposes six endpoints under one FastAPI router (`app/routes.py`): create/list/fetch expenses, approve, reject, and a spending-insights report. See `README.md` for the full endpoint reference and setup steps.

A Streamlit UI (`ui/app.py`) is included as a separate, optional front-end that talks to the API over HTTP.

## How it works

- **Stack**: FastAPI + Uvicorn, SQLAlchemy ORM on SQLite (`expenseflow.db`), pydantic v2 schemas, `python-dotenv` for config, `anthropic` SDK for the insights endpoint.
- **Startup**: `app/main.py` defines a `lifespan` that calls `init_db()` (`app/db.py`), which runs `Base.metadata.create_all` — the `expenses` table is created automatically if it doesn't exist. There is no migrations tool (no Alembic); schema changes today mean either dropping/recreating the SQLite file or hand-editing it, since `create_all` only creates missing tables and never alters existing ones.
- **Per-request DB session**: `get_db()` yields a `SessionLocal()` and closes it in a `finally` block, wired in via FastAPI's `Depends`.
- **State machine**: an expense is created `pending`, then transitions to `approved` or `rejected` exactly once. `_apply_decision()` in `routes.py` does a conditional `UPDATE ... WHERE status = 'pending'`; if zero rows are affected, it returns `409 Conflict` rather than silently overwriting a prior decision. A DB-level `CHECK` constraint on `status` is a second line of defense. See `docs/ARCHITECTURE.md` for the full schema and edge-case rationale.
- **Money**: every amount is an integer in minor units, never a float — see `docs/adr/0001-money-as-integer-minor-units.md`.
- **Currency conversion is currently a stub.** `create_expense()` in `routes.py` hardcodes `fx_rate_micros = 1_000_000` (a 1:1 rate) and sets `amount_base_minor = amount_minor` directly — there is a `TODO` in the code to replace this with a real `httpx` call to an FX rate provider. `httpx` is installed and in the stack for exactly this purpose but is not invoked anywhere yet. **Do not treat `amount_base_minor` as economically accurate FX-converted data in its current state.**
- **Insights** (`GET /reports/insights`): sends a compact summary of all expenses (amount, category, status) to the Anthropic API (`app/insights.py`, model `claude-sonnet-4-6`) and returns the three-bullet response as one string. On any `anthropic.APIError`, it logs the error and returns a fixed fallback string instead of propagating a failure — so a missing/invalid `ANTHROPIC_API_KEY` degrades this one endpoint, it doesn't crash the app.

## What a deployment engineer needs to know

- **No authentication or authorization on any endpoint.** `submitted_by` and `decided_by` are free-text strings, not verified identities — there's no user system, no auth middleware, no API key check. Anyone who can reach the service can submit, approve, or reject expenses. This is an explicit scope decision recorded in `docs/ARCHITECTURE.md` ("no auth/user system... specified in the brief"), not an oversight — but it means this must sit behind your own auth/network boundary before being exposed beyond a trusted internal environment.
- **No CORS configuration.** If a browser client on a different origin needs to call this API directly, CORS middleware isn't set up in `app/main.py` today.
- **SQLite, single file, no backup/replication built in.** `DATABASE_URL` (read in `app/db.py`, defaults to `sqlite:///expenseflow.db`) can point at a different SQLAlchemy-compatible database, but nothing in the code assumes anything other than SQLite (e.g. `connect_args={"check_same_thread": False}` is SQLite-specific). SQLite is fine for the PoC's expected load; it is not built for high write concurrency or multi-instance deployment sharing one file.
- **Secrets**: only `ANTHROPIC_API_KEY` is read today (via `.env`/environment, `python-dotenv`). It's required only for real insight generation — the rest of the API works without it. Never bake it into an image or commit it; inject it via your deployment platform's secret store.
- **Run command for dev is not a production command.** `python -m uvicorn app.main:app --reload` (from `README.md`/`CLAUDE.md`) auto-reloads on file change and binds to `127.0.0.1` — for a real deployment, drop `--reload`, bind an appropriate host/port (or put it behind a reverse proxy), and run under a process supervisor (systemd, Docker, etc.) rather than a bare foreground process.
- **No test suite exists yet.** `pytest` is in the stack and `python -m pytest -q` is the documented convention, but there are currently no test files in the repo — there's nothing for CI to run until a suite is added.
- **No structured logging, metrics, or rate limiting** beyond Uvicorn's default access logs — plan for this before putting real traffic through it.
- **The Streamlit UI is a separate process** (`streamlit run ui/app.py`, default port 8501) that calls the API over HTTP using the `API_BASE` environment variable. It has no independent data store and no auth of its own — it inherits whatever access the API allows. If you deploy it, it needs its own runtime and network path to the API's `API_BASE` URL.

## Where to look for more detail

- `README.md` — setup (including Windows), `.env` configuration, run/test commands, full endpoint reference.
- `docs/ARCHITECTURE.md` — SQLite schema, per-column rationale, and how specific edge cases (FX-provider failure, double-decision races, rounding drift) are meant to be handled.
- `docs/adr/0001-money-as-integer-minor-units.md` — why money is an integer, not a float, and the trade-offs that follow.
