# Project Collaborators Feature: Research Workflow Review

**Reviewer:** Research Agent (The Strategist)
**Date:** 2026-03-27
**Scope:** Review of the project sharing/collaborators feature from the perspective of communications researchers
**Status:** Review only -- no code changes

---

## 1. Implementation Summary

The collaborators feature adds project-level sharing between researchers. The data model is a `project_collaborators` junction table with composite PK on `(project_id, user_id)`, a `role` field (currently only `viewer`), and a `granted_by` audit FK. Access is granted by the project owner via email lookup. Shared projects appear in the collaborator's project list with a "Shared" badge and "Shared with you (view only)" label on the detail page.

### Access granted to viewers

Based on the route-level access control checks across all relevant modules, a viewer can:

- **View project detail page** (projects route: `_verify_project_ownership` with `require_owner=False`)
- **View query designs** within the project (query_designs route: `is_project_collaborator` check on `project_id`)
- **View arena configuration** for query designs (read endpoint uses same collaborator check)
- **View collection runs** belonging to the project (collections route: `_run_read_guard`)
- **Browse content records** from project collection runs (content route: query includes `collaborated_project_ids`)
- **Export content** via both sync and async export pipelines (content export uses the same content query base)
- **View project dashboard** (dashboard route: explicit `is_project_collaborator` check)
- **View analysis results** for collection runs in the project (analysis route: collaborator check on `run.project_id`)
- **View network visualizations** (networks route: collaborator check on project)
- **View collection history page** (pages route: explicit collaborator check)

### Access denied to viewers

All mutating operations use `require_owner=True` or `ownership_guard`:

- Edit project settings, delete project, clone project
- Create/edit/delete query designs
- Launch or cancel collection runs
- Add/remove collaborators
- Modify arena settings, source lists, comments config, collection mode

---

## 2. Use Case Coverage Assessment

### 2.1 Well-Covered Scenarios

**PI sharing collected data with a research assistant.** The most common collaboration pattern in communications research is a principal investigator who designs the data collection and then shares the resulting dataset with assistants for coding, export, and analysis. This feature handles it well: the assistant sees all content, can export in all formats (CSV, XLSX, NDJSON, Parquet, GEXF, RIS, BibTeX), and can browse the analysis dashboard. The read-only constraint is appropriate here -- the PI retains control over data collection parameters.

**Cross-institutional data sharing for peer review of methodology.** A reviewer can inspect the complete query design (search terms, actor lists, arena configuration, boolean logic), see collection run histories and record counts, and examine the data itself. This is sufficient for methodological review. The viewer can also see which arenas were enabled and at which tiers, which is essential for evaluating collection completeness.

**Teaching and demonstration.** An instructor can share a live research project with students who can then browse the data and analysis without risk of accidentally modifying the collection parameters. The "Shared with you (view only)" badge makes the access level clear on the project detail page.

### 2.2 Partially Covered Scenarios

**Collaborative qualitative coding.** The system has `ContentAnnotation` and `CodebookEntry` models, and annotation routes exist. However, annotations are scoped by `created_by` (the annotating user) and the annotation routes use `ownership_guard` without any `is_project_collaborator` check. This means a viewer who navigates to a shared project's content records can view the data but **cannot create annotations on shared content**. The codebook routes similarly have no collaborator awareness. This is a significant gap for qualitative research workflows where multiple researchers code the same dataset.

**Intercoder reliability assessment.** Related to the above: even if annotation access were granted to collaborators, there is no facility for comparing annotations across users on the same content records. This is a standard requirement in qualitative communications research (Krippendorff's alpha, Cohen's kappa).

### 2.3 Not Covered Scenarios

**Delegated collection management.** In larger research groups, a PI often delegates the operational task of launching and monitoring collections to a research assistant while retaining ownership of the research design. The current viewer role cannot launch collections. The model's `role` field anticipates an "editor" role (the model docstring mentions `'editor' (read + launch collections)`), but this is not yet implemented.

**Project cloning by collaborators.** The clone endpoint uses `require_owner=True`, meaning a viewer cannot clone a shared project to create their own independent copy. This is a reasonable default for the viewer role, but there is a legitimate use case: a collaborator sees a well-designed query setup and wants to replicate it for a different research context. This should be considered for the "editor" role or as a separate permission.

---

## 3. Issue Inventory

### ISSUE-01 (High): Annotations and codebooks are inaccessible to collaborators

**Affected files:**
- `/src/issue_observatory/api/routes/annotations.py` -- uses `ownership_guard`, no `is_project_collaborator` check
- `/src/issue_observatory/api/routes/codebooks.py` -- same pattern

**Impact:** A collaborator who has been given access to a project cannot annotate the content records they can browse. They also cannot view or use codebooks scoped to the project's query designs. This blocks the most common form of qualitative research collaboration: having multiple coders independently annotate the same dataset.

**Recommendation:** Allow collaborators to create their own annotations on content records belonging to shared projects. Annotations are already user-scoped (unique constraint on `created_by + content_record_id`), so there is no data integrity risk. Codebook read access should be granted to collaborators; codebook write access should remain owner-only.

### ISSUE-02 (High): Query design detail page shows Edit/Codebook buttons to viewers

**Affected file:** `/src/issue_observatory/api/templates/query_designs/detail.html` (lines 43-60)

**Impact:** The template unconditionally renders "Edit" and "Manage Codebook" action buttons. When a viewer clicks "Edit," they navigate to the editor page (which renders without any ownership check in `pages.py` line 491), fill in changes, submit, and then receive a 403 error. This is a confusing user experience -- the viewer has no way to know in advance that they lack permission.

**Recommendation:** Pass an `is_owner` flag to the query design detail template and conditionally hide the Edit and Manage Codebook buttons for viewers, consistent with the pattern already used on the project detail page.

### ISSUE-03 (Medium): Query design editor page renders for viewers without access check

**Affected file:** `/src/issue_observatory/api/routes/pages.py` (line 491, `query_designs_edit`)

**Impact:** The page-rendering route at `GET /query-designs/{design_id}/edit` does not verify ownership or collaborator status. Any authenticated user can load the full editor form. The 403 only triggers when they attempt to submit the form. A viewer could spend time filling out edits before learning they lack permission.

**Recommendation:** Add an `ownership_guard` call in the page route, or redirect viewers to the detail page with a flash message explaining they have read-only access.

### ISSUE-04 (Medium): No notification when a project is shared with you

**Affected file:** `/src/issue_observatory/api/routes/projects.py` (line 1148, `add_collaborator`)

**Impact:** When a project owner adds a collaborator, the target user receives no notification. The shared project simply appears in their project list on their next page load. In a research context where collaboration is coordinated asynchronously (across time zones, institutions), the collaborator may not discover the shared project for days. There is no email, no in-app notification, no SSE event.

**Recommendation:** At minimum, send an email notification using the target user's email (already available in the route). The system already has SSE event infrastructure (Redis pub/sub) that could be extended for in-app notifications. A lightweight first step would be structured logging with a webhook integration.

### ISSUE-05 (Medium): Shared projects show no owner attribution

**Affected files:**
- `/src/issue_observatory/api/routes/projects.py` (line 170, `list_projects`) -- builds project dict without owner info
- `/src/issue_observatory/api/templates/projects/list.html` -- shows "Shared" badge but not who shared it

**Impact:** When a researcher sees multiple shared projects in their list, they cannot distinguish who shared each one. In multi-institutional collaborations, this makes it difficult to identify the source and context of shared data. The project list shows a "Shared" badge but no owner name or email.

**Recommendation:** Include `owner_display_name` or `owner_email` in the project list context for shared projects. The `Project.owner` relationship is already defined and can be eagerly loaded.

### ISSUE-06 (Medium): No audit trail for collaborator data access

**Impact:** The project owner cannot see what a collaborator has accessed or exported. The system logs collaborator add/remove events via structlog (`project.collaborator_added`, `project.collaborator_removed`), but there is no user-visible audit log and no logging of collaborator read/export actions.

**Recommendation for Phase 1:** Add structured log events when a collaborator views project content or triggers an export, including the collaborator user ID and record counts. These logs already flow to the application's log infrastructure.

**Recommendation for Phase 2:** Create a user-facing audit log view on the project detail page (owner-only) showing collaborator access events with timestamps.

### ISSUE-07 (Low): Arena settings section visible to viewers but non-functional

**Affected file:** `/src/issue_observatory/api/templates/projects/detail.html` (line 182)

**Impact:** The "Arena Settings" section on the project detail page is rendered for all users (not gated by `{% if is_owner %}`), including viewers. The Alpine.js toggle buttons appear interactive but will fail silently when a viewer clicks them, since the backend PATCH endpoint requires ownership. The section provides useful read-only information (which arenas are enabled), but the interactive toggle UI is misleading.

**Recommendation:** Either wrap the arena settings section in `{% if is_owner %}` (and provide a read-only summary for viewers), or disable the toggle buttons for viewers while keeping the visual display of enabled/disabled status.

### ISSUE-08 (Low): Source Lists, Comments Config, and Collection Mode sections correctly hidden

This is not an issue but rather a positive finding: the Source Lists, Comments Config, and Collection Mode sections on the project detail page are all correctly wrapped in `{% if is_owner %}` blocks (lines 294, 474, and surrounding), so viewers do not see these editing interfaces. This is consistent and well-implemented.

---

## 4. Data Governance Assessment

### 4.1 Read-only as default sharing level

Read-only (`viewer`) as the default and currently only sharing level is the correct conservative choice. In the GDPR context of this project, limiting write access means the data controller (project owner) retains full control over what data is collected and how it is processed. Adding a collaborator does not change the data processing scope -- it only extends read access to data that has already been collected under the owner's authority.

### 4.2 GDPR implications of cross-user data sharing

**Key consideration:** Content records contain pseudonymized personal data (author usernames hashed via SHA-256 with `PSEUDONYMIZATION_SALT`). When a project is shared, the collaborator gains access to the same pseudonymized dataset. Since the pseudonymization salt is a system-wide environment variable (not per-user), both the owner and the collaborator see identical pseudonymized identifiers, which means they could theoretically correlate pseudonymized authors across their respective projects.

This is not a GDPR violation per se -- both users are researchers operating under the same data processing agreement and the same instance's legal basis (Article 89 research exemption, Databeskyttelsesloven SS10). However, the following considerations apply:

1. **Data minimization (Art. 5(1)(c)):** The viewer gets access to the full `raw_metadata` JSONB, which may contain platform-specific fields beyond what they need. There is no mechanism to share only specific fields or a subset of records.

2. **Purpose limitation:** If the collaborator uses the shared data for a purpose different from the project's stated research objective, this could constitute a new processing purpose requiring separate justification. The system has no mechanism to document or constrain the collaborator's intended use.

3. **Public figure bypass:** Content records from actors with `public_figure=True` are not pseudonymized. This is correct for the project owner who made that classification, but the collaborator inherits this decision without visibility into the justification.

**Recommendation:** Add a note in the collaborator invitation flow indicating that the collaborator will have access to pseudonymized research data and must comply with the same data handling policies. Consider making this an explicit acknowledgment step.

### 4.3 Cascade deletion behavior

The `ON DELETE CASCADE` foreign key on `project_collaborators.project_id` means deleting a project automatically revokes all collaborator access. The `ON DELETE CASCADE` on `user_id` means deleting a user account removes all their collaboration grants. The `ON DELETE SET NULL` on `granted_by` preserves the audit trail even if the grantor's account is deleted. These are all correct choices.

---

## 5. Discoverability Assessment

### 5.1 Current state

A shared project appears in the collaborator's project list alongside their own projects, distinguished only by a small blue "Shared" badge. There is no separate "Shared with me" section, no filtering mechanism, and no notification.

### 5.2 Findings

- The "Shared" badge is visually subtle. In a list of 10+ projects, it could easily be missed.
- There is no way to filter the project list to show only shared projects.
- The project detail page clearly states "Shared with you (view only)" at the top right, which is good.
- There is no "Shared with me" dashboard or navigation entry.

### 5.3 Recommendations

1. Add a filter toggle or tab to the project list page: "My Projects" / "Shared with Me" / "All"
2. Show the owner's name on the project card for shared projects (see ISSUE-05)
3. Consider a notification mechanism when a project is first shared (see ISSUE-04)

---

## 6. Future Extensibility Assessment

### 6.1 Role field

The `role` column is `String(20)`, and the model docstring explicitly mentions `'editor' (read + launch collections)` as a planned future role. The `add_collaborator` endpoint validates `role in ("viewer",)`, making it straightforward to extend.

**Recommended role roadmap:**

| Role | Capabilities | Use case |
|------|-------------|----------|
| `viewer` (current) | Read-only access to all project data | Peer review, data sharing, teaching |
| `annotator` | Viewer + create/edit own annotations | Collaborative qualitative coding |
| `editor` | Annotator + launch/cancel collections, clone project | Delegated data collection management |
| `admin` (project-level) | Editor + manage collaborators, edit query designs | Co-PI with full project control |

The `annotator` role deserves priority because qualitative coding is the most immediate collaboration need in communications research and the annotation infrastructure already exists.

### 6.2 Project-level vs. query-design-level sharing

The current implementation shares at the project level, which is the right granularity for most use cases. A project typically represents a coherent research study, and sharing the entire project gives the collaborator the context needed to understand the data.

Query-design-level sharing would add complexity without clear benefit. A researcher who needs to share only one query design can place it in its own project. The existing project structure already supports this organizational pattern.

### 6.3 Link-based sharing

The current implementation requires the collaborator to have an existing account (looked up by email). Link-based sharing (a URL with a token that grants access) would lower the friction for ad-hoc sharing, especially for peer review scenarios where the reviewer may not have an account.

**Considerations:**
- Link-based sharing introduces a new authentication surface that must be carefully secured (token expiry, single-use vs. reusable, revocation)
- GDPR data access requires accountability -- anonymous link access would undermine the ability to audit who accessed personal data
- The system already requires admin-approved accounts (`is_active` defaults to `false`), suggesting a deliberate access control philosophy

**Recommendation:** Defer link-based sharing. The current email-based model is appropriate for a research tool where all users should be known and accountable. If link-based access is needed in the future, implement it as a time-limited, single-use invitation link that still requires account creation.

---

## 7. Prioritized Recommendations

### Priority 1 -- High impact, addresses core research workflows

| # | Recommendation | Effort | Impact |
|---|---------------|--------|--------|
| R1 | Grant collaborators the ability to create annotations on shared project content (ISSUE-01) | Medium | Unblocks collaborative qualitative coding -- the primary collaboration use case |
| R2 | Hide Edit/Codebook buttons on query design detail page for non-owners (ISSUE-02) | Low | Eliminates confusing UX for viewers |
| R3 | Add ownership/collaborator check to the query design edit page route (ISSUE-03) | Low | Prevents viewers from loading the edit form |

### Priority 2 -- Medium impact, improves usability

| # | Recommendation | Effort | Impact |
|---|---------------|--------|--------|
| R4 | Show owner name on shared project cards (ISSUE-05) | Low | Essential context for multi-collaborator scenarios |
| R5 | Add email notification when sharing a project (ISSUE-04) | Medium | Closes the discoverability gap |
| R6 | Add project list filtering (My Projects / Shared with Me) | Low | Improves navigation as sharing adoption grows |
| R7 | Make arena settings read-only for viewers instead of showing interactive toggles (ISSUE-07) | Low | Eliminates misleading interactive UI |

### Priority 3 -- Lower urgency, strategic improvements

| # | Recommendation | Effort | Impact |
|---|---------------|--------|--------|
| R8 | Implement `annotator` role as the next role expansion | Medium | Provides fine-grained access for qualitative coding without granting collection control |
| R9 | Add structured logging for collaborator data access and exports (ISSUE-06) | Medium | GDPR accountability, owner peace of mind |
| R10 | Add GDPR acknowledgment step to the collaborator invitation flow | Low | Compliance documentation |
| R11 | Allow collaborators to clone shared projects | Low | Supports methodological replication |

---

## 8. Overall Assessment

The collaborators feature is well-architected at the data model level and provides thorough backend access control. The composite PK design, CASCADE deletion semantics, and `granted_by` audit field show careful database engineering. The access checks are consistently applied across all route modules (projects, collections, content, analysis, dashboard, networks, query designs), which is difficult to get right and has been done correctly here.

The primary gap is in the qualitative analysis workflow: the annotation and codebook subsystems are not yet aware of the collaborator model, which means the most common form of research collaboration (multiple coders on the same dataset) is not yet supported. This is the highest-priority improvement.

The secondary gap is in the UI layer, where a few templates do not yet conditionally render editing controls based on the viewer's access level. The backend correctly rejects unauthorized mutations, so this is a UX issue rather than a security issue.

The GDPR posture is appropriate for the current implementation. The read-only default is correct, and the existing pseudonymization infrastructure applies equally to shared data. The main improvement needed is documentation and acknowledgment -- making the data governance expectations explicit to collaborators at the time of invitation.

---

*End of review.*
