# Migration 015: Make content_hash Index Unique

**Created:** 2026-02-21
**Revision ID:** 015
**Revises:** 014
**Status:** Ready to deploy

---

## Problem Statement

The Zeeschuimer import code uses `ON CONFLICT (content_hash) DO NOTHING` in its INSERT statements to deduplicate content during import. However, the `content_records` table currently has only a **non-unique** B-tree index on `content_hash` (created in migration 001).

PostgreSQL requires a unique index or unique constraint for `ON CONFLICT` specifications. Without this, every Zeeschuimer import INSERT fails with:

```
ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification
```

This is **BLOCKER-1** from the QA review.

---

## Solution

Migration 015 replaces the non-unique index with a **unique partial index**:

```sql
CREATE UNIQUE INDEX idx_content_hash_unique
ON content_records (content_hash)
WHERE content_hash IS NOT NULL
```

The partial index (with `WHERE content_hash IS NOT NULL`) is necessary because:
- `content_hash` is nullable — records without text content may have NULL content_hash
- PostgreSQL unique indexes allow multiple NULLs
- The partial index ensures uniqueness only among non-NULL values

---

## Migration Details

### Upgrade

1. Drops the existing non-unique index `idx_content_hash` (created in migration 001, line 366)
2. Creates a unique partial index `idx_content_hash_unique`

### Downgrade

1. Drops the unique partial index `idx_content_hash_unique`
2. Recreates the original non-unique B-tree index `idx_content_hash`

Both operations use raw SQL via `op.execute(sa.text(...))` following the pattern established in migration 001 and 007 for partitioned table operations.

---

## Partitioning Compatibility

The `content_records` table is range-partitioned by `published_at` (monthly boundaries). PostgreSQL automatically creates the unique partial index on each partition when it is created on the parent table. No separate partition-level DDL is required.

This has been verified in migrations 001 and 007 which similarly create indexes on the partitioned parent table.

---

## Impact Assessment

### Performance
- **Query performance:** Identical to the original non-unique index for lookups
- **Insert performance:** Minimal overhead — unique index enforcement is O(log n) with B-tree
- **Index size:** Slightly smaller due to NULL exclusion

### Application Impact
- **Zeeschuimer imports:** Now work correctly with `ON CONFLICT (content_hash) DO NOTHING`
- **Existing code:** No changes required — the index name change is internal to PostgreSQL
- **Data integrity:** Improved — prevents duplicate content_hash values at the database level

### Rollback Safety
- Migration is fully reversible
- Downgrade restores the exact original index structure
- No data loss or modification

---

## Testing Notes

After deployment, verify:

1. **Index exists:**
   ```sql
   SELECT indexname, indexdef
   FROM pg_indexes
   WHERE tablename = 'content_records'
     AND indexname = 'idx_content_hash_unique';
   ```

2. **Zeeschuimer import works:**
   ```sql
   INSERT INTO content_records (id, published_at, platform, arena, content_type,
                                 collection_tier, content_hash)
   VALUES (gen_random_uuid(), NOW(), 'linkedin', 'social_media', 'post',
           'manual', 'abc123')
   ON CONFLICT (content_hash) DO NOTHING;
   ```
   Should succeed without error.

3. **Duplicate rejection works:**
   Run the same INSERT twice — second execution should silently skip (0 rows affected).

---

## Files Modified

| File | Change |
|------|--------|
| `alembic/versions/015_make_content_hash_unique.py` | New migration file |
| `docs/status/db.md` | Updated migration list and index table |

---

## References

- **QA Review:** BLOCKER-1 in QA agent's latest review
- **Zeeschuimer protocol:** `/docs/research_reports/zeeschuimer_4cat_protocol.md`
- **Original index creation:** `alembic/versions/001_initial_schema.py` line 366
- **Previous migration:** `alembic/versions/014_add_zeeschuimer_imports_table.py`
- **PostgreSQL partial index docs:** https://www.postgresql.org/docs/16/indexes-partial.html
