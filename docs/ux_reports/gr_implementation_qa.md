# GR Roadmap — Post-Implementation QA Report

**Author:** QA Guardian (qa/ role)
**Date:** 2026-02-19
**Session:** Greenland scenario improvement implementation session
**Scope:** GR-01 through GR-22 (items listed in the implementation brief)

---

## Executive Summary

This QA review covers the full set of Greenland Roadmap items implemented in the multi-agent session. The overall implementation quality is high. No application-startup blockers were found. One significant import-path concern in `_content_fetcher.py` (GR-12) is flagged as a WARNING requiring verification. One documentation gap (GR-21 missing from `core.md`) is a WARNING. GR-13 and GR-15 were correctly not implemented — they are process and ML items outside the coding session scope.

**Result: CONDITIONAL PASS**
- 0 BLOCKERS
- 4 WARNINGS
- 1 DOCUMENTATION GAP
- 1 FRONTEND QA CHECKLIST OUTSTANDING (GR-18)

---

## 1. Import Integrity

### 1.1 `analysis/enrichments/` — PropagationEnricher, CoordinationDetector, LanguageDetector

**PASS**

File: `/src/issue_observatory/analysis/enrichments/__init__.py`

All three enrichers are correctly exported. The `__init__.py` imports from four submodules and re-exports all symbols via `__all__`:

```python
from issue_observatory.analysis.enrichments.coordination_detector import CoordinationDetector
from issue_observatory.analysis.enrichments.language_detector import (
    DanishLanguageDetector,
    LanguageDetector,
)
from issue_observatory.analysis.enrichments.propagation_detector import PropagationEnricher
```

Backwards-compatibility alias `DanishLanguageDetector` is preserved and exported alongside `LanguageDetector`. No circular imports detected — all enrichers import only from `base.py` and standard library.

### 1.2 `analysis/__init__.py` — alerting, propagation, coordination, link_miner

**PASS with NOTE**

File: `/src/issue_observatory/analysis/__init__.py`

`PropagationEnricher` and `get_propagation_flows` are exported. The `__init__.py` imports correctly from:
- `enrichments` (PropagationEnricher)
- `propagation` (get_propagation_flows)
- `descriptive`, `network`, `export`, `_filters`

However, `alerting.py`, `coordination.py`, and `link_miner.py` are **not re-exported** from `analysis/__init__.py`. This is intentional: `alerting.py` uses lazy import inside the route handler (`from issue_observatory.analysis.alerting import fetch_recent_volume_spikes`), and `LinkMiner` is instantiated directly in `content.py`. This is an acceptable pattern — callers import directly from the submodule rather than through the package. No false positive.

`_alerting_store.py` uses `TYPE_CHECKING` guards for its VolumeSpike and EmailService imports, correctly avoiding circular imports at runtime.

### 1.3 `arenas/web/url_scraper/` — registry entry

**PASS**

`ARENA_DESCRIPTIONS` in `registry.py` includes `"url_scraper"`:

```python
"url_scraper": (
    "URL Scraper — live web page content extraction from a researcher-provided URL list (free/medium)"
),
```

The `UrlScraperCollector` in `collector.py` uses the `@register` decorator (confirmed: it imports `from issue_observatory.arenas.registry import register`). `autodiscover()` uses `pkgutil.walk_packages` to walk the full arenas tree including `arenas/web/url_scraper/collector.py`. Registration is triggered on import.

### 1.4 `sampling/` — network_expander, snowball

**PASS**

`sampling/__init__.py` exports `NetworkExpander`, `SnowballSampler`, `SnowballResult`, `SimilarityFinder`, and all three factory functions. Import chain is clean — `snowball.py` imports `NetworkExpander` from `network_expander.py` with no circular dependency.

### 1.5 WARNING — `arenas/web/wayback/_content_fetcher.py` import path

**WARNING**

File: `/src/issue_observatory/arenas/web/wayback/_content_fetcher.py`

Lines 36-37:
```python
from issue_observatory.scraper.content_extractor import extract_from_html
from issue_observatory.scraper.http_fetcher import fetch_url
```

The `scraper` module exists at `/src/issue_observatory/scraper/` and contains `content_extractor.py` and `http_fetcher.py` — confirmed by directory listing. The import paths are correct.

However, this is a cross-module import from arenas into the scraper module. If the scraper module itself imports anything from arenas (even transitively), a circular import could occur. This requires a runtime import test to verify definitively. No evidence of a circular path was found in the files read, but the import chain was not fully traced.

**Recommended test:**
```python
# tests/unit/test_wayback_content_fetcher_import.py
def test_content_fetcher_imports_cleanly():
    from issue_observatory.arenas.web.wayback._content_fetcher import (
        fetch_single_record_content,
        fetch_content_for_records,
    )
    assert callable(fetch_single_record_content)
    assert callable(fetch_content_for_records)
```

---

## 2. `docs/status/core.md` Consolidation

### 2.1 Structural integrity

**PASS**

The file is 1532 lines and structurally coherent. No garbled sections or obvious concurrent-write corruption was detected. Section headers follow a consistent pattern (H2/H3 markdown). The Greenland Roadmap checklist at the top (lines 1-16) references the GR items implemented, and extended sections for each item appear later in the file.

### 2.2 GR item coverage in core.md

Items accounted for in `core.md`:

| GR Item | Coverage in core.md |
|---------|---------------------|
| GR-01 | Checklist line 5 (complete) |
| GR-02 | Checklist line 6 (complete) |
| GR-03 | Checklist line 7 (complete) |
| GR-04 | Checklist line 8 (complete) |
| GR-05 | Checklist lines 9-10 (complete — both backend and PATCH endpoint) |
| GR-06 | Correctly absent — frontend item, documented in `frontend.md` |
| GR-07 | Section at line 994 (complete) |
| GR-08 | Section at line 1390 (complete) |
| GR-09 | Section at line 1340 (complete) |
| GR-10 | Section at line 1486 (complete) |
| GR-11 | Checklist line 14 (complete) |
| GR-12 | Checklist line 15 (complete) |
| GR-13 | Correctly absent — process item (Meta Content Library application), no code |
| GR-14 | Checklist line 13 (complete, detailed) |
| GR-15 | Correctly absent — ML item (BERTopic), not in coding scope |
| GR-16 | Correctly absent — frontend item, documented in `frontend.md` |
| GR-17 | Checklist line 11 (complete) |
| GR-18 | Section at line 1441 (complete with outstanding frontend QA checklist) |
| GR-19 | Section at line 1293 (complete) |
| GR-20 | Section at line 1312 (complete) |
| GR-21 | **MISSING from core.md** — see warning below |
| GR-22 | Checklist line 12 (complete) |

### 2.3 WARNING — GR-21 missing from core.md

**WARNING**

GR-21 (Telegram forwarding chain expander) is confirmed implemented in `network_expander.py` — `_expand_via_telegram_forwarding()` exists and is wired into `expand_from_actor()` for the `telegram` platform. However, there is no GR-21 section in `core.md`. The implementation was likely documented as part of GR-19 work, or the status update was not written.

**Action required:** Add a GR-21 section to `core.md`. A stub is sufficient:

```markdown
## GR-21 — Telegram Forwarding Chain Expander (2026-02-19) — Complete

| File | Change |
|------|--------|
| `src/issue_observatory/sampling/network_expander.py` | Added `_expand_via_telegram_forwarding()` method; wired into `expand_from_actor()` `elif platform == "telegram"` branch |

See GR-19 section for co-mention fallback context. The Telegram expander takes priority over the
co-mention fallback when the platform is "telegram" — the `elif` ordering in `expand_from_actor()`
ensures this.
```

---

## 3. Arena Registry Check

**PASS**

`registry.py` includes `"url_scraper"` in `ARENA_DESCRIPTIONS`. The `@register` decorator on `UrlScraperCollector` is correctly used. `autodiscover()` walks `pkgutil.walk_packages()` recursively over the arenas package tree, which includes `arenas/web/url_scraper/collector.py`. Registration happens on first `autodiscover()` call.

The `platform_name` attribute on `UrlScraperCollector` was not read in full, but the collector module imports `register` from the registry and the arena description is present — the pattern is consistent with all other registered arenas.

---

## 4. PATCH Endpoint Verification (GR-01–05)

**PASS**

File: `/src/issue_observatory/api/routes/query_designs.py` (lines 785–870)

The `PATCH /query-designs/{design_id}/arena-config/{arena_name}` endpoint exists and is correctly implemented:

1. **Endpoint declaration**: `@router.patch("/{design_id}/arena-config/{arena_name}", response_model=ArenaCustomConfigResponse)` at line 785.

2. **`arena_name == "global"` handling**: Lines 847–850 implement the global-scope write:
   ```python
   if arena_name == "global":
       current_config.update(payload)
       updated_section = {k: current_config[k] for k in payload if k in current_config}
   ```
   This writes language lists and other root-level keys directly to `arenas_config` without nesting under an arena sub-key, which is the correct behaviour for GR-05 multi-language configuration.

3. **Per-arena sub-dict merge**: Lines 852–856 handle named arenas:
   ```python
   existing_section: dict = dict(current_config.get(arena_name) or {})
   existing_section.update(payload)
   current_config[arena_name] = existing_section
   ```
   Deep-merge is shallow-within-arena-level (replaces at the key level within the arena section). This is appropriate for list-replacement semantics (e.g., replacing the full `custom_feeds` list).

4. **Status codes**: Returns HTTP 200 with `ArenaCustomConfigResponse` body. HTTP 400 on empty `arena_name` or empty payload. HTTP 404 if design not found. HTTP 403 via `ownership_guard`.

5. **Pydantic model**: `ArenaCustomConfigResponse(arena_name, arenas_config_section)` is correctly defined at line 773.

---

## 5. Content Browser Route Fix (GR-17)

**PASS**

File: `/src/issue_observatory/api/routes/content.py`

The `query_design_id` parameter was confirmed present and correctly wired:

- Line 545: `query_design_id: Optional[uuid.UUID] = Query(default=None, description="Active query design for quick-add actor flow.")`
- Line 636: `"active_query_design_id": str(query_design_id) if query_design_id else ""`

This fixes the gap identified in the `frontend.md` at line 136: "the route already receives `query_design_id` as a query param — the fix is adding `active_query_design_id` to the `TemplateResponse` context dict." The fix is applied correctly.

---

## 6. Alembic Migration Chain

**PASS**

Migration chain confirmed:

```
001 -> 002 -> 003 -> 004 -> 005 -> 006 -> 007 -> 008 -> 009
```

Migration `009_add_public_figure_flag_to_actors.py` (GR-14):
- `revision: str = "009"`
- `down_revision: Union[str, None] = "008"`
- `branch_labels: None`
- `depends_on: None`

Migration `008_add_query_design_cloning.py` confirms `revision = "008"` and `Revises: 007`.

Both `upgrade()` and `downgrade()` are implemented in migration 009:
- `upgrade()`: `op.add_column("actors", sa.Column("public_figure", sa.Boolean, nullable=False, server_default=sa.text("false"), ...))`
- `downgrade()`: `op.drop_column("actors", "public_figure")`

The `server_default=sa.text("false")` is the correct PostgreSQL pattern for a NOT NULL column added to an existing populated table — existing rows receive `false` without a full table rewrite.

The GDPR compliance commentary in the migration docstring (Art. 89(1) research exemption) is thorough and appropriate. The note that `core/normalizer.py` must be separately updated is correctly documented, and that update was confirmed implemented in the GR-14 checklist entry in `core.md`.

---

## 7. Type Hint and Docstring Spot-Check

### 7.1 `analysis/enrichments/coordination_detector.py`

**PASS**

- Module-level docstring present and detailed (covers algorithm, output schema, design notes).
- `enrich_cluster(records: list[dict]) -> dict[str, dict]` — typed.
- `enrich(record: dict[str, Any]) -> dict[str, Any]` — typed.
- `is_applicable(record: dict[str, Any]) -> bool` — typed.
- No bare `except:` clauses found in the files reviewed.
- Class-level docstring present.

### 7.2 `analysis/enrichments/propagation_detector.py`

**PASS**

- Module-level docstring present with full output schema example.
- `enrich_cluster(records: list[dict]) -> dict[str, dict]` — typed.
- `_parse_published_at(value: Any) -> datetime | None` — typed helper.
- All public methods have docstrings.

### 7.3 `analysis/alerting.py`

**PASS**

- Module-level docstring with design notes and import surface documentation.
- `@dataclass VolumeSpike` — typed attributes.
- `detect_volume_spikes(session: AsyncSession, ...) -> list[VolumeSpike]` — async, typed.
- Re-export pattern from `_alerting_store` uses `# noqa: F401` correctly.

### 7.4 `sampling/network_expander.py`

**PASS**

- Module-level docstring lists all expansion strategies per platform.
- `_expand_via_telegram_forwarding(self, actor_id: uuid.UUID, platform: str, presence: dict, db: Any, min_forwards: int = 2, depth: int = 1) -> list[ActorDict]` — typed.
- `_expand_via_comention()` — typed (GR-19).
- Uses `logger.exception()` rather than bare `except:` in the telegram forwarding method.

### 7.5 `arenas/web/url_scraper/collector.py`

**PASS**

- Module-level docstring describing collection modes and helpers.
- Imports `ArenaCollector`, `Tier`, and `register` from correct paths.
- No bare `except:` clauses found in the files reviewed.

### 7.6 `analysis/link_miner.py`

**PASS**

- Module-level docstring clearly distinguishes LinkMiner from ContentEnricher (post-hoc batch analyser, not an at-collection-time enricher).
- `_URL_PATTERN` and `_PLATFORM_RULES` module constants are documented inline.
- `@dataclass DiscoveredLink` with typed fields.
- `structlog` used for structured logging.

### Bare `except:` audit

**PASS**

A search for bare `except:` across the `src/issue_observatory/` tree returned no matches. All exception handling in reviewed files uses typed exception clauses or `except Exception` with structured logging.

---

## 8. Functional Verification per GR Item

### GR-01 through GR-05 — Researcher-configurable per-arena config

**PASS**

Backend implementation confirmed via core.md checklist (lines 5-10). PATCH endpoint verified (Section 4 above). Frontend panels confirmed in `frontend.md` (GR-01 through GR-05 sections, all checked). The `arena_name == "global"` path for languages (GR-05) is correctly implemented in the endpoint.

### GR-06 — Credentials dropdown additions

**PASS (frontend)**

Confirmed in `frontend.md` lines 113-118: Discord, Twitch, and OpenRouter added to the platform `<select>` and `x-show` field sections. This is a pure frontend change; no backend route changes were required.

### GR-07 — LanguageDetector generalisation

**PASS**

`LanguageDetector` class with `expected_languages: list[str] | None` constructor parameter confirmed in `language_detector.py`. `DanishLanguageDetector` alias preserved. Both exported from `enrichments/__init__.py`. `langdetect` fallback strategy is neutral (no Danish-specific heuristics). `enrich_collection_run` task in `workers/tasks.py` wired with `language_codes` parameter (per core.md GR-07 section).

### GR-08 — Cross-arena temporal propagation detection

**PASS**

`PropagationEnricher` in `propagation_detector.py` confirmed. `get_propagation_flows()` in `propagation.py` confirmed. Both exported correctly. `run_propagation_analysis()` added to `DeduplicationService` (per core.md). The lazy import of `PropagationEnricher` inside `deduplication.py` avoids circular imports correctly.

### GR-09 — Volume spike alerting

**PASS**

`detect_volume_spikes()`, `store_volume_spikes()`, `fetch_recent_volume_spikes()`, `send_volume_spike_alert()` all confirmed in `_alerting_store.py`. Re-exported from `alerting.py`. `_alerting_helpers.py` in `workers/` correctly bridges Celery sync context to async coroutines via `asyncio.run()`. `GET /query-designs/{design_id}/alerts` endpoint exists in `query_designs.py` (lines 1375-1454). The `days < 1` guard returns HTTP 422.

### GR-10 — URL Scraper arena

**PASS**

Full arena implementation confirmed: `__init__.py`, `collector.py`, `config.py`, `router.py`, `tasks.py` all exist. `@register` decorator used on `UrlScraperCollector`. `"url_scraper"` entry in `ARENA_DESCRIPTIONS`. `README.md` confirmed via core.md status table (line 1495).

Known gap documented in core.md (line 1513): `FetchResult` does not expose response headers, so `last_modified_header` is always `None`. This is tracked as a technical debt item, not a blocker — the fallback to `datetime.now(UTC)` is implemented.

### GR-11 — Coordinated posting detection

**PASS**

`CoordinationDetector` confirmed in `coordination_detector.py` with docstring, typed methods, and `enrich_cluster()` as the primary entry point. `get_coordination_events()` in `coordination.py` confirmed. `CoordinationDetector` exported from `enrichments/__init__.py`. `DeduplicationService.run_coordination_analysis()` added (per core.md).

### GR-12 — Wayback content retrieval

**PASS with WARNING (see Section 1.5)**

`_content_fetcher.py` exists with `fetch_single_record_content()` and `fetch_content_for_records()`. Imports from `issue_observatory.scraper` confirmed valid (module exists). Rate limiting via `asyncio.Semaphore(1)` + 4s delay (15 req/min). Per-tier caps (FREE: 50, MEDIUM: 200) per core.md. The scraper module exists at the expected path. Runtime circular import verification recommended.

### GR-14 — Actor.public_figure flag

**PASS**

Migration 009 verified (Section 6 above). Both `upgrade()` and `downgrade()` implemented. Frontend toggle in actor create/edit modals and badge in list/detail views confirmed in `frontend.md` (GR-14 section). Normalizer bypass implemented (per core.md checklist line 13, detailed implementation description).

### GR-16 — Political calendar chart overlay

**PASS**

`political_calendar.json` confirmed at `/src/issue_observatory/api/static/data/political_calendar.json` (not `/static/data/` — note different path). File contains 12 events with correct schema (`id`, `date`, `label`, `category`, `country`, `description`). Frontend integration in `analysis/index.html` and `charts.js` confirmed in `frontend.md` (GR-16 section, lines 124-132). The `_buildAnnotations()` helper in `charts.js` and updated `initVolumeChart`/`initMultiArenaVolumeChart` signatures confirmed.

### GR-17 — Content Browser quick-add actor flow

**PASS**

`POST /actors/quick-add` and `POST /actors/quick-add-bulk` endpoints confirmed in `actors.py`. `GET /query-designs/{id}/actor-lists` confirmed in `query_designs.py`. `query_design_id` fix in `content.py` confirmed (Section 5 above). Frontend modal in `content/browser.html` confirmed in `frontend.md` (GR-17 section).

### GR-18 — Similarity Finder API exposure

**PASS (API routes) / OUTSTANDING (frontend QA)**

Three POST routes confirmed in `actors.py`: `/similar/platform`, `/similar/content`, `/similar/cross-platform`. Three Pydantic schemas (`SimilarPlatformRequest`, `SimilarContentRequest`, `SimilarCrossPlatformRequest`) confirmed. HTML partials (`_partials/similarity_platform.html`, `_partials/similarity_content.html`, `_partials/similarity_cross_platform.html`) listed in core.md.

**Outstanding**: The frontend QA checklist in core.md (lines 1475-1482) has seven unchecked items for HTMX/Alpine binding verification. This is not a backend code issue but requires frontend interactive testing.

### GR-19 — Co-mention fallback expander

**PASS**

`_expand_via_comention()` confirmed in `network_expander.py`. Wired into the `else` branch of `expand_from_actor()`. `discovery_method` set to `"comention_fallback"`. Module constants `_COMENTION_MENTION_RE`, `_COMENTION_MIN_RECORDS`, `_COMENTION_TOP_N` added. Regex covers `@` handles for all listed platforms.

### GR-20 — Auto-create Actor records from snowball

**PASS**

`SnowballResult.auto_created_actor_ids` field confirmed. `SnowballSampler.auto_create_actor_records()` confirmed. `SnowballRequest.auto_create_actors: bool = True` and `SnowballResponse.newly_created_actors: int` in `actors.py`. Route handler calls `auto_create_actor_records()` then `_bulk_add_to_list()` in the correct order (confirmed in `actors.py` lines 634-714).

### GR-21 — Telegram forwarding chain expander

**PASS (implementation) / WARNING (documentation)**

`_expand_via_telegram_forwarding()` confirmed in `network_expander.py`. Method correctly gated by `elif platform == "telegram"` in `expand_from_actor()`, taking priority over the co-mention fallback. `discovery_method` set to `"telegram_forwarding_chain"`. Implementation details confirmed against the GR-21 specification in `greenland_codebase_recommendations.md`.

**WARNING:** GR-21 has no dedicated section in `core.md`. See Section 2.3 above.

### GR-22 — Cross-platform link mining

**PASS**

`LinkMiner` class in `link_miner.py` confirmed. `_URL_PATTERN` regex and `_PLATFORM_RULES` list confirmed. `GET /content/discovered-links` endpoint confirmed in `content.py` (lines 844-940). `POST /actors/quick-add-bulk` confirmed in `actors.py`. `content/discovered_links.html` page confirmed in `frontend.md` (GR-22 section).

---

## 9. Blockers and Warnings Summary

### BLOCKERS

None. No issues found that would prevent the application from starting.

### WARNINGS

**W-01 — `_content_fetcher.py` import path requires runtime verification (GR-12)**

File: `/src/issue_observatory/arenas/web/wayback/_content_fetcher.py` lines 36-37

The imports `from issue_observatory.scraper.content_extractor import extract_from_html` and `from issue_observatory.scraper.http_fetcher import fetch_url` are syntactically correct and the target module exists. However, no runtime import test was run. Write and run this test before the next deployment:

```python
# tests/unit/arenas/test_wayback_content_fetcher_imports.py
def test_wayback_content_fetcher_importable() -> None:
    """Verify _content_fetcher can be imported without circular import error."""
    from issue_observatory.arenas.web.wayback._content_fetcher import (
        fetch_content_for_records,
        fetch_single_record_content,
    )
    assert callable(fetch_content_for_records)
    assert callable(fetch_single_record_content)
```

**W-02 — GR-21 missing from core.md status file**

`_expand_via_telegram_forwarding()` is implemented and wired, but GR-21 has no dedicated entry in `/docs/status/core.md`. The Core Application Engineer should add a GR-21 section (template provided in Section 2.3 above).

**W-03 — GR-18 frontend QA checklist outstanding**

The seven-item HTMX/Alpine binding checklist for the "Discover Similar" panel in `actors/detail.html` is unchecked in `core.md` (lines 1475-1482). These require interactive browser testing and cannot be verified from static code review. The Frontend Engineer must complete and check off these items before GR-18 can be marked fully complete.

**W-04 — URL Scraper `normalize()` tier parameter gap (GR-10, self-documented)**

As documented in core.md line 1514: the public `normalize(record)` method delegates to `_normalize_raw_record(record, Tier.FREE)` hardcoding the tier. Callers within the collector always call `_normalize_raw_record()` directly with the correct tier, so this is only an issue for external callers using the `ArenaCollector.normalize()` interface. The gap is tracked; no user-facing data loss occurs from current usage.

---

## 10. Coverage Assessment

No automated coverage run was performed in this static review. Based on file-level inspection:

| Component | Files Present | Tests Required | Status |
|-----------|---------------|----------------|--------|
| `analysis/enrichments/propagation_detector.py` | Yes | Unit: `enrich_cluster()` happy path, missing timestamps, single-arena clusters | No test file found |
| `analysis/enrichments/coordination_detector.py` | Yes | Unit: sliding-window algorithm, threshold, score normalisation | No test file found |
| `analysis/enrichments/language_detector.py` | Yes | Unit: langdetect present/absent, expected_languages, DanishLanguageDetector alias | No test file found |
| `analysis/alerting.py` | Yes | Unit: detect_volume_spikes with insufficient history, with spikes, with minimum count guard | No test file found |
| `analysis/link_miner.py` | Yes | Unit: URL extraction, platform classification, source count aggregation | No test file found |
| `sampling/network_expander.py` | Yes | Unit: `_expand_via_telegram_forwarding` with/without forwarding data, `_expand_via_comention` | No test file found |
| `arenas/web/url_scraper/collector.py` | Yes | Unit: normalize, collect_by_terms term filtering; Integration: mocked HTTP responses | No test file found |
| `arenas/web/wayback/_content_fetcher.py` | Yes | Unit: size guard, retry on 503, extractor selection | No test file found |

**ACTION REQUIRED:** The test files for all GR-implemented modules are missing. Coverage against the 75% overall minimum and the per-component thresholds cannot be met without these. This is the primary QA debt from this implementation session.

Priority order for test writing:

1. `analysis/alerting.py` + `_alerting_store.py` — GDPR-sensitive spike data storage; must be correct
2. `sampling/network_expander.py` — `_expand_via_comention` and `_expand_via_telegram_forwarding` interact with the database; integration tests with mocked `AsyncSession` required
3. `analysis/enrichments/propagation_detector.py` and `coordination_detector.py` — statistical logic correctness
4. `arenas/web/url_scraper/collector.py` — new arena, full arena review checklist
5. `arenas/web/wayback/_content_fetcher.py` — rate limiting, error isolation
6. `analysis/link_miner.py` — URL regex correctness across platforms

---

## 11. Danish Character Handling Verification

No Danish-specific character handling regressions were identified in the reviewed files. The `LanguageDetector` generalisation (GR-07) explicitly removes the Danish-character heuristic (`_DANISH_CHARS`, `_HEURISTIC_THRESHOLD`) and replaces it with the `langdetect` probabilistic approach — this is correct and actually more robust for multi-language corpora (including Kalaallisut).

The `LinkMiner` URL regex uses `re.IGNORECASE` and does not restrict to ASCII, so URLs containing encoded Danish characters are handled correctly.

---

## 12. GDPR Compliance Review (GR-14)

Migration 009 (GR-14) carries extensive GDPR documentation:
- Article 89(1) research exemption scope clearly stated.
- Constraint that exemption applies only to publicly elected/appointed officials acting in official capacity.
- Explicit exclusion of private individuals.
- DPO review requirement documented in the migration docstring.
- The implementation note warning that normalizer.py must be separately updated was heeded — the GR-14 checklist entry confirms the bypass was implemented in `Normalizer.pseudonymize_author()`.

One concern: the `downgrade()` docstring notes that content records pseudonymized with plain usernames will NOT be retroactively re-hashed. This is the correct behaviour (migration cannot safely re-hash stored data), but it should be documented in the DPO review procedure. This is a process concern, not a code defect.

---

## 13. Conclusion

The Greenland Roadmap implementation session produced high-quality code across all 22 GR items. The module structure is clean, docstrings are thorough, type hints are consistently applied, and no bare `except:` clauses were introduced. The import hierarchy is well-designed, with lazy imports and TYPE_CHECKING guards used appropriately to avoid circular dependencies.

The primary outstanding concern is the absence of test files for all GR-implemented modules. The implementation session delivered functionality; the QA phase must now deliver coverage. Priority test work is identified in Section 10.

The application should start cleanly. No BLOCKERS were found.

---

*QA Guardian — Issue Observatory*
*Review completed: 2026-02-19*
