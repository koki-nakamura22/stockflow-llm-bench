# Migration: Tax Amount Addition to Orders

## Overview

Currently, `orders.total_amount` stores the pre-tax subtotal (税抜合計).
We need to extend the API to return three fields:
- `subtotal_amount`: pre-tax subtotal
- `tax_amount`: tax amount calculated as `floor(subtotal_amount * 0.10)`
- `total_amount`: post-tax total calculated as `subtotal_amount + tax_amount`

## Migration Strategy (Rolling Migration)

This is a rolling migration to avoid downtime and maintain compatibility with the old app.

### Phase 1: Expand Migration (`make migrate-expand`)

**Purpose**: Add new columns and backfill existing data WITHOUT breaking old app.

**Changes**:
1. Add new column `subtotal_amount` (integer, nullable temporarily)
2. Add new column `tax_amount` (integer, nullable)
3. Create database trigger to sync columns on write

**Trigger Logic**:
- When old app writes to `orders.total_amount` (pre-tax):
  - Set `subtotal_amount = NEW.total_amount` (pre-tax value)
  - Set `tax_amount = floor(subtotal_amount * 0.10)`
  - Set `total_amount = subtotal_amount + tax_amount` (post-tax for new API)

**Why this doesn't break old app**:
- Old app still writes to `total_amount` column as before
- Trigger intercepts and updates new columns atomically
- Old app reads `total_amount` and gets pre-tax value (same as before)
- Old app works exactly as before during this phase

**Backfill**:
- Set `subtotal_amount = total_amount` for existing rows
- Calculate and set `tax_amount` and update `total_amount` (post-tax)

**Idempotency**: Migration can be re-run safely - trigger ensures consistency.

### Phase 2: Contract Migration (`make migrate-contract`)

**Purpose**: Finalize the migration after old app has been replaced.

**Prerequisites**: Old app must be stopped before running this migration.

**Changes**:
1. Update `total_amount` column constraint to allow post-tax values
   OR keep column as-is since trigger handles it
2. Remove trigger (no longer needed)
3. Make columns NOT NULL
4. Update SQLAlchemy model to use new columns

**Note**: This migration is separate from expand and requires explicit command after old app stops.

## Column Semantics During Migration

| Column | During Compatibility | After Contract |
|--------|---------------------|----------------|
| `orders.total_amount` | Pre-tax subtotal (unchanged for old app) | Post-tax total (for new API) |
| `subtotal_amount` | Pre-tax subtotal (synced by trigger) | Pre-tax subtotal |
| `tax_amount` | Tax amount (synced by trigger) | Tax amount |

## API Request Handling

**IMPORTANT**: The API does NOT accept amount specification from requests.
All amounts are calculated server-side based on line items.

## Idempotency

Both migrations are idempotent:
- Expand: Trigger ensures data consistency; backfill uses `WHERE` clause
- Contract: Operations are safe to run multiple times

## Rollback

- Expand: Drop new columns and trigger
- Contract: Cannot easily rollback without data loss after contract