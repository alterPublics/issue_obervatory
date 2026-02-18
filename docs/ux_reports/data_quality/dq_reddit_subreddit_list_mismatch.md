# Data Quality Finding: Reddit Subreddit List Mismatch Between Code and Documentation

**Identified:** 2026-02-17
**Severity:** Medium
**Responsible agent:** [data]
**Finding reference:** DQ-03 in phase_3_report.md

---

## Summary

The `DANISH_SUBREDDITS` list in source code contains 4 subreddits, while the documentation lists 7. Three subreddits documented as included are not actually in the collection scope.

---

## Technical finding

**File:** `src/issue_observatory/config/danish_defaults.py`, lines 140–151

```python
DANISH_SUBREDDITS: list[str] = [
    "Denmark",
    "danish",
    "copenhagen",
    "aarhus",
]
```

**File:** `docs/guides/what_data_is_collected.md`, line 175

> "The system searches within a predefined set of Danish subreddits: r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkfinance, r/scandinavia, and r/NORDVANSEN."

The three subreddits in the documentation but not in the code:
- `r/dkfinance` — Danish personal finance community
- `r/scandinavia` — Broader Scandinavian community with Danish participation
- `r/NORDVANSEN` — Smaller community

---

## Research impact

A researcher designing a study of Danish Reddit discourse based on the documentation will expect coverage of 7 subreddits. They will actually receive coverage of 4. Studies involving Danish economic or financial discourse (r/dkfinance) or broader Scandinavian framing (r/scandinavia) will be missing relevant data.

The researcher has no way to know this from the UI — the content browser and analysis dashboard do not display which subreddits were searched, only that results came from "reddit".

---

## Recommended fix

Either:
1. Add `"dkfinance"`, `"scandinavia"`, `"NORDVANSEN"` to `DANISH_SUBREDDITS` in `danish_defaults.py` to match the documentation.
2. Or update the documentation to list only the 4 subreddits that are actually implemented.

Note that r/scandinavia and r/NORDVANSEN collect content primarily in English — their inclusion should be deliberate and justified by the research methodology, not accidental. The documentation change (option 2) may be the more conservative and methodologically defensible choice.
