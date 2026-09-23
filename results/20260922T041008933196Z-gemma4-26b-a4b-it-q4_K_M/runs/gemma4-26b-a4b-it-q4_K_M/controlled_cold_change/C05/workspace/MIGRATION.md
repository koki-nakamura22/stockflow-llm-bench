# Migration Plan: Rolling Migration for Order Total Amount

## Goal
Expand `orders.total_amount` from tax-exclusive to include `subtotal_amount`, `tax_amount`, and tax-inclusive `total_amount` using a rolling migration strategy.

## Phase 1: Expand
**Command:** `make migrate-expand`

**Changes:**
- **Database:** 
    - Add `subtotal_amount` and `tax_amount` columns to `orders` table (initially nullable).
    - Backfill `subtotal_amount = total_amount` and `tax_amount = floor(total_amount * 0.10)`.
    - `total_amount` column remains tax-exclusive.
- **Application (New Version):**
    - Update `Order` model to include `subtotal_amount` and `tax_amount`.
    - Update `OrderOut` schema to include `subtotal_amount`, `tax_amount`, and tax-inclusive `total_amount`.
    - Update `create_order` to populate `subtotal_amount` and `tax_amount` in the database.
    - `OrderOut.total_amount` is computed as `subtotal_amount + tax_amount` in the API response.

**Compatibility:**
- Old App (Write): Still writes `total_amount` (tax-exclusive). New App's `create_order` will also populate the new columns.
- Old App (Read): Reads `total_amount` (now tax-inclusive in API). While the value changes, the structure is preserved, and `subtotal_amount` is now available for clients that need the tax-exclusive amount.
- Re-running `migrate-expand` is safe as the backfill uses `=` which is idempotent.

## Phase 2: Contract
**Command:** `make migrate-contract`
(To be executed after the Old App is decommissioned)

**Changes:**
- **Database:**
    - Update `total_amount` column to store tax-inclusive amount: `total_amount = total_amount + tax_amount`.
    - Set `subtotal_amount` and `tax_amount` to `NOT NULL`.
- **Application (New Version):**
    - Update `create_order` to write the tax-inclusive amount to the `total_amount` column.
