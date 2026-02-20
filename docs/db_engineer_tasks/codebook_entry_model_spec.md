# DB Engineer Task: CodebookEntry Model Creation

**Blocking:** SB-16 Codebook Management API
**Priority:** P3 (Low)
**Assignee:** DB Engineer
**Created:** 2026-02-20

---

## Task Overview

Create the `CodebookEntry` model and associated Alembic migration to support structured qualitative coding for content annotations. This is a dependency for the completed API layer in SB-16.

---

## Model Specification

### File Location
`src/issue_observatory/core/models/annotations.py`

### Model Code

```python
class CodebookEntry(Base, TimestampMixin):
    """Structured codebook entry for annotation vocabulary control.

    Allows researchers to define controlled vocabularies of codes with
    human-readable labels and descriptions, either globally (admin-only)
    or scoped to specific query designs.

    Attributes:
        id: UUID primary key.
        code: Short identifier used in annotations (e.g., "punitive_frame").
            Max 100 characters. Indexed.
        label: Human-readable display name (e.g., "Punitive Framing").
            Max 200 characters.
        description: Optional longer explanation of when to apply this code.
        category: Optional grouping label (e.g., "stance", "frame").
            Max 100 characters. Indexed.
        query_design_id: UUID of the owning query design. NULL = global
            codebook entry (admin-only). FK to query_designs.id with
            CASCADE delete. Indexed.
        created_by: UUID of the user who created this entry. FK to users.id
            with SET NULL on delete. Indexed.
        created_at: Auto-populated creation timestamp.
        updated_at: Auto-updated modification timestamp.
    """

    __tablename__ = "codebook_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    code: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

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
        # Unique constraint: code must be unique within a query_design_id scope.
        # This allows the same code to appear in different query designs or
        # as both a global entry and design-scoped entries.
        sa.UniqueConstraint(
            "query_design_id",
            "code",
            name="uq_codebook_query_design_code",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CodebookEntry id={self.id} "
            f"code={self.code!r} "
            f"query_design_id={self.query_design_id}>"
        )
```

### Import Requirements

At the top of `annotations.py`:
```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base, TimestampMixin
```

---

## Migration Specification

### File Name
`alembic/versions/012_add_codebook_entries.py`

### Migration Content

```python
"""add codebook entries

Revision ID: 012
Revises: 011
Create Date: 2026-02-20

Adds the codebook_entries table to support structured qualitative coding
for content annotations. Codebook entries define controlled vocabularies
with human-readable labels and descriptions, either globally (admin-only)
or scoped to specific query designs.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'codebook_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('query_design_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['query_design_id'],
            ['query_designs.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['created_by'],
            ['users.id'],
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'query_design_id',
            'code',
            name='uq_codebook_query_design_code',
        ),
    )

    # Indexes
    op.create_index(
        'ix_codebook_entries_code',
        'codebook_entries',
        ['code'],
    )
    op.create_index(
        'ix_codebook_entries_category',
        'codebook_entries',
        ['category'],
    )
    op.create_index(
        'ix_codebook_entries_query_design_id',
        'codebook_entries',
        ['query_design_id'],
    )
    op.create_index(
        'ix_codebook_entries_created_by',
        'codebook_entries',
        ['created_by'],
    )


def downgrade() -> None:
    op.drop_index('ix_codebook_entries_created_by', table_name='codebook_entries')
    op.drop_index('ix_codebook_entries_query_design_id', table_name='codebook_entries')
    op.drop_index('ix_codebook_entries_category', table_name='codebook_entries')
    op.drop_index('ix_codebook_entries_code', table_name='codebook_entries')
    op.drop_table('codebook_entries')
```

---

## Model Registration

After creating the model, update `src/issue_observatory/core/models/__init__.py`:

```python
# Add to imports at top of file
from issue_observatory.core.models.annotations import ContentAnnotation, CodebookEntry

# Add to __all__ list
__all__ = [
    # ...existing exports...
    "ContentAnnotation",
    "CodebookEntry",  # Add this line
]
```

---

## Schema Constraints

### Unique Constraint Behavior

The unique constraint on `(query_design_id, code)` allows:
- ✅ Same code in different query designs (scoped isolation)
- ✅ Same code as both global and design-scoped (global acts as default)
- ❌ Duplicate code within the same query design (enforced uniqueness)

### NULL Handling

- `query_design_id=NULL` represents a **global codebook entry**
- Only admins can create/modify global entries (enforced at API layer)
- Global entries are visible to all users
- PostgreSQL treats NULL values as distinct in UNIQUE constraints, so multiple global entries with the same code are possible (API layer should prevent this)

### Cascade Behavior

- `query_design_id`: CASCADE delete - when a query design is deleted, all its codebook entries are deleted
- `created_by`: SET NULL on delete - preserve codebook entries for audit even if creator is deleted

---

## Testing Checklist

After creating the model and migration:

1. ✅ Run `alembic upgrade head` successfully
2. ✅ Verify table exists in PostgreSQL: `\d codebook_entries`
3. ✅ Verify all indexes exist
4. ✅ Verify unique constraint exists
5. ✅ Test INSERT with duplicate (query_design_id, code) - should fail
6. ✅ Test INSERT with same code in different designs - should succeed
7. ✅ Test CASCADE delete when query design is deleted
8. ✅ Test SET NULL when user is deleted
9. ✅ Model imports successfully: `from issue_observatory.core.models import CodebookEntry`

---

## API Integration Steps (Post-Model Creation)

After the model is created, the Core Application Engineer will:

1. Uncomment all `# FIXME` blocks in `src/issue_observatory/api/routes/codebooks.py`
2. Uncomment codebook resolution logic in `src/issue_observatory/api/routes/annotations.py`
3. Add model imports to both router files
4. Verify all 6 endpoints work correctly

---

## Questions?

- See full API implementation in `src/issue_observatory/api/routes/codebooks.py`
- See API documentation in `docs/implementation_reports/SB-16_codebook_management_api.md`
- Contact Core Application Engineer for API layer questions
- This task is blocked by this model creation - API layer is complete but inactive

---

## Related Documentation

- API implementation report: `docs/implementation_reports/SB-16_codebook_management_api.md`
- Original recommendation: `docs/research_reports/socialt_bedrageri_codebase_recommendations.md` (SB-16)
- Annotation model: `src/issue_observatory/core/models/annotations.py` (ContentAnnotation)
