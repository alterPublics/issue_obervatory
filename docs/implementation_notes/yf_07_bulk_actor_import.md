# YF-07: Bulk Actor Import - Implementation Summary

## Status: COMPLETE

**Date**: 2026-02-19
**Component**: Frontend UI
**Backend**: Already implemented (see YF-07 backend task)

## Overview

Added a bulk import UI to the query design editor's actor panel, allowing researchers to import multiple actors at once using a textarea with structured or simple format.

## Implementation Details

### 1. Frontend Template Changes

**File**: `src/issue_observatory/api/templates/query_designs/editor.html`

**Changes Made:**

#### a) Actor Form UI (lines 435-547)
- Replaced single actor form with a toggle between "Single Add" and "Bulk Add" modes
- Added Alpine.js `x-data="{ bulkMode: false }"` wrapper
- Preserved existing single-actor form functionality with `x-show="!bulkMode"`
- Added new bulk import panel with `x-show="bulkMode"` and `x-data="bulkActorImport()"`

**Bulk Import Panel Features:**
- Textarea with 8 rows and format-aware placeholder text
- Format help box explaining simple and structured formats
- Clear button to reset textarea
- Import button with loading state (spinner + disabled state)
- Success/error message display areas
- Transition animations for status messages

#### b) Alpine.js Component (lines 2034-2167)
- Created `bulkActorImport()` function returning Alpine component
- Implements parser for two input formats:
  - **Simple**: `name` → defaults to "person" type
  - **Structured**: `name | type` → explicit type specification

**Component State:**
```javascript
{
  bulkInput: '',      // Textarea content
  importing: false,   // Loading state
  bulkSuccess: null,  // Success message
  bulkError: null     // Error message
}
```

**Key Methods:**
- `submitBulkActors()` - Main submission handler
  - Parses textarea line-by-line
  - Validates each actor (name non-empty, type valid)
  - POSTs to `/query-designs/{design_id}/actors/bulk`
  - Shows success/error messages
  - Reloads page on success (800ms delay)
- `parseLine(line)` - Format parser
  - Detects simple vs structured format (presence of `|`)
  - Validates actor type against 11 valid types
  - Returns `{name, actor_type}` object
- `clearInput()` - Reset textarea and messages

### 2. Format Specifications

#### Simple Format
```
Lars Løkke Rasmussen
Mette Frederiksen
```
Defaults all actors to `person` type.

#### Structured Format
```
Lars Løkke Rasmussen | person
Socialdemokratiet | political_party
DR | media_outlet
Undervisningsministeriet | government_body
```

#### Comment Support
```
# Danish political leaders
Lars Løkke Rasmussen | person
Mette Frederiksen | person

# Political parties
Socialdemokratiet | political_party
```

Lines starting with `#` are ignored, empty lines are skipped.

### 3. Valid Actor Types

The UI validates against 11 actor types:
1. `person`
2. `organization`
3. `political_party`
4. `educational_institution`
5. `teachers_union`
6. `think_tank`
7. `media_outlet`
8. `government_body`
9. `ngo`
10. `company`
11. `unknown`

### 4. User Experience Flow

1. **Initial State**: Single-actor form visible by default
2. **Switch to Bulk**: Click "Bulk Add" button
3. **Enter Data**: Paste/type actors in textarea (simple or structured format)
4. **Submit**: Click "Import Actors"
5. **Validation**: Frontend validates format before sending
6. **Backend Processing**: Server validates, creates/links actors, skips duplicates
7. **Success Feedback**: Shows "Added X actors, skipped Y duplicates"
8. **Page Reload**: Refreshes to display new actors (800ms delay for user to see message)

### 5. Error Handling

**Frontend Validation Errors:**
- Empty actor name: "Actor name must not be empty"
- Invalid actor type: "Invalid actor type: {type}. Must be one of: {list}"
- No valid lines: "No valid actors found. Add at least one actor."

**Backend Errors:**
- HTTP error responses displayed with line number context
- Textarea preserved on error (allows user to fix and retry)

**Success States:**
- Added only: "Added 5 actors"
- Added + skipped: "Added 3 actors, skipped 2 duplicates"

### 6. Backend Integration

**Endpoint**: `POST /query-designs/{design_id}/actors/bulk`

**Request Format:**
```json
[
  {"name": "Actor Name", "actor_type": "person"}
]
```

**Response Format:**
```json
{
  "added": ["Actor 1", "Actor 2"],
  "skipped": ["Actor 3"],
  "actor_ids": ["uuid-1", "uuid-2", "uuid-3"],
  "total": 3
}
```

Backend behavior:
- Validates all actors before inserting any
- Creates/links canonical `Actor` records (synchronizes with Actor Directory)
- Skips duplicates (no error raised)
- Atomic operation (all-or-nothing)

## Design Pattern

This implementation follows the same pattern as YF-03 (bulk term import):
- Toggle between single/bulk modes
- Alpine.js component for client-side logic
- Format help text with examples
- Inline validation with line-number errors
- Success messages with counts
- Page reload to refresh UI state

## Testing Checklist

- [ ] Toggle between single and bulk modes
- [ ] Simple format (name only)
- [ ] Structured format (name | type)
- [ ] Comment lines (# prefix)
- [ ] Empty lines
- [ ] Invalid actor type error
- [ ] Empty actor name error
- [ ] Duplicate actor handling (skipped count)
- [ ] Clear button functionality
- [ ] Loading state (spinner + disabled button)
- [ ] Success message display
- [ ] Error message display
- [ ] Page reload on success

## Files Modified

1. `src/issue_observatory/api/templates/query_designs/editor.html`
   - Lines 435-547: HTML template changes
   - Lines 2034-2167: Alpine.js component

## Documentation Added

1. `docs/features/bulk_actor_import.md` - User-facing feature guide
2. `docs/implementation_notes/yf_07_bulk_actor_import.md` - This file

## Related Tasks

- **YF-07 Backend**: Bulk actor import endpoint (completed separately)
- **YF-03**: Bulk term import (pattern reference)
- **IP2-007**: Actor synchronization (ensures actors sync to Actor Directory)

## Known Limitations

- No inline preview of parsed actors before submission
- No incremental validation (all-or-nothing parsing)
- Page reload required to see new actors (could use HTMX for dynamic updates)
- No undo functionality

## Future Enhancements

Consider for future improvements:
- Real-time validation as user types
- Preview table of parsed actors before submission
- HTMX-based dynamic actor list updates (avoid full page reload)
- CSV/JSON file upload support
- Actor list templates (save/load common actor groups)
