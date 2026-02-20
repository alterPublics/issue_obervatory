# YF Implementation: Required Fixes Before Merge

**Date**: 2026-02-19
**Status**: BLOCKING — 3 critical fixes required

This document outlines the mandatory fixes identified in the QA review of the YF implementation. These must be addressed before the YF PR can be merged to main.

---

## Fix 1: Add Arena Platform Name Validation (CRITICAL-04)

**File**: `src/issue_observatory/api/routes/query_designs.py`
**Lines**: 637, 734 (single term and bulk term endpoints)
**Priority**: HIGH (data integrity)

### Problem
The `target_arenas` field accepts any string values without validation. Researchers can save terms with `target_arenas = ["nonexistent_arena"]`, which will silently exclude the term from all collection runs.

### Fix
Add validation against the arena registry before storing `target_arenas`:

```python
# At the top of query_designs.py, add import:
from issue_observatory.arenas.registry import list_arenas

# In add_search_term() at line 637, replace:
resolved_target_arenas: list[str] | None = None
if target_arenas:
    arenas_list = [a.strip() for a in target_arenas.split(",") if a.strip()]
    if arenas_list:
        resolved_target_arenas = arenas_list

# With:
resolved_target_arenas: list[str] | None = None
if target_arenas:
    arenas_list = [a.strip() for a in target_arenas.split(",") if a.strip()]
    if arenas_list:
        # Validate against registered arenas
        registered_arenas = {arena["platform_name"] for arena in list_arenas()}
        invalid_arenas = [a for a in arenas_list if a not in registered_arenas]
        if invalid_arenas:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid arena platform names: {invalid_arenas}. "
                    f"Must be one of: {sorted(registered_arenas)}"
                ),
            )
        resolved_target_arenas = arenas_list
```

Apply the same fix in `add_search_terms_bulk()` at line 734.

### Test
```python
# tests/integration/test_yf_bulk_imports.py
async def test_bulk_add_search_terms_rejects_invalid_arenas(
    client: AsyncClient, test_user, test_design
):
    """Bulk add rejects terms with non-existent arena names."""
    payload = [
        {"term": "valid", "term_type": "keyword", "target_arenas": ["reddit"]},
        {"term": "invalid", "term_type": "keyword", "target_arenas": ["fake_arena"]},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers={"Authorization": f"Bearer {test_user.id}"},
    )

    assert response.status_code == 422
    assert "fake_arena" in response.json()["detail"]
```

---

## Fix 2: Add GIN Index on target_arenas (MEDIUM-04)

**File**: New migration file `alembic/versions/011_add_gin_index_target_arenas.py`
**Priority**: HIGH (performance)

### Problem
The `target_arenas` column is queried with a JSONB `has_key()` operator in every collection dispatch, but has no GIN index to accelerate JSONB key lookups. This causes sequential scans on the `search_terms` table.

### Fix
Create a new Alembic migration:

```python
"""Add GIN index on search_terms.target_arenas

Revision ID: 011
Revises: 010
Create Date: 2026-02-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add GIN index on target_arenas for efficient JSONB key lookups."""
    op.create_index(
        "ix_search_terms_target_arenas_gin",
        "search_terms",
        ["target_arenas"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove GIN index on target_arenas."""
    op.drop_index(
        "ix_search_terms_target_arenas_gin",
        table_name="search_terms",
    )
```

### Test
Run the migration on a fresh database and verify:
```bash
alembic upgrade head
psql -d issue_observatory -c "\d search_terms"
# Should show: "ix_search_terms_target_arenas_gin" gin (target_arenas)
```

---

## Fix 3: Add Unit Tests for fetch_search_terms_for_arena (MEDIUM-02)

**File**: `tests/unit/test_task_helpers.py` (already created)
**Priority**: HIGH (regression prevention)

### Problem
The core filtering logic in `fetch_search_terms_for_arena()` has no unit tests despite being critical to YF-01 functionality.

### Fix
Tests have been created in `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/tests/unit/test_task_helpers.py`.

### Verification
Run the tests:
```bash
pytest tests/unit/test_task_helpers.py -v
```

All 9 test cases should pass:
- `test_fetch_search_terms_for_arena_null_includes_all`
- `test_fetch_search_terms_for_arena_scoped_includes_only_specified`
- `test_fetch_search_terms_for_arena_excludes_inactive`
- `test_fetch_search_terms_for_arena_returns_empty_for_no_match`
- `test_fetch_search_terms_for_arena_mixed_scoping`
- `test_fetch_search_terms_for_arena_preserves_insertion_order`
- `test_fetch_search_terms_for_arena_empty_design`
- `test_fetch_search_terms_for_arena_nonexistent_design`

---

## Optional Enhancements (Non-blocking)

### Enhancement 1: Add Integration Tests for Bulk Endpoints
**File**: `tests/integration/test_yf_bulk_imports.py` (already created)
**Priority**: MEDIUM

Integration tests for YF-03 and YF-07 bulk import endpoints have been created. Run with:
```bash
pytest tests/integration/test_yf_bulk_imports.py -v
```

### Enhancement 2: Improve Bulk Actor Import Response Schema
**File**: `src/issue_observatory/api/routes/query_designs.py:1293`
**Priority**: LOW

Add a `duplicates_in_request` field to distinguish between:
- Actors already in the list
- Duplicate names within the same bulk import payload

Current response:
```json
{"added": ["John Doe"], "skipped": ["john doe", "JOHN DOE"], "total": 3}
```

Proposed response:
```json
{
  "added": ["John Doe"],
  "skipped": [],
  "duplicates_in_request": ["john doe", "JOHN DOE"],
  "total": 3
}
```

### Enhancement 3: Add Defensive Type Checking for arenas_config
**File**: `src/issue_observatory/api/routes/collections.py:222`
**Priority**: LOW

Replace:
```python
design_arena_config: dict = query_design.arenas_config or {}
```

With:
```python
design_arena_config: dict = (
    query_design.arenas_config
    if isinstance(query_design.arenas_config, dict)
    else {}
)
```

---

## Merge Checklist

Before merging the YF PR, ensure:

- [ ] Fix 1: Arena platform name validation added to both endpoints
- [ ] Fix 2: Migration 011 created and applied
- [ ] Fix 3: Unit tests pass (`pytest tests/unit/test_task_helpers.py`)
- [ ] All existing tests still pass (`pytest`)
- [ ] Integration tests pass (`pytest tests/integration/test_yf_bulk_imports.py`)
- [ ] Migration applies cleanly to production-like database
- [ ] QA review document (`docs/status/qa_yf_review.md`) acknowledged

---

## Post-Merge Tasks (can be done later)

- [ ] Enhancement 1: Add integration tests to CI pipeline
- [ ] Enhancement 2: Improve bulk actor response schema (breaking API change)
- [ ] Enhancement 3: Add defensive JSONB type checking
- [ ] Complete template security review (YF-02, YF-03 Alpine components)
- [ ] Complete analysis routes review (YF-06 endpoints)
- [ ] Update CLAUDE.md with YF implementation status

---

## Sign-off

**QA Guardian**
2026-02-19

Fixes 1-3 are **mandatory blocking issues**. The YF PR must not be merged until these are resolved.
