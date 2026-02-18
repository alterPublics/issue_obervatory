# Data Quality Finding: GEXF Edge Construction is Methodologically Incorrect

**Identified:** 2026-02-17
**Severity:** Critical
**Responsible agent:** [core]
**Finding reference:** DQ-02 in phase_3_report.md

---

## Summary

The actor co-occurrence network exported as GEXF does not implement co-occurrence. It implements full-graph connectivity across all authors within a collection run. The implementation is internally consistent but methodologically wrong.

---

## Technical finding

**File:** `src/issue_observatory/analysis/export.py`, lines 379–412

The `export_gexf()` method builds its edge map as follows:

```python
run_authors: dict[str, set[str]] = defaultdict(set)
run_terms: dict[str, set[str]] = defaultdict(set)

for rec in records:
    author_id = rec.get("pseudonymized_author_id")
    run_id = str(rec.get("collection_run_id") or "unknown")
    run_authors[run_id].add(author_id)
    run_terms[run_id].update(terms)

for run_id, authors in run_authors.items():
    author_list = sorted(authors)
    terms = run_terms.get(run_id, set())
    for i, a in enumerate(author_list):
        for b in author_list[i + 1:]:
            key = (a, b)
            edge_map[key]["weight"] += 1
            edge_map[key]["shared_terms"].update(terms)
```

The outer loop groups all authors by `collection_run_id`. Since a typical GEXF export is scoped to a single run (via `?run_id=...`), all records share the same run ID. This means:

- Every author is placed in the same set.
- The inner double loop connects every author to every other author.
- The `weight` of each edge is 1 (one shared run).
- The `shared_terms` of each edge is the union of all search terms from the entire run, not the terms that appear in records co-authored by both authors (which is meaningless in this context, since neither author wrote both records).

## What a co-occurrence network should be

In discourse research, an actor co-occurrence network connects author A to author B when they independently posted content matching the same search term. The edge weight is the number of distinct terms (or the number of record pairs) where both authors appeared.

The correct construction is:

```
for each search_term T:
    collect all pseudonymized_author_ids that posted content where T is in search_terms_matched
    connect every pair of authors in this set
    weight += 1 per shared term
```

## Research impact

If a researcher exports and opens this GEXF file in Gephi, they will see:
- A fully-connected graph (or near-fully-connected, depending on how many authors posted)
- All edges with weight = 1
- All edges with identical `shared_terms` attributes (the full term list)

This does not represent who discussed similar topics. It represents "everyone in this collection run knows everyone else", which is meaningless for discourse analysis.

A researcher who publishes network analysis based on this export will have incorrect centrality measures, incorrect community detection results, and incorrect interpretation of actor relationships.

## Recommended fix

Rewrite the edge construction to group authors by search term match rather than by collection run:

```python
term_authors: dict[str, set[str]] = defaultdict(set)

for rec in records:
    author_id = rec.get("pseudonymized_author_id")
    if not author_id:
        continue
    for term in (rec.get("search_terms_matched") or []):
        term_authors[term].add(author_id)

for term, authors in term_authors.items():
    author_list = sorted(authors)
    for i, a in enumerate(author_list):
        for b in author_list[i + 1:]:
            key = (a, b)
            edge_map[key]["weight"] += 1
            edge_map[key]["shared_terms"].add(term)
```

This produces a true co-occurrence network where edge weight = number of shared terms and `shared_terms` = the actual terms both authors discussed.
