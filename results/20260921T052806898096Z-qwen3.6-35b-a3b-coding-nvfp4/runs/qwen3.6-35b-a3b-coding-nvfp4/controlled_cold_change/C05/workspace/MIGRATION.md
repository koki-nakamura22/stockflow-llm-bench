# Rolling Migration: Tax Amount Expansion

## Background
Existing `orders.total_amount` stores tax-exclusive total (subtotal).
We need to expand to `subtotal_amount`, `tax_amount`, `total_amount`.

## Rules
- `tax_amount = floor(subtotal_amount * 0.10)`
- `total_amount = subtotal_amount + tax_amount`
- API requests do not accept amount values; amounts are computed server-side.

## Migration Strategy

### Phase 1: Expand (`make migrate-expand`)
- **Revision**: `0002_expand_tax_columns`
- **Action**: Add `subtotal_amount` and `tax_amount` columns to `orders` table.
- **Backfill**:
  - `subtotal_amount = total_amount` (old column is tax-exclusive)
  - `tax_amount = floor(subtotal_amount * 0.10)`
- **Trigger**: Add a BEFORE UPDATE trigger `trg_sync_tax_columns` that keeps
  `subtotal_amount` and `tax_amount` in sync when `total_amount` changes.
  This ensures old app writes to `total_amount` are reflected in new columns.
- **Compatibility**: Old app's read/write of `total_amount` is not broken.
  The trigger ensures new columns are updated on old app writes.
- **Idempotency**: Re-running this migration is safe; the trigger is idempotent
  (CREATE OR REPLACE) and backfill uses the current `total_amount` value.

### Phase 2: Contract (`make migrate-contract`)
- **Revision**: `0003_contract_remove_total`
- **Action**: Remove the old `total_amount` column after old app is stopped.
- **Precondition**: Old app must be stopped before running this.
- **Downgrade**: Re-add `total_amount` as `subtotal_amount + tax_amount`.

## Column Semantics
- **During compatibility** (after expand, before contract):
  - Physical column `total_amount` still means tax-exclusive (old semantics).
  - New columns `subtotal_amount` and `tax_amount` are populated.
  - Trigger keeps `subtotal_amount` and `tax_amount` in sync with `total_amount`.
- **After contract**:
  - `total_amount` column is removed.
  - Only `subtotal_amount` and `tax_amount` remain.
  - `total_amount` is computed as `subtotal_amount + tax_amount` in the API response.

## API Changes
- `OrderOut` now includes `subtotal_amount`, `tax_amount`, and `total_amount`.
- `OrderCreate` does not accept amount values; amounts are computed server-side.
- `create_order` computes `subtotal_amount` from items, then `tax_amount = floor(subtotal * 0.10)`,
  and `total_amount = subtotal + tax_amount`.

## Idempotency
- Re-running `migrate-expand` does not double-add because:
  - The trigger uses CREATE OR REPLACE (idempotent).
  - Backfill reads current `total_amount` and sets `subtotal_amount` and `tax_amount`.
  - If already backfilled, re-running sets the same values (no double computation).
