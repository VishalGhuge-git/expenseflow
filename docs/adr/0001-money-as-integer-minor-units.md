# 0001. Money as integer minor units

## Status

Accepted

## Context

ExpenseFlow stores an amount as submitted (`amount_minor`), a normalized base-currency amount (`amount_base_minor`), and the FX rate relating them (`fx_rate_micros`). These values are summed, compared, and serialized through SQLite, pydantic, and JSON, and must not silently drift under arithmetic.

## Decision

Store all money as integers in minor units (e.g. paise), never floats. The FX rate is likewise stored as an integer scaled by 1,000,000 (`fx_rate_micros`), not a float, since the same rounding concern applies to the multiplier as to the amount. `amount_base_minor` is computed once at submission and frozen on the row rather than recomputed later.

## Alternatives considered

- **Float/double** — rejected: binary floating point can't exactly represent most decimal currency values (`0.1 + 0.2 != 0.3`), causing silent drift when summed or FX-multiplied.
- **Decimal (fixed-point)** — rejected for this PoC: SQLite has no native `DECIMAL` type, and `Decimal` isn't a native JSON type either, so the API boundary would still coerce it to a string or float, pushing the ambiguity onto every client.
- **String-encoded amount** (`"45.99"`) — rejected: avoids float error but pushes parsing/validation onto every consumer and gives up SQL-native arithmetic and `CHECK` constraints.

## Consequences

- No floating-point rounding error in stored amounts or rates; sums and equality checks are exact.
- Integers are JSON-safe and language-agnostic for any client.
- Every UI/client boundary must explicitly convert major units (`"45.99"`) to/from minor units (`4599`) — an easy off-by-100 bug if forgotten.
- The unit is implicit, not type-enforced: `amount_minor` is meaningless without `original_currency`; nothing stops a caller from confusing it with `amount_base_minor`.
- `fx_rate_micros` caps rate precision at 6 decimal digits.
- Because `amount_base_minor` is frozen at submission, correcting a mis-recorded rate later requires a manual data fix, not just a code change.
