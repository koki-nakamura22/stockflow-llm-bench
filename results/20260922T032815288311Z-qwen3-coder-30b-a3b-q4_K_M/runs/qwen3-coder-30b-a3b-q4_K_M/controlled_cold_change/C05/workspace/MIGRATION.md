# Rolling Migration Plan: Tax Calculation

## Overview
This document describes the rolling migration from a single `total_amount` column to separate `subtotal_amount`, `tax_amount`, and `total_amount` columns with tax calculation.

## Migration Phases

### Phase 1: Expand (Add New Columns)
- **Command**: `make migrate-expand` (or `alembic upgrade head`)
- **Changes**:
  - Added new columns: `subtotal_amount`, `tax_amount`, `total_amount_new`
  - Maintained backward compatibility with existing `total_amount` column
  - Updated models and schemas to support both old and new fields
  - Modified order creation logic to populate new fields

### Phase 2: Contract (Remove Old Column)
- **Command**: `make migrate-contract` (after app shutdown)
- **Changes**:
  - Removed the old `total_amount` column
  - Updated constraints to only reference new columns

## Implementation Details

### Tax Calculation Logic
- `tax_amount = floor(subtotal_amount * 0.10)`
- `total_amount_new = subtotal_amount + tax_amount`

### Backward Compatibility
During the migration period:
- The old `total_amount` column retains its pre-tax value (for compatibility)
- New fields (`subtotal_amount`, `tax_amount`, `total_amount_new`) are populated with proper values
- API responses include all fields for both old and new clients

### Data Migration
- All existing rows will have their tax-related fields populated during the expand phase
- New orders will automatically populate all fields correctly
- The migration is idempotent - re-running won't cause double calculation

## Commands
```bash
# Expand phase - run while app is still running
make migrate

# Contract phase - run after app stops
make migrate-contract
```

## Notes
1. This migration supports rolling updates without downtime
2. The old `total_amount` column is maintained for backward compatibility
3. All new orders will have tax calculation properly applied
4. The contract phase should only be executed after all application instances are stopped