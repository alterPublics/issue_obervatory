# Bulk Actor Import API (YF-07)

## Overview

The bulk actor import endpoint allows researchers to add 8-15 seed actors to a query design in a single request, eliminating the tedious process of adding them one by one through the UI.

## Endpoint

```
POST /query-designs/{design_id}/actors/bulk
```

## Request Schema

### ActorBulkItem

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Actor's canonical name |
| `actor_type` | string | No | `"person"` | Actor type classification |

### Valid Actor Types

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

## Request Body

```json
[
  {
    "name": "Lars Løkke Rasmussen",
    "actor_type": "person"
  },
  {
    "name": "Socialdemokratiet",
    "actor_type": "political_party"
  },
  {
    "name": "Folkeskolen",
    "actor_type": "media_outlet"
  }
]
```

## Response Schema

### ActorBulkAddResponse

| Field | Type | Description |
|-------|------|-------------|
| `added` | list[string] | List of actor names successfully added to the query design |
| `skipped` | list[string] | List of actor names already in the list (not duplicated) |
| `actor_ids` | list[string] | UUIDs of all actors (added or skipped) |
| `total` | integer | Total number of items processed |

## Response Example

```json
{
  "added": [
    "Lars Løkke Rasmussen",
    "Socialdemokratiet",
    "Folkeskolen"
  ],
  "skipped": [],
  "actor_ids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f678-90ab-cdef-123456789012",
    "c3d4e5f6-7890-abcd-ef12-34567890abcd"
  ],
  "total": 3
}
```

## Behavior

1. **Ownership validation**: Verifies the authenticated user owns the query design.

2. **Actor lookup/creation**: For each actor in the request:
   - Strips and validates the name is not empty
   - Searches for an existing Actor record (case-insensitive name match)
   - Priority: user-owned actors → shared actors → create new
   - Creates new Actor records as `is_shared=False`

3. **Actor list membership**:
   - Adds actors to the query design's "Default" ActorList
   - Skips actors already in the list (no error raised)
   - All memberships are marked with `added_by="bulk_import"`

4. **Atomicity**: All changes are committed in a single transaction.

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Request body must contain at least one actor."
}
```

### 403 Forbidden

```json
{
  "detail": "Access denied."
}
```

### 404 Not Found

```json
{
  "detail": "Query design '{design_id}' not found."
}
```

### 422 Unprocessable Entity

```json
{
  "detail": "Actor name must not be empty: '   '"
}
```

## Usage Example (cURL)

```bash
curl -X POST "http://localhost:8000/query-designs/{design_id}/actors/bulk" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "name": "Lars Løkke Rasmussen",
      "actor_type": "person"
    },
    {
      "name": "Socialdemokratiet",
      "actor_type": "political_party"
    }
  ]'
```

## Usage Example (Python)

```python
import httpx

async def bulk_import_actors(design_id: str, actors: list[dict], token: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"http://localhost:8000/query-designs/{design_id}/actors/bulk",
            headers={"Authorization": f"Bearer {token}"},
            json=actors
        )
        response.raise_for_status()
        return response.json()

# Example usage
actors = [
    {"name": "Lars Løkke Rasmussen", "actor_type": "person"},
    {"name": "Socialdemokratiet", "actor_type": "political_party"},
    {"name": "Folkeskolen", "actor_type": "media_outlet"},
]

result = await bulk_import_actors(
    design_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    actors=actors,
    token="your-jwt-token"
)

print(f"Added {len(result['added'])} actors")
print(f"Skipped {len(result['skipped'])} existing actors")
```

## Related Endpoints

- `POST /query-designs/{design_id}/actors` - Add a single actor (HTML form endpoint)
- `DELETE /query-designs/{design_id}/actors/{actor_id}` - Remove an actor
- `GET /query-designs/{design_id}/actor-lists` - List actor lists for a design
- `POST /actors/quick-add-bulk` - Bulk add actors with platform presences (different use case)

## Implementation Notes

This endpoint follows the same pattern as `POST /query-designs/{design_id}/terms/bulk` (YF-03), providing a JSON API for bulk operations while the single-actor endpoint remains form-based for HTMX compatibility.

Actor records created through this endpoint:
- Are visible in the Actor Directory (`/actors`)
- Are available as seeds for snowball sampling
- Can be enriched with platform presences later
- Have stable UUIDs for cross-design sharing
