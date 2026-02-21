# IP2-052: Multilingual Query Design Implementation

**Status:** Implemented
**Date:** 2026-02-20
**Implemented by:** Core Application Engineer

## Overview

Implemented IP2-052 (Multilingual query design with bilingual term pairing) to allow researchers to provide translations for search terms when targeting multiple languages. This builds on the existing GR-05 multi-language selector by adding the ability to pair each term with its translated equivalents.

## Changes Made

### 1. Database Migration (Migration 013)

Created `/alembic/versions/013_add_translations_to_search_terms.py`:
- Adds `translations JSONB` column to `search_terms` table
- Column is nullable (NULL = no translations available)
- Stores a dictionary mapping ISO 639-1 language codes to translated term strings
- Example value: `{"kl": "CO2-akilerisitsinnaanera", "en": "CO2 tax"}`

### 2. Model Layer

Updated `/src/issue_observatory/core/models/query_design.py`:
- Added `translations` field to `SearchTerm` model:
  ```python
  translations: Mapped[dict[str, str] | None] = mapped_column(
      JSONB,
      nullable=True,
      comment=(
          "Optional dict mapping ISO 639-1 language codes to translated terms. "
          "NULL = no translations available."
      ),
  )
  ```

### 3. Schema Layer

Updated `/src/issue_observatory/core/schemas/query_design.py`:
- Added `translations` field to `SearchTermCreate` schema:
  ```python
  translations: Optional[dict[str, str]] = Field(
      default=None,
      description=(
          "Optional dict mapping ISO 639-1 language codes to translated terms. "
          "Example: {'kl': 'CO2-akilerisitsinnaanera', 'en': 'CO2 tax'}. "
          "NULL means no translations available (use the primary term)."
      ),
  )
  ```
- `SearchTermRead` inherits this field automatically via inheritance

### 4. API Routes

Updated `/src/issue_observatory/api/routes/query_designs.py`:

#### Single Term Addition (POST /query-designs/{design_id}/terms)
- Added `translations` form parameter (accepts JSON string)
- Parses and validates JSON before persisting
- Returns 422 if JSON is invalid or not a dict with string keys/values

#### Bulk Term Addition (POST /query-designs/{design_id}/terms/bulk)
- Updated to accept and persist `translations` from `SearchTermCreate` schema
- Translations validated by Pydantic at the schema level

#### Query Design Cloning (POST /query-designs/{design_id}/clone)
- Updated to deep-copy `translations` field when cloning search terms
- Ensures cloned query designs preserve all translation data

### 5. Query Builder Integration

Updated `/src/issue_observatory/arenas/query_builder.py`:

#### New Function: `resolve_term_translation`
```python
def resolve_term_translation(
    term_spec: TermSpec,
    target_language: str | None = None,
) -> str:
    """Resolve the appropriate term text based on the target language.

    When target_language is provided and the term has a translation for
    that language, returns the translated term. Otherwise returns the
    primary term value.
    """
```

#### Updated Function: `build_boolean_query_groups`
- Added `target_language` parameter
- Uses `resolve_term_translation` to resolve the appropriate term text
- When `target_language="kl"` and a term has a Greenlandic translation, the Greenlandic term is used in the query groups
- Falls back to primary term when no translation is available

## Usage Example

### Creating a Term with Translations

**Via bulk add (JSON API):**
```json
{
  "term": "CO2 afgift",
  "term_type": "keyword",
  "translations": {
    "kl": "CO2-akilerisitsinnaanera",
    "en": "CO2 tax"
  }
}
```

**Via single term add (form submission):**
```
term=CO2 afgift
translations={"kl": "CO2-akilerisitsinnaanera", "en": "CO2 tax"}
```

### Collection with Translations

When a collection run targets multiple languages via `arenas_config["languages"] = ["da", "kl"]`:

1. Arena collectors receive term specs with translations
2. Query builder is called with `target_language="kl"` for Greenlandic arenas
3. `resolve_term_translation` returns the Greenlandic translation if available
4. Query is built using the translated term

**Example flow:**
```python
term_specs = [
    {
        "term": "CO2 afgift",
        "translations": {"kl": "CO2-akilerisitsinnaanera", "en": "CO2 tax"}
    }
]

# For Danish collection (default)
groups = build_boolean_query_groups(term_specs, target_language="da")
# → [["CO2 afgift"]]

# For Greenlandic collection
groups = build_boolean_query_groups(term_specs, target_language="kl")
# → [["CO2-akilerisitsinnaanera"]]

# For English collection
groups = build_boolean_query_groups(term_specs, target_language="en")
# → [["CO2 tax"]]

# No translation available for Swedish
groups = build_boolean_query_groups(term_specs, target_language="sv")
# → [["CO2 afgift"]]  (falls back to primary term)
```

## Integration Points

### Arena Collectors
Arena collectors need to be updated to:
1. Detect the target language from the query design's `arenas_config["languages"]` or `language` field
2. Pass `target_language` to `build_boolean_query_groups` when building queries
3. This is a **future enhancement** — collectors will continue to work with the primary term until they are updated to support translations

### Frontend
The query design editor will need:
1. A UI control to add/edit translations for each term
2. Language selector showing which languages have translations
3. Visual indicator in the term list showing which terms have translations
4. This is a **frontend task** — the backend is ready to accept and persist translations

## Testing Recommendations

1. **Unit tests for `resolve_term_translation`:**
   - Test fallback to primary term when no translation exists
   - Test correct translation selection for each language code
   - Test case-insensitive language code matching

2. **Unit tests for `build_boolean_query_groups` with translations:**
   - Test translation resolution in simple queries
   - Test translation resolution in boolean AND/OR groups
   - Test fallback behavior when translation is missing

3. **Integration tests for routes:**
   - Test POST /terms with valid translations JSON
   - Test POST /terms with invalid translations JSON (should return 422)
   - Test POST /terms/bulk with translations
   - Test query design cloning preserves translations

4. **Migration test:**
   - Run migration 013 on a test database
   - Verify `translations` column exists and is nullable
   - Create terms with and without translations
   - Verify data persists and retrieves correctly

## Schema Documentation

### translations Field Format

**Type:** JSONB (nullable)

**Structure:**
```typescript
{
  [languageCode: string]: translatedTerm: string
}
```

**Constraints:**
- Language codes should be ISO 639-1 (2-letter) or ISO 639-2 (3-letter) codes
- All keys must be strings
- All values must be strings
- Empty object `{}` is treated as NULL (no translations)
- NULL means no translations available

**Examples:**

Simple translation:
```json
{
  "kl": "CO2-akilerisitsinnaanera"
}
```

Multiple translations:
```json
{
  "kl": "CO2-akilerisitsinnaanera",
  "en": "CO2 tax",
  "sv": "CO2-avgift"
}
```

No translations:
```json
null
```

## Migration Instructions

To apply this migration:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run migration
alembic upgrade head

# Verify migration applied
alembic current
# Should show: 013 (head)
```

## Files Modified

1. `/alembic/versions/013_add_translations_to_search_terms.py` (created)
2. `/src/issue_observatory/core/models/query_design.py`
3. `/src/issue_observatory/core/schemas/query_design.py`
4. `/src/issue_observatory/api/routes/query_designs.py`
5. `/src/issue_observatory/arenas/query_builder.py`

## Status in Implementation Plan 2.0

- **IP2-052:** Multilingual query design → **Implemented**
- Related items:
  - **GR-05:** Multi-language selector → Already implemented (provides the language list)
  - **IP2-052:** Bilingual term pairing → **This implementation**

## Next Steps

1. **Run migration** on development/staging/production databases
2. **Update arena collectors** to use `target_language` parameter when calling query builder
3. **Frontend implementation** to provide UI for adding/editing translations
4. **Documentation** for researchers on how to use multilingual queries
5. **Testing** according to recommendations above
