# Data Quality Finding: Bluesky Actor-Based Collection Has No Language Filter

**Identified:** 2026-02-17
**Severity:** High
**Responsible agent:** [data]
**Finding reference:** DQ-01 in phase_3_report.md

---

## Summary

The `BlueskyCollector.collect_by_actors()` method retrieves all posts from an actor's feed within the specified date range, without applying any language filter. This contradicts the documentation, which states that `lang:da` is applied to Bluesky collection.

---

## Technical finding

**File:** `src/issue_observatory/arenas/bluesky/collector.py`

`collect_by_terms()` correctly applies `"lang": DANISH_LANG` at line 458:
```python
params: dict[str, Any] = {
    "q": term,
    "lang": DANISH_LANG,
    "limit": page_size,
}
```

`collect_by_actors()` delegates to `_fetch_author_feed()`, which applies no language filter:
```python
params: dict[str, Any] = {"actor": actor, "limit": page_size}
if cursor:
    params["cursor"] = cursor
```

The AT Protocol `getAuthorFeed` endpoint does not support a `lang` parameter at the API level — this is an inherent API limitation, not a developer omission. However, client-side filtering by the `language` field of collected posts would be possible.

---

## Documentation contradiction

`docs/guides/what_data_is_collected.md`, Bluesky section, line 137:
> "The search query is appended with `lang:da` to request Danish-language posts."

This statement is accurate only for term-based collection. It is misleading when actor-based collection is also documented in the same paragraph, because actor-based collection cannot apply this filter at the API level and does not apply it client-side either.

---

## Research impact

A researcher who sets up actor-based Bluesky collection for five Danish politicians will collect every post from those accounts, including:
- English-language posts (reposted international content, travel posts, etc.)
- Posts in other languages (if any actors write in multiple languages)

The language column in the collected records will reflect the actual language declared by the post. A researcher filtering by `language=da` in the content browser will find the correct records, but the raw export will include multilingual content. More importantly, the researcher was not warned about this limitation when setting up the collection.

## Recommended fix

1. Update the documentation to accurately state: "Actor-based Bluesky collection retrieves all posts from the actor's public feed. Language filtering is not available at the API level for author feeds. Posts in languages other than Danish will be included and can be filtered post-collection using the Language filter in the content browser."

2. Optionally, add client-side language filtering in `_fetch_author_feed()`:
```python
# After normalization:
normalized = self.normalize(post)
lang = normalized.get("language") or ""
if lang and lang != "da":
    continue  # or collect with a flag
records.append(normalized)
```
This would reduce records but would silently drop posts from multilingual accounts that post in Danish. The trade-off should be a configurable option, not a hardcoded filter.
