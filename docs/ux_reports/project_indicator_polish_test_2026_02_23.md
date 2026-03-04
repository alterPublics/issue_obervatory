# UX Test Report -- Project Indicator Polish Items
Date: 2026-02-23
Application: localhost:8000
Tester: UX Agent (researcher perspective)

## Scope

Two polish items tested against the live application:
1. Project indicator in QD editor and detail views (breadcrumbs, badge, navigation)
2. Graceful handling of invalid project_id query parameter

Test project used: "Greenland" (ID `1cd984df-9d6e-4f12-b5fa-39c09dc73a9a`, 2 query designs)

---

## Polish Item 1: Project Indicator in QD Views

### Test Steps and Results

| # | Action | Expected | Actual | Verdict |
|---|--------|----------|--------|---------|
| 1 | Log in as admin | Dashboard loads | Dashboard loads | PASS |
| 2 | Navigate to /projects, find Greenland | Project visible with 2 designs | Project card visible, "2 designs" count, links work | PASS |
| 3 | Click "New Query Design" from project detail | Goes to /query-designs/new?project_id=... | Link correctly includes project_id parameter | PASS |
| 4 | Verify breadcrumbs on new QD page with project | "Projects > Greenland > New Query Design" | Breadcrumbs show exactly: Projects (link) > Greenland (link to project) > New Query Design (plain text) | PASS |
| 5 | Verify "Part of project" badge on new QD page | Badge with folder icon showing project name | Present: folder icon SVG + "Part of project:" text + linked project name "Greenland" in blue | PASS |
| 6 | Verify hidden project_id input on new QD form | project_id included in form data | Hidden input with correct UUID value present | PASS |
| 7 | Navigate to QD detail page (Second UX Test Design) | Breadcrumbs include project | Breadcrumbs: Projects > Greenland > Second UX Test Design | PASS |
| 8 | Verify badge on QD detail page | "Part of project: Greenland" with folder icon | Present with folder icon SVG, linked project name | PASS |
| 9 | Verify back arrow on QD detail page | Arrow navigates to project, not QD list | Back arrow links to /projects/1cd984df-... with aria-label "Back to project" | PASS |
| 10 | Click Edit from QD detail page | Opens edit page | Opens /query-designs/.../edit | PASS |
| 11 | Verify breadcrumbs on edit page | "Projects > Greenland > Edit" | Breadcrumbs: Projects > Greenland > Edit | PASS |
| 12 | Verify badge on edit page | "Part of project: Greenland" with folder icon | Present, identical styling to new/detail pages | PASS |
| 13 | Verify hidden project_id input on edit form | project_id preserved during edit | Hidden input with correct UUID present | PASS |
| 14 | Navigate to /query-designs/new (no project_id) | "Query Designs > New" breadcrumbs | Breadcrumbs: Query Designs (link) > New (plain text) | PASS |
| 15 | Verify no badge on no-project page | No "Part of project" badge | No badge present, no project_id hidden input | PASS |
| 16 | Verify Cancel link on no-project page | Points to /query-designs | Cancel links to /query-designs | PASS |

### Summary for Polish Item 1

All core requirements pass. Breadcrumbs, badge, back arrow, and hidden form field are all correctly present when a project is associated and correctly absent when no project is associated. The visual presentation is consistent across new, detail, and edit views.

---

## Polish Item 2: Graceful Handling of Invalid project_id

### Test Steps and Results

| # | Action | Expected | Actual | Verdict |
|---|--------|----------|--------|---------|
| 17 | GET /query-designs/new?project_id=not-a-uuid | Page loads normally, no project badge | HTTP 200, breadcrumbs show "Query Designs > New", no badge, no project_id hidden input | PASS |
| 18 | GET /query-designs/new?project_id= (empty) | Page loads normally, no project badge | HTTP 200, breadcrumbs show "Query Designs > New", no badge, no project_id hidden input | PASS |
| 19 | GET /query-designs/new?project_id=00000000-0000-0000-0000-000000000000 (valid UUID format, non-existent project) | Page loads normally, no project badge, no hidden field | HTTP 200, breadcrumbs correct, no badge -- BUT hidden project_id input IS present with the non-existent UUID | PARTIAL FAIL |
| 20 | Submit form from step 19 | Graceful error or silent ignore | HTTP 500 with full SQLAlchemy stack trace: ForeignKeyViolationError exposed to user | FAIL |

### Details on the Non-Existent UUID Edge Case (Steps 19-20)

When a syntactically valid UUID is provided that does not match any existing project:

**Page load (step 19):** The page renders without a project badge or project breadcrumbs, which is visually correct. However, a hidden `<input type="hidden" name="project_id" value="00000000-0000-0000-0000-000000000000">` is included in the form. The researcher sees no indication that a project will be associated, but the form silently includes the bad reference.

**Form submission (step 20):** Submitting the form triggers an unhandled `IntegrityError` that produces a raw Python traceback visible to the researcher. The response is HTTP 500 with the full stack trace including:
- Internal table names (`query_designs`, `projects`)
- Constraint names (`query_designs_project_id_fkey`)
- SQL statements with parameter values
- Internal file paths on the server

From the researcher's perspective: they filled out a form, clicked "Create Query Design," and got a wall of incomprehensible technical text. They have no idea if their work was saved (it was not). There is no guidance on what went wrong or what to do next.

---

## Passed

- Breadcrumb rendering is correct and consistent across all three project-associated views (new, detail, edit)
- "Part of project" badge with folder icon appears correctly on all project-associated views
- Badge is a clickable link to the project detail page
- Back arrow on QD detail page correctly navigates to the project (not the QD list)
- Non-UUID project_id values ("not-a-uuid", empty string) are silently and correctly ignored
- No-project views correctly show "Query Designs > New/Edit" breadcrumbs without any project indicators
- Hidden project_id form field is correctly included when a valid project exists

## Friction Points

1. **Cancel link on "New QD" page with project does not return to the project.** When creating a new QD from within a project context, the Cancel link at the bottom of the form points to `/query-designs` (the generic QD list) rather than back to the project detail page. The breadcrumbs and badge make the project association clear, so clicking Cancel and landing on an unrelated page breaks the researcher's mental model of "I'm working inside this project." `[frontend]`

2. **Edit page Cancel link goes to QD detail, not project.** On the edit page, Cancel goes to the QD detail page. This is less of an issue because the QD detail page has the back arrow to the project, so the researcher can get back in two clicks. But the breadcrumbs suggest the researcher is within the project context, and Cancel arguably should go one level up in that breadcrumb hierarchy (to the project). This is a minor inconsistency. `[frontend]`

## Blockers

1. **Non-existent but valid-format UUID project_id causes 500 error on form submission.** A syntactically valid UUID that does not correspond to any project is accepted into the form's hidden field, and when the form is submitted, the application crashes with a raw traceback. The researcher sees internal database details, loses their form input, and has no recovery path. This is a blocker because: (a) it can happen if a project is deleted while a researcher has the new QD page open, and (b) the error page is a raw stack trace with no explanation or next steps. `[core]`

## Data Quality Findings

No data quality issues applicable to these polish items.

## Recommendations

Prioritized by severity:

1. **[core] Validate project_id existence before inserting query_design.** When the form submission includes a project_id, the route handler should verify the project exists (and belongs to the current user) before attempting the database insert. If the project is not found, either silently drop the association or return a user-friendly error message like "The selected project no longer exists. Your query design was created without a project association." This prevents the 500 crash.

2. **[core] Do not include hidden project_id field when project was not found.** On the page-rendering side, when a valid-format UUID is provided but no matching project is found in the database, the hidden `project_id` input should not be included in the form at all. Currently the page correctly omits the badge and breadcrumbs but still includes the hidden field, creating an inconsistent state.

3. **[frontend] Update Cancel link on "New QD with project" page to return to the project.** When `project_id` is present, the Cancel link should point to `/projects/{project_id}` instead of `/query-designs`. This maintains the researcher's context within the project workflow.

4. **[core] Add generic error handling for IntegrityError on form submission routes.** Even after fixing the specific project_id validation, form submission routes should catch `IntegrityError` and render a user-friendly error page rather than exposing raw tracebacks. This is a defense-in-depth measure that protects against similar issues in the future.
