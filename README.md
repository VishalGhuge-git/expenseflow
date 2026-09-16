# ExpenseFlow

A small expense submission and approval API. This is a proof of concept, not a production system.

One user journey: submit an expense, convert it to a base currency (INR), then approve or reject it.

## What it does

- **Submit** an expense (`POST /expenses`) with an amount, ISO currency code, category, description, and submitter name. The expense is stored as `pending`.
- **Normalize to base currency.** Every expense carries both the amount as submitted (`amount_minor`, in the original currency's minor units) and the normalized INR amount (`amount_base_minor`, in paise), plus the exact rate used (`fx_rate_micros`). Money is always an integer — never a float.
  - Note on the current build: the FX conversion in `app/routes.py` is a stub — it records `fx_rate_micros = 1_000_000` (a 1:1 rate) rather than calling a real FX provider. `httpx` is in the stack for this purpose but isn't wired up to an external rate lookup yet.
- **List / fetch** expenses (`GET /expenses`, `GET /expenses/{id}`), optionally filtered by `status` and/or `category`.
- **Approve or reject** a pending expense (`POST /expenses/{id}/approve`, `POST /expenses/{id}/reject`). The transition only applies if the expense is still `pending` — a second decision on an already-decided expense returns `409 Conflict` instead of silently overwriting it.
- **Spending insights** (`GET /reports/insights`): sends a summary of all expenses (amount, category, status) to the Anthropic API and returns three short bullet insights as a single text string. Falls back to a fixed message if the Anthropic call fails.

A Streamlit UI (`ui/app.py`) is also included: it can submit expenses, list them in a status-color-coded table, approve/reject pending ones, and trigger the insights report against a running instance of this API.

## Stack

- Python 3.12
- FastAPI + Uvicorn
- SQLAlchemy ORM on SQLite (file: `expenseflow.db`, created automatically on startup)
- httpx (planned external FX rate call; not yet invoked — see note above)
- pydantic v2 for request/response models
- anthropic SDK (`app/insights.py`) for the insights endpoint
- pytest for tests
- python-dotenv for reading environment variables from `.env`

Versions installed in this project's `.venv` at the time of writing:

```
fastapi==0.141.1
uvicorn==0.52.4
SQLAlchemy==2.0.52
httpx==0.28.1
pydantic==2.13.5
python-dotenv==1.2.3
anthropic==1.5.0
pytest==9.1.1
```

There is currently no `requirements.txt` checked into the repo, so install these explicitly (see below).

## Setup

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install fastapi "uvicorn[standard]" SQLAlchemy httpx pydantic python-dotenv anthropic pytest
```

### Windows

1. Install Python 3.12 from [python.org](https://www.python.org/downloads/) — check **"Add python.exe to PATH"** during install.
2. Open PowerShell (or Command Prompt) in the project folder.
3. Create the virtual environment:
   ```powershell
   py -3.12 -m venv .venv
   ```
4. Activate it:
   - PowerShell:
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
     If you get an execution-policy error, run this first (only affects the current PowerShell process):
     ```powershell
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     ```
   - Command Prompt:
     ```cmd
     .venv\Scripts\activate.bat
     ```
5. Upgrade pip and install dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install fastapi "uvicorn[standard]" SQLAlchemy httpx pydantic python-dotenv anthropic pytest
   ```

Do not edit `.venv`, `.git`, or `expenseflow.db` directly.

## Configure `.env`

The app reads environment variables via `python-dotenv`. Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your-anthropic-api-key
```

- `ANTHROPIC_API_KEY` — required for `GET /reports/insights` to return real insights (used by `app/insights.py`). If it's missing or the Anthropic call fails, the endpoint returns a fixed fallback message instead of erroring.
- `DATABASE_URL` — optional, read in `app/db.py`. Defaults to `sqlite:///expenseflow.db` if unset. Only set this if you want to point at a different SQLite (or other SQLAlchemy-compatible) database.

Never commit `.env` or hardcode secrets in code.

## Run the server

```bash
python -m uvicorn app.main:app --reload
```

The app creates the `expenses` table automatically on startup if it doesn't already exist (`init_db()` in `app/db.py`, called from the FastAPI `lifespan` in `app/main.py`) — no manual migration step is needed.

Once running:
- API base URL: `http://127.0.0.1:8000`
- Interactive docs (Swagger UI): `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

### Run the UI (optional)

```bash
pip install streamlit pandas
streamlit run ui/app.py
```

The UI talks to the API at the URL in the `API_BASE` environment variable (defaults to `http://127.0.0.1:8000`), so the FastAPI server above must be running separately.

## Run the tests

```bash
python -m pytest -q
```

Note: at the time of writing, no test files exist in the repository yet — this command is the project's documented convention for when tests are added.

## Endpoint reference

All request/response bodies are JSON. Money fields are integers in minor units (e.g. cents, paise) — never floats.

### `POST /expenses`

Submit a new expense. Always created with `status = "pending"`.

Request body (`ExpenseCreate`):

| Field | Type | Constraints |
|---|---|---|
| `description` | string | min length 1 |
| `amount_minor` | integer | must be > 0 |
| `currency` | string | exactly 3 letters, pattern `^[A-Z]{3}$` (e.g. `"USD"`) |
| `category` | string | min length 1 |
| `submitted_by` | string | min length 1 |

Response: `201 Created`, body is an `ExpenseOut` (see below). `422` on validation failure.

### `GET /expenses`

List expenses, newest-id-last (ordered by `id`).

Query parameters (both optional):
- `status` — filter by `pending`, `approved`, or `rejected`
- `category` — filter by exact category match

Response: `200 OK`, `list[ExpenseOut]`.

### `GET /expenses/{expense_id}`

Fetch a single expense by id.

Response: `200 OK` with `ExpenseOut`, or `404 Not Found` if no expense with that id exists.

### `POST /expenses/{expense_id}/approve`

Approve a pending expense.

Request body (`ApproveRequest`):

| Field | Type | Constraints |
|---|---|---|
| `decided_by` | string | min length 1 |

Response: `200 OK` with the updated `ExpenseOut` (`status` becomes `"approved"`, `decided_by` and `decided_at` are set).
Errors: `404 Not Found` if the expense doesn't exist; `409 Conflict` if it isn't currently `pending` (e.g. already approved/rejected).

### `POST /expenses/{expense_id}/reject`

Reject a pending expense.

Request body (`RejectRequest`):

| Field | Type | Constraints |
|---|---|---|
| `decided_by` | string | min length 1 |
| `reason` | string \| null | optional |

Response: `200 OK` with the updated `ExpenseOut` (`status` becomes `"rejected"`, `rejection_reason`, `decided_by`, and `decided_at` are set).
Errors: `404 Not Found` if the expense doesn't exist; `409 Conflict` if it isn't currently `pending`.

### `GET /reports/insights`

Generate three short bullet insights across all expenses in the database (via the Anthropic API).

Response: `200 OK`
```json
{ "insight": "<text containing three bullet insights>" }
```
If the Anthropic call fails, `insight` is a fixed fallback string instead of an error response.

### `ExpenseOut` (returned by all expense endpoints)

| Field | Type | Notes |
|---|---|---|
| `id` | integer | |
| `submitted_by` | string | |
| `description` | string | |
| `category` | string | |
| `amount_minor` | integer | amount as submitted, in `currency`'s minor units |
| `currency` | string | ISO 4217 code as submitted (aliased from the DB's `original_currency` column) |
| `fx_rate_micros` | integer | rate to INR × 1,000,000, frozen at submission time |
| `amount_base_minor` | integer | amount normalized to INR, in paise |
| `status` | `"pending"` \| `"approved"` \| `"rejected"` | |
| `rejection_reason` | string \| null | set only when rejected |
| `decided_by` | string \| null | null while pending |
| `created_at` | datetime | |
| `decided_at` | datetime \| null | null while pending |
