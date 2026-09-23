# Migration Plan: Rolling Migration for Orders Tax Calculation

## Overview
Add tax calculation to orders table with a rolling migration strategy to avoid breaking existing functionality.

## Changes
- Add `subtotal_amount`, `tax_amount`, and `total_amount` columns to the orders table
- Keep existing `total_amount` as pre-tax (税抜合計)
- New `total_amount` will be the post-tax total (税込合計)

## Migration Strategy

### Phase 1: Expand (migrate-expand)
- Add three new columns: `subtotal_amount`, `tax_amount`, `total_amount`
- Backfill existing orders with tax calculations:
  - `subtotal_amount = existing total_amount` (pre-tax total)
  - `tax_amount = floor(subtotal_amount * 0.10)`
  - `total_amount = subtotal_amount + tax_amount`
- This ensures old app can continue working without modification

### Phase 2: Contract (migrate-contract)
- Remove the old `total_amount` column
- Rename new `total_amount` to be the primary `total_amount`
- This step should only be executed after stopping the old app

## Compatibility
- During compatibility period, both old and new APIs work
- Old app: continues to use old `total_amount` (pre-tax)
- New app: uses new `total_amount` (post-tax)
- Both apps can read/write orders with the new columns

## Tax Rate
- 10% tax rate as specified
- Tax is calculated using floor() for `tax_amount`

## Idempotency
- Migration is designed to be idempotent
- Reading `total_amount` during compatibility returns pre-tax value
- Writing to orders will populate new columns automatically

## Execution Order
1. Run `make migrate-expand` to add columns and backfill data
2. Verify old app works correctly
3. When ready to remove old column, run `make migrate-contract`
4. Stop old app after migration is complete

## Decision Notes
- Tax calculation uses floor() for tax_amount to avoid floating point issues
- Separate expand/contract migrations allow for safe rollback
- New columns are nullable during expansion for safety
- Old total_amount remains as pre-tax during compatibility