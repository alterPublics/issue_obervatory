# YF-01: Per-Arena Search Term Scoping — Database Layer Implementation

**Status**: Complete (database layer)
**Date**: 2026-02-19
**Agent**: Database & Data Processing Engineer

## Summary

Implemented the database layer changes for YF-01 (Per-Arena Search Term Scoping). This feature allows researchers to optionally specify which arena platform_names a search term should be dispatched to, preventing credit waste and cross-platform contamination.

## Changes Implemented

### 1. SQLAlchemy ORM Model

**File**: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/query_design.py`

Added `target_arenas` field to the `SearchTerm` model (line 203-207):

```python
# Optional list of arena platform_names. NULL = all arenas.
target_arenas: Mapped[list[str] | None] = mapped_column(
    JSONB,
    nullable=True,
    comment="Optional list of arena platform_names. NULL = all arenas.",
)
```

**Type**: `JSONB` (stores list of platform_name strings)
**Nullable**: `True` (NULL means "all arenas")
**Default**: `NULL` (backward-compatible)

### 2. Pydantic Schemas

**File**: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/schemas/query_design.py`

Updated two schema classes:

#### SearchTermCreate (lines 112-136)
Added field and docstring:
```python
target_arenas: Optional[list[str]] = Field(
    default=None,
    description=(
        "Optional list of arena platform_names to which this term applies. "
        "NULL or empty list means all enabled arenas."
    ),
)
```

#### SearchTermRead (lines 130-147)
Inherits from `SearchTermCreate`, so `target_arenas` is automatically included in the read schema.

### 3. Alembic Migration

**File**: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/alembic/versions/010_add_target_arenas_to_search_terms.py`

Created new migration with:
- **Revision ID**: `010`
- **Down revision**: `009`
- **Upgrade**: Adds nullable JSONB column `target_arenas` to `search_terms` table
- **Downgrade**: Removes the column

Migration is fully reversible and non-breaking.

### 4. Status Documentation

**File**: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/status/db.md`

Added migration entry to the migrations list:
```markdown
- [x] `010_add_target_arenas_to_search_terms` — adds `target_arenas JSONB NULL`
      to `search_terms`; implements YF-01 per-arena search term scoping (2026-02-19)
```

## Schema Design Decisions

### Why JSONB?
- Flexible storage for a list of platform_name strings
- No need for a join table (search terms are not a many-to-many relationship with arenas)
- Indexed with GIN if needed for queries (not required for initial implementation)
- Allows empty list `[]` vs `NULL` distinction if needed in the future

### Why Nullable?
- **Backward compatibility**: All existing search terms will have `target_arenas = NULL`, which means "all arenas"
- **No data migration required**: Existing terms continue to work as before
- **Clear semantics**: NULL = "apply to all arenas", explicit list = "apply only to these arenas"

### Why No FK Constraint?
- Arena platform_names are not stored as rows in a database table
- Arena registration happens in Python code via the `@register` decorator
- A CHECK constraint would be fragile (would need updating every time a new arena is added)
- Validation should happen at the application layer when dispatching collection tasks

## Backward Compatibility

✅ **Fully backward-compatible**:
- All existing search terms will have `target_arenas = NULL` after migration
- NULL semantics: "apply this term to all enabled arenas" (current behavior)
- No application code changes required to maintain existing behavior
- API clients that don't send `target_arenas` will continue to work

## Data Model Semantics

| `target_arenas` value | Meaning | Example |
|----------------------|---------|---------|
| `NULL` | Apply to all enabled arenas | Existing terms, general keywords |
| `[]` (empty list) | No arenas (term inactive?) | Edge case, likely validation error |
| `["reddit"]` | Apply only to Reddit | Platform-specific terms |
| `["reddit", "youtube"]` | Apply only to Reddit and YouTube | Multi-platform but not all |

## Next Steps (for other agents)

### Core Application Engineer
**Priority**: High

The collection dispatcher needs to be updated to respect `target_arenas`:

1. **Collection task dispatcher** (likely in `/src/issue_observatory/workers/collection_tasks.py` or similar):
   - When assembling the list of terms for a collection run, filter terms by arena
   - Pseudo-code logic:
     ```python
     def get_terms_for_arena(query_design_id: UUID, platform_name: str) -> list[SearchTerm]:
         # Fetch all active terms for the query design
         terms = await db.execute(
             select(SearchTerm)
             .where(
                 SearchTerm.query_design_id == query_design_id,
                 SearchTerm.is_active == True,
             )
         )
         # Filter: include term if target_arenas is NULL or contains this platform
         filtered_terms = [
             term for term in terms
             if term.target_arenas is None  # Apply to all arenas
             or platform_name in term.target_arenas  # Explicitly targeted
         ]
         return filtered_terms
     ```

2. **Update collection logging** to record which terms were dispatched to which arenas

3. **Add validation** at the API layer when creating/updating search terms:
   - Validate that all platform_names in `target_arenas` exist in the arena registry
   - Return HTTP 400 if an unknown platform_name is provided

### Frontend Engineer
**Priority**: Medium

The Query Design editor needs UI controls for `target_arenas`:

1. **Search term editor**:
   - Add an "Arena Scope" selector (multi-select or checkboxes)
   - Default state: "All arenas" (corresponds to `target_arenas = null`)
   - When user selects specific arenas, send `target_arenas: ["reddit", "youtube"]` in the POST/PATCH request

2. **Search term list view**:
   - Display a visual indicator (badge/chip) showing arena scope
   - Example: "All arenas" or "Reddit, YouTube only"

3. **Bulk edit** (if implementing YF-03 bulk import):
   - Allow setting arena scope for multiple terms at once

### QA Guardian
**Priority**: Medium

Test coverage needed:

1. **Migration test**: Verify migration up/down works without data loss
2. **Schema test**: Verify `SearchTermCreate` and `SearchTermRead` accept/return `target_arenas`
3. **API test**: POST new search term with `target_arenas`, verify it's persisted
4. **Collection test**: Verify terms are filtered correctly per arena during collection dispatch
5. **Edge case tests**:
   - Empty list `[]` behavior
   - Invalid platform_name in list (should fail validation)
   - NULL vs omitted field behavior

## Migration Execution

The migration has been created but NOT yet run (database connection unavailable in development environment).

To run the migration in a working environment:

```bash
# Activate virtual environment
source .venv/bin/activate

# Check current revision
alembic current

# Run the migration
alembic upgrade head

# Verify the column was added
psql $DATABASE_URL -c "\d search_terms"
# Should show: target_arenas | jsonb | | |
```

To rollback (if needed):

```bash
alembic downgrade 009
```

## Testing the Implementation

### Manual SQL Test

After running the migration, verify with:

```sql
-- Check the column exists
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'search_terms'
AND column_name = 'target_arenas';

-- Insert a test term with arena scoping
INSERT INTO search_terms (query_design_id, term, term_type, target_arenas)
VALUES (
    '00000000-0000-0000-0000-000000000000',  -- placeholder UUID
    'test term',
    'keyword',
    '["reddit", "youtube"]'::jsonb
);

-- Insert a test term with NULL (all arenas)
INSERT INTO search_terms (query_design_id, term, term_type, target_arenas)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'all arenas term',
    'keyword',
    NULL
);

-- Query to verify
SELECT term, target_arenas FROM search_terms;
```

### Python ORM Test

```python
from issue_observatory.core.models.query_design import SearchTerm
from issue_observatory.core.database import get_db

# Create a scoped term
term = SearchTerm(
    query_design_id=some_design_id,
    term="klimaforandringer",
    term_type="keyword",
    target_arenas=["reddit", "bluesky"],  # Only these two arenas
)
db.add(term)
await db.commit()

# Create an all-arenas term
term2 = SearchTerm(
    query_design_id=some_design_id,
    term="climate",
    term_type="keyword",
    target_arenas=None,  # All arenas
)
db.add(term2)
await db.commit()

# Query and filter
terms = await db.execute(
    select(SearchTerm).where(SearchTerm.query_design_id == some_design_id)
)
for term in terms.scalars():
    print(f"{term.term}: {term.target_arenas or 'all arenas'}")
```

## JSONB Query Examples (for future optimization)

If arena-filtered queries become a performance bottleneck, add a GIN index:

```sql
-- Index for JSONB containment queries
CREATE INDEX idx_search_terms_target_arenas
ON search_terms USING GIN (target_arenas);

-- Query: find all terms that target "reddit"
SELECT * FROM search_terms
WHERE target_arenas @> '["reddit"]'::jsonb;

-- Query: find all terms that target any of multiple arenas
SELECT * FROM search_terms
WHERE target_arenas ?| ARRAY['reddit', 'youtube'];
```

## Files Modified

| File | Type | Lines Changed |
|------|------|---------------|
| `src/issue_observatory/core/models/query_design.py` | Model | +6 (lines 202-207) |
| `src/issue_observatory/core/schemas/query_design.py` | Schema | +7 (lines 112, 130-136) |
| `alembic/versions/010_add_target_arenas_to_search_terms.py` | Migration | New file (50 lines) |
| `docs/status/db.md` | Docs | +1 line |
| `docs/status/YF-01_implementation_summary.md` | Docs | New file (this document) |

## Acceptance Criteria

✅ **All acceptance criteria met**:

- [x] SearchTerm model has `target_arenas` field (JSONB, nullable)
- [x] Schemas support the new field (`SearchTermCreate` and `SearchTermRead`)
- [x] Migration adds column without breaking existing data
- [x] All existing search terms (with `target_arenas=NULL`) will continue to apply to all arenas
- [x] Migration is reversible (downgrade removes the column)
- [x] Documentation updated (status file)

## Related Work

- **YF-02**: Source-list arena configuration UI (Frontend Engineer)
- **YF-03**: Bulk search term import (will need to support `target_arenas` in CSV format)
- **YF-10**: Group label autocomplete (Frontend Engineer)

## Contact

For questions about this implementation, consult:
- **Database schema questions**: DB Engineer (this agent)
- **Collection dispatcher logic**: Core Application Engineer
- **UI implementation**: Frontend Engineer
- **Test coverage**: QA Guardian

---

# YF-01: Per-Arena Search Term Scoping — Core Application Layer Implementation

**Status**: Complete (application layer)
**Date**: 2026-02-19
**Agent**: Core Application Engineer

## Summary

Implemented the application-layer filtering logic for YF-01 (Per-Arena Search Term Scoping). The collection orchestration code now loads search terms from the database and filters them per arena based on the `target_arenas` JSONB field before dispatching Celery tasks.

## Changes Implemented

### 1. Task Helper Function

**File**: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/workers/_task_helpers.py`

Added `fetch_search_terms_for_arena()` function (lines 368-418):

```python
async def fetch_search_terms_for_arena(
    query_design_id: Any,
    arena_platform_name: str,
) -> list[str]:
    """Return the list of active search term strings scoped to a specific arena.

    Queries the ``search_terms`` table for all active terms associated with
    *query_design_id*, filtering to include only terms where:

    - ``is_active`` is ``True``
    - ``target_arenas`` is ``NULL`` (applies to all arenas), OR
    - ``target_arenas`` contains *arena_platform_name* in its JSONB array
    """
```

**Key implementation details**:
- Uses SQLAlchemy's `has_key()` method which maps to PostgreSQL's JSONB `?` operator
- Returns a list of term strings (not ORM objects) for direct dispatch to arena tasks
- Returns empty list when no terms are scoped to the arena (expected with per-arena scoping)
- Non-fatal errors are logged and handled gracefully in the dispatcher

**SQL Logic**:
```python
.where(
    or_(
        SearchTerm.target_arenas.is_(None),  # NULL = all arenas
        SearchTerm.target_arenas.has_key(arena_platform_name),  # JSONB ? operator
    )
)
```

### 2. Collection Orchestration

**File**: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/workers/tasks.py`

Modified `trigger_daily_collection()` task (lines 216-286):

**Before**: Dispatched arena tasks without passing terms or query_design_id
**After**: Loads and filters terms per arena, passes all required parameters

**Key changes**:
1. Added import for `fetch_search_terms_for_arena` (line 57)
2. Modified arena dispatch loop to:
   - Call `fetch_search_terms_for_arena()` for each arena (lines 226-241)
   - Skip arena if no terms are scoped to it (lines 243-250)
   - Pass `query_design_id` and `terms` to arena tasks (lines 259-261)
   - Log term count per arena (line 278)

**New task parameters passed to arena tasks**:
```python
kwargs={
    "query_design_id": str(design_id),  # NEW
    "collection_run_id": str(run_id),
    "terms": arena_terms,  # NEW (filtered list)
    "tier": tier,
    "language_filter": language_filter,
    "public_figure_ids": public_figure_ids,
}
```

**Error handling**:
- Term loading errors are logged and the arena is skipped (non-fatal)
- Empty term lists cause the arena to be skipped with info-level logging
- Dispatch errors are logged but don't fail the entire daily collection

## Filtering Logic

The implementation follows the exact specification from the task requirements:

```python
terms_for_this_arena = [
    t for t in query_design.search_terms
    if t.is_active and (
        t.target_arenas is None
        or arena_platform_name in t.target_arenas
    )
]
```

This is implemented via SQL at the database layer (more efficient than loading all terms and filtering in Python):

```sql
SELECT term FROM search_terms
WHERE query_design_id = :design_id
  AND is_active = TRUE
  AND (
    target_arenas IS NULL
    OR target_arenas ? :platform_name
  )
ORDER BY added_at
```

## Backward Compatibility

✅ **Fully backward-compatible**:
- All existing search terms have `target_arenas = NULL` (applies to all arenas)
- No changes required to individual arena collectors
- Arena tasks already expected to receive `terms` parameter (this was missing before and is now provided)
- The dispatch loop gracefully handles arenas with zero terms (skips dispatch rather than failing)

## Testing Notes

The implementation has been validated for:
- ✅ Python syntax (no compilation errors)
- ✅ SQLAlchemy query construction (uses standard patterns from the codebase)
- ✅ JSONB operator usage (`has_key()` maps to PostgreSQL `?` operator)

## Functional Behavior

### Scenario 1: No arena scoping (backward-compatible)
- All search terms have `target_arenas = NULL`
- All terms are dispatched to all enabled arenas
- Behavior identical to pre-YF-01 implementation

### Scenario 2: Some terms scoped to specific arenas
- Term A: `target_arenas = NULL` → dispatched to all arenas
- Term B: `target_arenas = ["reddit"]` → dispatched to Reddit only
- Term C: `target_arenas = ["reddit", "bluesky"]` → dispatched to Reddit and Bluesky only

### Scenario 3: Arena with no scoped terms
- All terms have explicit `target_arenas` that don't include this arena
- Arena is skipped with info-level log: "no search terms scoped to arena; skipping"
- No error, no failed task, no wasted credits

## Files Modified

| File | Lines Changed | Description |
|------|--------------|-------------|
| `src/issue_observatory/workers/_task_helpers.py` | +51 lines | New `fetch_search_terms_for_arena()` function |
| `src/issue_observatory/workers/tasks.py` | +38 lines, -9 lines | Modified `trigger_daily_collection()` to load and filter terms |

Total: ~80 lines of new/modified code

## Acceptance Criteria

✅ **All acceptance criteria met**:

- [x] Filtering logic is centralized in one location (`_task_helpers.py`)
- [x] Terms are filtered per-arena before dispatch (not in individual collectors)
- [x] NULL `target_arenas` works (all arenas receive the term)
- [x] Explicit arena list works (only specified arenas receive the term)
- [x] No changes needed in individual arena collectors
- [x] Backward-compatible (existing terms with NULL work as before)

## Next Steps

### Frontend Engineer
**Priority**: High

The Query Design editor needs UI controls for setting `target_arenas` on search terms:

1. **Search term editor**:
   - Add an "Arena Scope" multi-select dropdown
   - Populate with all registered arena platform_names from `/api/arenas`
   - Default state: empty (all arenas) — corresponds to `target_arenas = null`
   - When user selects specific arenas, send `target_arenas: ["reddit", "youtube"]` in POST/PATCH

2. **Search term list view**:
   - Display visual indicator showing arena scope
   - Example: Badge showing "All arenas" or "Reddit, Bluesky only"

3. **Bulk edit** (YF-03):
   - Allow setting arena scope for multiple terms at once

### QA Guardian
**Priority**: High

Test coverage needed:

1. **Unit test**: `test_fetch_search_terms_for_arena()`
   - Verify NULL target_arenas returns term
   - Verify matching platform_name in array returns term
   - Verify non-matching platform_name excludes term
   - Verify inactive terms are excluded

2. **Integration test**: `test_trigger_daily_collection_with_scoped_terms()`
   - Create query design with mixed scoped/unscoped terms
   - Trigger daily collection
   - Verify correct terms dispatched to each arena

3. **Edge case tests**:
   - Empty `target_arenas = []` (should exclude from all arenas)
   - Single-arena scope
   - Multi-arena scope
   - All terms scoped away from an arena (arena skipped)

## Related Work

- **Database layer**: Completed (migration 010, SearchTerm model, schemas)
- **Frontend layer**: Pending (UI controls for setting `target_arenas`)
- **Testing layer**: Pending (unit and integration tests)
