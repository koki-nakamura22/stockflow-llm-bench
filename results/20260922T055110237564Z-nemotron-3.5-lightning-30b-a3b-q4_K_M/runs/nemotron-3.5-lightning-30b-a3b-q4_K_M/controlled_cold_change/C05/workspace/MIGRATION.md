# Rolling Migration: orders.total_amount -> subtotal_amount, tax_amount, total_amount

## Background

Existing `orders.total_amount` is tax-exclusive (tax-free) sum of line items. This migration
extends the API to expose three columns with a clear tax breakdown.

## Formulas

- `tax_amount = floor(subtotal_amount * 0.10)`  (10% tax, floored)
- `total_amount = subtotal_amount + tax_amount`  (tax-inclusive total)

## Migration Steps

### 1. `make migrate-expand`  (upgrade to revision 0002_expand)

**Purpose**: Add new columns and backfill existing data without breaking the old app.

**What happens**:

- Adds `subtotal_amount` and `tax_amount` columns to the `orders` table.
- Backfills existing rows: `subtotal_amount` = sum of `order_items.line_amount`,
  `tax_amount` = `FLOOR(subtotal_amount * 0.10)`.
- `total_amount` column is preserved with its original tax-exclusive meaning during the
  compatibility period.
- The old app continues to read/write `total_amount` as tax-exclusive; new orders from the
  old app will also populate `subtotal_amount` and `tax_amount`.

**Backward compatibility**: The old app's read/write is NOT broken. The physical column
`total_amount` remains tax-exclusive. New columns are added alongside.

**Re-execution safety**: Running the migration multiple times does not double-add values;
the backfill `UPDATE` sets absolute values, not incrementals.

### 2. `make migrate-contract`  (upgrade to revision 0003_contract)

**Purpose**: Finalize the schema after the old app has been stopped.

**What happens**:

- Reinterprets `total_amount` from tax-exclusive to tax-inclusive:
  `total_amount = subtotal_amount + tax_amount`.
- This is safe because the old app is stopped; no new writes will conflict.
- After this step, the schema has three meaningful columns:
  - `subtotal_amount` = tax-exclusive sum
  - `tax_amount` = calculated tax (10%, floored)
  - `total_amount` = tax-inclusive total

## API Changes

- Order creation now calculates `subtotal_amount`, `tax_amount`, and `total_amount` from
  the line items. The client (API consumer) does NOT send amount values; they are computed
  server-side from product `unit_price` and `quantity`.

## Column Meanings

| Phase | Column | Meaning |
|-------|--------|---------|
| Expand (compatibility) | `total_amount` | Tax-exclusive subtotal (preserved for old app) |
| Expand (compatibility) | `subtotal_amount` | Tax-exclusive sum of line items |
| Expand (compatibility) | `tax_amount` | Calculated tax, `floor(subtotal * 0.10)` |
| Contract | `total_amount` | Tax-inclusive total (`subtotal + tax`) |
| Contract | `subtotal_amount` | Tax-exclusive sum (unchanged) |
| Contract | `tax_amount` | Calculated tax (unchanged) |