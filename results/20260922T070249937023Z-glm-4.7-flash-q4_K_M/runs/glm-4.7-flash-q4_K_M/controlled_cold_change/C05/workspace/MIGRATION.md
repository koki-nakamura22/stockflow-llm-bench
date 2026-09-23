# Order Tax Migration

## Overview
This document records the decisions made during the rolling migration from `total_amount` (pre-tax) to `subtotal_amount`, `tax_amount`, and `total_amount` (tax-inclusive).

## Migration Strategy

### Phase 1: Expand/Backfill (Revision 0002)
- **Command**: `make migrate-expand`
- **Purpose**: Add new columns without breaking existing functionality
- **Implementation**:
  - Added `subtotal_amount` and `tax_amount` columns to orders table
  - Backfilled existing orders with:
    - `subtotal_amount` = existing `total_amount`
    - `tax_amount` = floor(`subtotal_amount` * 0.10)
  - Old `total_amount` remains unchanged (pre-tax)
  - New orders get all three columns set correctly

### Phase 2: Compatibility (Old App Running)
- **Duration**: Until old app is fully migrated
- **Behavior**:
  - Old app reads/writes `total_amount` (pre-tax) directly
  - New app reads/writes `subtotal_amount`, `tax_amount`, and calculates `total_amount`
  - During reads, both old and new columns are available
  - Old `total_amount` continues to represent pre-tax total
  - New orders from old app get `subtotal_amount` and `tax_amount` set correctly
  - Migration re-execution is safe (no double counting due to backfill only affecting NULL values)

### Phase 3: Contract (Revision 0003)
- **Command**: `make migrate-contract`
- **Purpose**: Remove old column after old app is stopped
- **Implementation**:
  - Removes `total_amount` column
  - `total_amount` is now computed as `subtotal_amount + tax_amount`
  - Only run this after old app is fully migrated and stopped

## API Changes

### Request
- **No changes**: API still accepts `items` with product IDs and quantities
- **No changes**: API does NOT accept `total_amount`, `subtotal_amount`, or `tax_amount` in requests

### Response
- **Old format** (before Phase 3):
  - `total_amount`: pre-tax total
- **New format** (after Phase 2):
  - `subtotal_amount`: pre-tax total
  - `tax_amount`: calculated tax (10%)
  - `total_amount`: tax-inclusive total

## Database Schema

### Before Migration
```sql
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,
    total_amount INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### After Phase 1 (Expand)
```sql
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,
    total_amount INTEGER NOT NULL,  -- pre-tax, kept for compatibility
    subtotal_amount INTEGER NOT NULL,  -- pre-tax total
    tax_amount INTEGER NOT NULL,  -- calculated tax
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### After Phase 3 (Contract)
```sql
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,
    subtotal_amount INTEGER NOT NULL,  -- pre-tax total
    tax_amount INTEGER NOT NULL,  -- calculated tax
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## Tax Calculation

- **Rate**: 10%
- **Formula**: `tax_amount = floor(subtotal_amount * 0.10)`
- **Total**: `total_amount = subtotal_amount + tax_amount`

## Rollback

### Rollback to Phase 1
- Run `alembic downgrade 0001_initial`
- This removes the new columns

### Rollback to Original
- Run `alembic downgrade 0001_initial`
- This removes all new columns and brings back original schema

## Safety Measures

1. **Separate Migrations**: Expand and contract are separate revisions
2. **No Double Counting**: Backfill only affects rows with NULL values
3. **Backward Compatibility**: Old app can still read/write during Phase 2
4. **Explicit Contract**: Contract migration requires explicit command execution
5. **No API Changes**: API does not accept amount specifications in requests

## Testing

### Public Tests
- Verify health endpoint
- Verify product round-trip
- Verify order creation with tax calculation
- Verify order response includes all three amount fields
- Verify tax is correctly calculated (10% of subtotal)

## Timeline

1. **Week 1**: Perform expand/backfill migration
2. **Week 2**: Run old app in compatibility mode
3. **Week 3**: Migrate old app to new API
4. **Week 4**: Perform contract migration
5. **Week 5**: Remove old app and verify everything works

## Decisions

1. **Why separate expand/contract?**
   - Allows gradual migration without downtime
   - Gives time to verify compatibility
   - Reduces risk of data corruption

2. **Why keep old `total_amount` during compatibility?**
   - Old app reads/writes this column directly
   - Removing it during compatibility would break old app
   - Only remove after old app is fully migrated

3. **Why not calculate tax on the fly?**
   - Tax rate is fixed (10%), making it efficient to pre-calculate
   - Reduces CPU load during queries
   - Simplifies reporting and analytics

4. **Why floor tax calculation?**
   - Avoids floating point precision issues
   - Ensures tax is always an integer
   - Consistent with accounting practices

## References

- Tax rate: 10%
- Migration command: `make migrate-expand` and `make migrate-contract`
- Original schema: `alembic/versions/0001_initial.py`
- Expand migration: `alembic/versions/0002_expand_order_columns.py`
- Contract migration: `alembic/versions/0003_contract_order_columns.py`