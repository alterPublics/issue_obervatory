# SB-16: Annotation Codebook Management - API Layer Implementation Report

**Date:** 2026-02-20
**Priority:** P3 (Low)
**Effort:** Medium
**Status:** Partially Complete - Blocked on DB Engineer
**Agent:** Core Application Engineer

---

## Summary

This report documents the implementation of the API layer for annotation codebook management as specified in recommendation SB-16 from the "socialt bedrageri" codebase recommendations.

The codebook feature provides structured qualitative coding for content annotations. Instead of free-text codes, researchers can define and manage a controlled vocabulary of codes with labels, descriptions, and optional categories, either globally or scoped to specific query designs.

---

## Implementation Status

### Completed Components

1. **Pydantic Schemas** (`src/issue_observatory/core/schemas/codebook.py`)
   - `CodebookEntryCreate` - Request schema for creating entries
   - `CodebookEntryUpdate` - Request schema for updating entries
   - `CodebookEntryRead` - Response schema for single entries
   - `CodebookListResponse` - Response schema for list endpoints

2. **API Router** (`src/issue_observatory/api/routes/codebooks.py`)
   - `GET /codebooks` - List all accessible codebook entries (filterable by query_design_id)
   - `GET /codebooks/{codebook_id}` - Get single codebook entry
   - `POST /codebooks` - Create new codebook entry
   - `PATCH /codebooks/{codebook_id}` - Update codebook entry
   - `DELETE /codebooks/{codebook_id}` - Delete codebook entry
   - `GET /query-designs/{design_id}/codebook` - Convenience endpoint for design-scoped entries

3. **Integration with Annotations** (`src/issue_observatory/api/routes/annotations.py`)
   - Added `codebook_entry_id` field to `AnnotationUpsertBody`
   - Implemented mutual exclusivity validation between `frame` and `codebook_entry_id`
   - Added codebook resolution logic (currently stubbed pending model creation)

4. **Application Registration** (`src/issue_observatory/api/main.py`)
   - Registered codebook router at `/codebooks` with `codebooks` tag

---

## Blocking Dependency: CodebookEntry Model

**CRITICAL:** This implementation is blocked on the DB Engineer creating the `CodebookEntry` model.

### Required Model Schema

The DB Engineer must create a `CodebookEntry` model in `src/issue_observatory/core/models/annotations.py` with the following schema:

```python
class CodebookEntry(Base, TimestampMixin):
    """Structured codebook entry for annotation vocabulary control.

    Allows researchers to define controlled vocabularies of codes with
    human-readable labels and descriptions, either globally (admin-only)
    or scoped to specific query designs.
    """

    __tablename__ = "codebook_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Short identifier used in annotations (e.g., "punitive_frame")
    code: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
        index=True,
    )

    # Human-readable display name (e.g., "Punitive Framing")
    label: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )

    # Optional longer explanation
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    # Optional category for grouping (e.g., "stance", "frame")
    category: Mapped[Optional[str]] = mapped_column(
        sa.String(100),
        nullable=True,
        index=True,
    )

    # NULL = global codebook (admin-only), non-NULL = design-scoped
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Creator (for ownership checks)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        # Unique constraint: code must be unique within a query_design_id scope
        sa.UniqueConstraint(
            "query_design_id",
            "code",
            name="uq_codebook_query_design_code",
        ),
    )
```

### Required Migration

The DB Engineer must create an Alembic migration (likely `012_add_codebook_entries.py`) that:

1. Creates the `codebook_entries` table with the schema above
2. Creates indexes on `code`, `category`, `query_design_id`, and `created_by`
3. Creates the unique constraint on `(query_design_id, code)`

### Model Registration

After creating the model, the DB Engineer must add it to `src/issue_observatory/core/models/__init__.py`:

```python
from issue_observatory.core.models.annotations import ContentAnnotation, CodebookEntry

__all__ = [
    # ...existing exports...
    "ContentAnnotation",
    "CodebookEntry",
]
```

---

## Access Control Design

The API implements multi-level access control:

### Non-Admin Users
- Can create codebook entries for query designs they own
- Can read global codebook entries (query_design_id=NULL)
- Can read codebook entries for query designs they own
- Can update/delete only their own codebook entries
- **Cannot** create, update, or delete global codebook entries

### Admin Users
- Can create, read, update, and delete all codebook entries
- Can create global codebook entries (query_design_id=NULL)
- Have full visibility across all query designs

### Ownership Verification
The router includes a helper function `_verify_design_ownership()` that checks:
1. If the current user is an admin, bypass checks
2. If not, verify the query design exists and is owned by the current user
3. Raise 403 if ownership check fails

---

## Codebook Integration with Annotations

When creating or updating an annotation, users can now provide either:

1. **Free-text frame** (existing behavior):
   ```json
   {
     "frame": "punitive_frame",
     "published_at": "2025-01-01T12:00:00Z"
   }
   ```

2. **Codebook entry reference** (new behavior):
   ```json
   {
     "codebook_entry_id": "uuid-of-entry",
     "published_at": "2025-01-01T12:00:00Z"
   }
   ```

When `codebook_entry_id` is provided:
- The API fetches the codebook entry
- Verifies the user has access to it (global or owned design)
- Uses the entry's `code` field to populate the annotation's `frame` field
- This enforces vocabulary consistency

The fields are **mutually exclusive** - providing both will raise a 400 error.

---

## Deletion Policy

When a codebook entry is deleted:
- Annotations that reference its code are **NOT** cascade deleted
- Those annotations become "orphaned" - the code string remains but has no codebook definition
- This preserves annotation data while allowing codebook evolution

Rationale: Codebooks may evolve during research, but coding decisions already made should be preserved for audit and analysis purposes.

---

## Error Handling

The API provides helpful error messages for common scenarios:

1. **Duplicate code within scope** (400):
   ```
   A codebook entry with code 'punitive_frame' already exists in this scope.
   Codes must be unique within a query design.
   ```

2. **Global entry creation by non-admin** (403):
   ```
   Only administrators can create global codebook entries.
   ```

3. **Modifying entry without ownership** (403):
   ```
   You do not have permission to modify this codebook entry.
   ```

4. **Using both frame and codebook_entry_id** (400):
   ```
   Cannot provide both 'frame' and 'codebook_entry_id'. Use one or the other.
   ```

5. **Codebook entry not found** (404):
   ```
   Codebook entry '{uuid}' not found.
   ```

---

## Current State of Implementation

All API routes are implemented but **currently return placeholder responses** with HTTP 501 (Not Implemented) or empty lists. The actual database operations are commented out with `# FIXME: Uncomment once CodebookEntry model exists` markers.

Once the DB Engineer creates the model and migration:

1. Uncomment all `# FIXME` blocks in `src/issue_observatory/api/routes/codebooks.py`
2. Uncomment the codebook resolution logic in `src/issue_observatory/api/routes/annotations.py`
3. Import the `CodebookEntry` model at the top of both files
4. Run the migration: `alembic upgrade head`
5. Test all endpoints with the test suite

---

## Testing Plan (Post-Model Creation)

Once the model exists, the following tests should be created in `tests/routes/test_codebooks.py`:

1. **List codebooks**
   - As non-admin: returns global + owned entries
   - As admin: returns all entries
   - Filtered by query_design_id

2. **Get single codebook entry**
   - Retrieve global entry
   - Retrieve owned entry
   - Reject access to other user's design-scoped entry

3. **Create codebook entry**
   - Non-admin creates design-scoped entry
   - Admin creates global entry
   - Non-admin rejected from creating global entry
   - Unique constraint violation returns 400

4. **Update codebook entry**
   - Update owned entry
   - Admin can update any entry
   - Non-admin rejected from updating others' entries
   - Code change logged with warning

5. **Delete codebook entry**
   - Delete owned entry
   - Admin can delete any entry
   - Annotations referencing deleted code are orphaned (not cascade deleted)

6. **Integration with annotations**
   - Create annotation with codebook_entry_id
   - Reject when both frame and codebook_entry_id provided
   - Reject invalid codebook_entry_id

---

## API Documentation

The OpenAPI schema will automatically document the `/codebooks` endpoints once the router is active. All endpoints include detailed docstrings and Pydantic schema descriptions for:

- Parameter validation
- Response models
- Error responses
- Authentication requirements

The endpoints will appear under the `codebooks` tag in the Swagger UI at `/docs`.

---

## Next Steps

1. **DB Engineer**: Create `CodebookEntry` model and migration
2. **DB Engineer**: Add model to `__init__.py` exports
3. **DB Engineer**: Run migration on development database
4. **Core Application Engineer**: Uncomment all FIXME blocks once model exists
5. **QA Engineer**: Write comprehensive test suite for codebook endpoints
6. **Frontend Engineer**: Build UI for codebook management (separate task: SB-16 UI layer)

---

## Files Modified

- `src/issue_observatory/core/schemas/codebook.py` (created)
- `src/issue_observatory/api/routes/codebooks.py` (created)
- `src/issue_observatory/api/routes/annotations.py` (modified)
- `src/issue_observatory/api/main.py` (modified)
- `src/issue_observatory/core/schemas/__init__.py` (modified)

---

## Related Work

- **SB-16 UI Layer** (not yet started): Frontend interface for codebook management
- **IP2-043** (completed): Content annotation layer (foundation for codebook feature)

---

## Conclusion

The API layer for codebook management is architecturally complete but functionally blocked on database model creation. All route handlers, schemas, access control logic, and error handling are implemented and ready for activation once the `CodebookEntry` model exists.

The implementation follows established patterns:
- Pydantic v2 schemas with proper validation
- Async route handlers with dependency injection
- Ownership guards for resource isolation
- Structured logging with contextual information
- Helpful error messages for common scenarios
- Comprehensive docstrings for maintainability

Once the blocking dependency is resolved, the feature will be fully functional and ready for UI integration.
