# YF-07 Bulk Actor Import - Test Plan

## Test Cases

### 1. Happy Path - Add Multiple New Actors

**Setup:**
- Create a query design owned by test user
- Empty actor list

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "Actor One", "actor_type": "person"},
  {"name": "Actor Two", "actor_type": "organization"},
  {"name": "Actor Three", "actor_type": "media_outlet"}
]
```

**Expected Response:**
```json
{
  "added": ["Actor One", "Actor Two", "Actor Three"],
  "skipped": [],
  "actor_ids": ["<uuid1>", "<uuid2>", "<uuid3>"],
  "total": 3
}
```

**Verification:**
- 3 new Actor records created in database
- 3 new ActorListMember records with `added_by="bulk_import"`
- All actors visible in Actor Directory
- All actors appear in query design's actor list

---

### 2. Partial Duplicates - Skip Existing Actors

**Setup:**
- Create a query design with "Actor One" already in the list

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "Actor One", "actor_type": "person"},
  {"name": "Actor Two", "actor_type": "organization"}
]
```

**Expected Response:**
```json
{
  "added": ["Actor Two"],
  "skipped": ["Actor One"],
  "actor_ids": ["<existing_uuid>", "<new_uuid>"],
  "total": 2
}
```

**Verification:**
- Only 1 new Actor record created
- Only 1 new ActorListMember record
- No duplicate memberships in database

---

### 3. Case-Insensitive Matching

**Setup:**
- Create Actor named "lars løkke rasmussen" (lowercase)

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "Lars Løkke Rasmussen", "actor_type": "person"}
]
```

**Expected Response:**
```json
{
  "added": [],
  "skipped": ["lars løkke rasmussen"],
  "actor_ids": ["<existing_uuid>"],
  "total": 1
}
```

**Verification:**
- No new Actor record created
- Existing actor linked to the list

---

### 4. Empty Request Body

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[]
```

**Expected Response:** HTTP 400
```json
{
  "detail": "Request body must contain at least one actor."
}
```

---

### 5. Empty Actor Name

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "   ", "actor_type": "person"}
]
```

**Expected Response:** HTTP 422
```json
{
  "detail": "Actor name must not be empty: '   '"
}
```

---

### 6. Non-Existent Query Design

**Request:**
```json
POST /query-designs/00000000-0000-0000-0000-000000000000/actors/bulk
[
  {"name": "Actor One", "actor_type": "person"}
]
```

**Expected Response:** HTTP 404
```json
{
  "detail": "Query design '00000000-0000-0000-0000-000000000000' not found."
}
```

---

### 7. Ownership Guard - Wrong User

**Setup:**
- User A creates a query design
- User B tries to add actors to User A's design

**Request:** (as User B)
```json
POST /query-designs/{user_a_design_id}/actors/bulk
[
  {"name": "Actor One", "actor_type": "person"}
]
```

**Expected Response:** HTTP 403
```json
{
  "detail": "Access denied."
}
```

---

### 8. Default Actor Type

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "Actor Without Type"}
]
```

**Expected Response:**
```json
{
  "added": ["Actor Without Type"],
  "skipped": [],
  "actor_ids": ["<uuid>"],
  "total": 1
}
```

**Verification:**
- Actor created with `actor_type="person"` (default)

---

### 9. Atomicity - All or Nothing Validation

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "Valid Actor", "actor_type": "person"},
  {"name": "   ", "actor_type": "person"}
]
```

**Expected Response:** HTTP 422
```json
{
  "detail": "Actor name must not be empty: '   '"
}
```

**Verification:**
- NO Actor records created (transaction rolled back)
- "Valid Actor" not added to the list

---

### 10. Large Batch (15 Actors)

**Request:**
```json
POST /query-designs/{design_id}/actors/bulk
[
  {"name": "Actor 01", "actor_type": "person"},
  {"name": "Actor 02", "actor_type": "person"},
  ...
  {"name": "Actor 15", "actor_type": "person"}
]
```

**Expected Response:**
```json
{
  "added": ["Actor 01", "Actor 02", ..., "Actor 15"],
  "skipped": [],
  "actor_ids": ["<uuid1>", ..., "<uuid15>"],
  "total": 15
}
```

**Verification:**
- All 15 actors created efficiently
- Single transaction commit

---

## Performance Benchmarks

### Expected Performance
- **15 actors (all new):** < 500ms
- **15 actors (all existing):** < 300ms
- **Mixed (7 new, 8 existing):** < 400ms

### Database Operations
- Single query for ActorList lookup
- One query per actor for name lookup
- Bulk insert of ActorListMember records
- Single commit at the end

### Optimizations Implemented
- ActorList retrieved once (not per actor)
- Actor lookup uses case-insensitive index
- Membership checks done in Python (not individual DB queries)
- Bulk commit instead of per-actor commits

---

## Integration Test Template (pytest)

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_bulk_actor_import_happy_path(
    client: AsyncClient,
    auth_token: str,
    query_design_id: str
):
    actors = [
        {"name": "Lars Løkke Rasmussen", "actor_type": "person"},
        {"name": "Socialdemokratiet", "actor_type": "political_party"},
    ]

    response = await client.post(
        f"/query-designs/{query_design_id}/actors/bulk",
        headers={"Authorization": f"Bearer {auth_token}"},
        json=actors
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data["added"]) == 2
    assert len(data["skipped"]) == 0
    assert data["total"] == 2
    assert len(data["actor_ids"]) == 2
```

---

## Manual Testing Steps

1. **Setup:**
   - Start the FastAPI server
   - Create a test user and authenticate
   - Create a new query design

2. **Test bulk import:**
   ```bash
   curl -X POST "http://localhost:8000/query-designs/{design_id}/actors/bulk" \
     -H "Authorization: Bearer {token}" \
     -H "Content-Type: application/json" \
     -d '[
       {"name": "Test Actor 1", "actor_type": "person"},
       {"name": "Test Actor 2", "actor_type": "organization"}
     ]'
   ```

3. **Verify in UI:**
   - Navigate to `/query-designs/{design_id}`
   - Confirm both actors appear in the actor list
   - Click "Profile" link to verify Actor Directory entries

4. **Test duplicate handling:**
   - Re-run the same curl command
   - Verify response shows both actors in "skipped" field
   - Confirm no duplicate entries in the UI

---

## Success Criteria

✅ All 10 test cases pass
✅ Performance benchmarks met
✅ No N+1 query issues
✅ Proper error messages for invalid input
✅ Ownership guards enforced
✅ Atomicity maintained (transaction rollback on error)
✅ Integration with existing Actor Directory
✅ Follows same pattern as YF-03 bulk term import
