# Bulk Actor Import (YF-07)

## Overview

The bulk actor import feature allows researchers to add multiple actors to a query design at once, rather than adding them one by one through the single-actor form.

## Location

Query Design Editor → Actor List panel → "Bulk Add" button

## Supported Formats

### Simple Format

One actor name per line. All actors default to `person` type.

```
Lars Løkke Rasmussen
Mette Frederiksen
Pernille Vermund
```

### Structured Format

Pipe-delimited: `name | type`

```
Lars Løkke Rasmussen | person
Socialdemokratiet | political_party
DR | media_outlet
Undervisningsministeriet | government_body
DLF | teachers_union
```

## Valid Actor Types

- `person`
- `organization`
- `political_party`
- `educational_institution`
- `teachers_union`
- `think_tank`
- `media_outlet`
- `government_body`
- `ngo`
- `company`
- `unknown`

## Comments and Empty Lines

- Lines starting with `#` are treated as comments and ignored
- Empty lines are skipped

```
# Danish political leaders
Lars Løkke Rasmussen | person
Mette Frederiksen | person

# Political parties
Socialdemokratiet | political_party
Venstre | political_party
```

## Backend Endpoint

`POST /query-designs/{design_id}/actors/bulk`

**Request Body:**
```json
[
  {"name": "Lars Løkke Rasmussen", "actor_type": "person"},
  {"name": "Socialdemokratiet", "actor_type": "political_party"}
]
```

**Response:**
```json
{
  "added": ["Lars Løkke Rasmussen"],
  "skipped": ["Socialdemokratiet"],
  "actor_ids": ["uuid-1", "uuid-2"],
  "total": 2
}
```

## Behavior

1. **Duplicate Detection**: Actors already in the list are skipped (no error raised)
2. **Atomic Operation**: All actors are validated before any are inserted
3. **Canonical Actor Records**: All actors are linked to the Actor Directory for cross-query tracking and snowball sampling
4. **Success Message**: Shows count of added and skipped actors
5. **Page Reload**: After successful import, the page reloads to display all new actors

## Error Handling

- Empty actor names are rejected with line number reference
- Invalid actor types show a detailed error with valid options
- Backend validation errors are displayed inline
- On error, the textarea is not cleared (allows user to fix and retry)

## UI States

- **Loading**: Import button shows spinner and "Importing..." text
- **Success**: Green message with counts, textarea clears, page reloads after 800ms
- **Error**: Red message with specific line number and issue
- **Clear**: Button to reset textarea and clear any messages

## Implementation Files

- **Template**: `src/issue_observatory/api/templates/query_designs/editor.html`
  - HTML: Lines 435-547 (bulk actor form)
  - JavaScript: Lines 2034-2167 (`bulkActorImport` Alpine component)
- **Backend Route**: `src/issue_observatory/api/routes/query_designs.py`
  - Endpoint: `add_actors_to_design_bulk` (line 1404)
  - Schema: `ActorBulkItem`, `ActorBulkAddResponse` (lines 1259-1288)

## Testing

To test manually:
1. Navigate to a query design editor
2. Click "Bulk Add" in the Actor List panel
3. Paste test data in the textarea
4. Click "Import Actors"
5. Verify success message and page reload

Sample test data:
```
# Test actors for ytringsfrihed project
Lars Løkke Rasmussen | person
Mette Frederiksen | person
Socialdemokratiet | political_party
DLF | teachers_union
Undervisningsministeriet | government_body
DR | media_outlet
TV2 | media_outlet
```
