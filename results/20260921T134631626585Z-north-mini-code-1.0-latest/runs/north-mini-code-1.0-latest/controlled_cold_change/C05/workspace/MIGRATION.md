# Rolling Migration for Orders Total Amount

## Overview

- Existing `orders.total_amount` is tax-exclusive total.
- Extend API to expose `subtotal_amount`, `tax_amount`, and `total_amount` (inclusive).
- Tax rate = 10%, tax_amount = floor(subtotal_amount * 0.10), total_amount = subtotal_amount + tax_amount.
- Two-step migration: **expand** (add new columns) and **contract** (swap meanings).

## Compatibility Mode

During expand (before contract):
- Old physical column `total_amount` retains tax‑exclusive meaning.
- New columns `subtotal_amount`, `tax_amount`, and temporary `total_amount_inclusive` are added.
- Existing rows are back‑filled: `subtotal_amount = total_amount`, `tax_amount = floor(subtotal_amount * 0.10)`, `total_amount_inclusive = subtotal_amount + tax_amount`.
- New orders inserted by the old app also populate the three new columns (subtotal_amount = total_amount, tax_amount computed, total_amount_inclusive = subtotal_amount + tax_amount).
- The API response includes `subtotal_amount` and `tax_amount` alongside the original `total_amount` (still tax‑exclusive). `total_amount_inclusive` is not exposed.
- No manual amount spec is accepted – amounts are derived from order items.

## Migration Commands

### `make migrate-expand`

Runs Alembic upgrade to revision **0002** (`0002-expand.py`):
- Adds `subtotal_amount`, `tax_amount`, `total_amount_inclusive` columns (nullable).
- Back‑fills values for all existing rows (idempotent: only updates rows where columns are NULL).
- Sets NOT NULL constraints and adds DB‑level check constraints.
- No breaking changes to the old app’s read/write behavior.

### `make migrate-contract`

Runs Alembic upgrade to revision **0003** (`0003-contract.py`):
- **Assumption:** The old app is stopped before running this command.
- Overwrites the existing `total_amount` column with the inclusive total (`subtotal_amount + tax_amount`), effectively changing its meaning.
- Drops the temporary `total_amount_inclusive` column.
- The database schema now has three columns:
  - `subtotal_amount` (tax‑exclusive)
  - `tax_amount` (tax)
  - `total_amount` (tax‑inclusive)
- The API now returns `subtotal_amount`, `tax_amount`, and `total_amount` (inclusive) for every order.
- Subsequent writes (from the new app) will populate all three fields accordingly.

Running the contract migration a second time is safe because the update to `total_amount` is idempotent (it always recomputes the same value) and the `total_amount_inclusive` column is already absent.

## Code Changes

### Models (`stockflow/models.py`)
- Added `subtotal_amount` and `tax_amount` columns to the `Order` model.
- Removed the temporary `total_amount_inclusive` column after the contract step (model updated before deployment).

### Schemas (`stockflow/schemas.py`)
- Extended `OrderOut` to include `subtotal_amount` and `tax_amount` fields.

### API (`stockflow/main.py`)
- Modified `create_order` to compute `subtotal_amount`, `tax_amount`, and set `total_amount` (tax‑exclusive) as before, while also populating the new columns.
- The endpoint now returns the three fields via `OrderOut`.

## Decisions & Rationale

1. **Two‑step migration (expand/contract):** Ensures zero downtime for the old app. The expand step is reversible and harmless; contract is run only after the old version is stopped.
2. **Temporary `total_amount_inclusive` column:** Allows us to compute the final inclusive total without losing the old `total_amount` values during the transition. It is dropped in the contract step.
3. **Idempotent back‑fill:** Using a `WHERE column IS NULL` clause guarantees that re‑running `migrate‑expand` does not recalc or double‑add values.
4. **API extension:** New fields are added to `OrderOut` without removing or renaming existing fields, preserving backward compatibility for clients that still read only `total_amount`.
5. **No manual amount spec:** The API never accepts `subtotal_amount`, `tax_amount` or `total_amount` from requests; they are always derived from the order items.
6. **Check constraints:** Added database‑level constraints for the new columns (`subtotal_amount >= 0`, `tax_amount >= 0`) to maintain data integrity.
7. **Model cleanup:** The temporary column is removed from the model after the contract step, keeping the schema clean for future development.

## Migration Summary

| Revision | Description | When to Run |
|----------|-------------|-------------|
| 0001     | Initial schema (existing) | — |
| 0002 (expand) | Add `subtotal_amount`, `tax_amount`, `total_amount_inclusive` and back‑fill | `make migrate-expand` (old app still running) |
| 0003 (contract) | Switch `total_amount` to inclusive, drop `total_amount_inclusive` | `make migrate-contract` (old app stopped) |

After running `0003`, the system is fully transitioned and the API returns the three monetary fields as specified.