# Validation — October 2026 (v0.1.0)

How the skill was checked before release. Every number below was measured on the stated run; nothing is estimated.

## 1. Test suite

`python3 -m unittest discover -s tests -t tests` → **49 tests, OK** (≈5 s, no network, no packages). Seven fixture repos under `tests/fixtures/`, all invented:

| Fixture | Pins down |
|---|---|
| `flask_app` | blueprint prefix → route URLs, guards, templates, SQL table access via a module constant, a write gateway, boundaries, dead-code candidates, convention-typed calls, `tests/` excluded |
| `fastapi_llm` | `include_router(prefix) + APIRouter(prefix)` order, the `llm` profile switched on by import (model through a constant, settings, roles `system → user`, output schema), `profiles.disable` |
| `django_site` | `path()` to function and class-based views, `models.Model` and `Meta.db_table` → tables, ORM use |
| `celery_jobs` | the `jobs` profile: task decorators and `.delay()` linked to the task |
| `src_layout_lib` | `src/` stripping, relative import, re-export through `__init__`, `self.method()`, a real import cycle told apart from a lazy one |
| `oo_lib` | attribute types from `__init__`, inherited methods of a library subclass, an imported module-level object, an annotated library parameter, SQLModel `table=True` |
| `broken` | a syntax error is recorded and skipped, never fatal |

Plus end-to-end CLI runs on copies: init → draft → build → check, staleness after a code change, a renamed function naming the stale narrative entry, a new module outside every layer, a `no_callers` finding breaking once a caller appears, Korean output with quotes round-tripping through TOML, both profile sections, and the Markdown report.

## 2. Real repositories (zero configuration)

`init → map → draft --depth standard → build`, default settings, on a copy of each repository.

| Repository | Kind | Files · lines | `map` | Resolved calls | Routes · tables | Draft |
|---|---|---|---|---|---|---|
| a private Flask app + batch loader + AWS CDK (the report this skill was generalised from) | web app | 126 · 53,087 | 0.8 s | **81.0 %** (hand-tuned original: 82.8 %) | 200 · 46 | 7 layers, 6 journeys, 15 boundary cards, 10 entities |
| fastapi/full-stack-fastapi-template | API + SQLModel | 27 · 1,686 | 0.1 s | **94.5 %** | 23 · 2 | 3 layers, 5 journeys, 2 entities |
| httpie/cli | class-heavy CLI library | 86 · 10,630 | 0.2 s | **66.5 %** | 0 · 0 | 3 layers, 2 journeys |

What the runs changed in the code (each now has a fixture test):

- Router prefixes were joined in module order (`/v1/api`); now mount prefix + declared prefix.
- A package's `__init__` module could land in two auto layers and fail the build.
- The analysed repo's own `SyntaxWarning`s were printed; now silenced.
- Methods inherited from a library base class, attributes set in `__init__`, objects imported from another module and annotated library parameters were unresolved (httpie 62.1 % → 66.5 %).
- SQLModel `table=True` models were not tables (FastAPI template: 0 → 2 tables).
- Draft journeys descended into plumbing helpers (`connect`, `log`) and ranked admin screens and one-off scripts above core flows; now hubs are not descended into, write paths go first, and journeys are ranked by how central the tables they write are (the private app's candidates changed from "change password, backfill script" to "submit feedback, call-centre intake, edit/delete contract, file a work log").

Known limit seen: one file in the FastAPI template uses Python 3.14 syntax (`except A, B:`) and is skipped on 3.12, listed as a finding.

## 2b. Call resolution in 0.2.0

The unresolved calls were classified first (receiver is a literal / name matches a function of the repo / builtin-type method name / unknown object / bare name). On the 53k-line app, three quarters of them were value methods (`row.get`, `items.append`); on httpie, half were calls whose name matches a method of the repo on objects of unknown type — real missed edges. The fixes in the changelog target both; each rule has a case in `tests/fixtures/types_lib`.

| Repository | 0.1.0 all call sites | 0.2.0 all call sites | 0.2.0 graph coverage | Internal edges 0.1.0 → 0.2.0 | Inferred edges |
|---|---|---|---|---|---|
| private Flask app (53k lines) | 81.0 % | 91.5 % | 96.2 % | 3,689 → 3,694 | 8 |
| fastapi/full-stack-fastapi-template | 94.5 % | 97.0 % | 97.2 % | 73 → 73 | 0 |
| httpie/cli | 66.5 % | 82.7 % | 83.3 % | 541 → 621 | 40 |

What still cannot be seen statically: parameters whose callers pass different or unknown types, objects returned by libraries without annotations, and callbacks invoked through a variable (`work(cur)`).

## 3. Accuracy spot checks

- `verify --edges 5` on the private app: 5 / 5 edges — the callee's name on the call line and on its `def` line.
- During the original hand-built report: 5 / 5 random edges and one 12-step journey walked against the source matched.

## 4. Page

Checked in a headless browser on the private app's report (953 KB): no page errors; no horizontal overflow at 390 px (full-page screenshot exactly 390 px wide); the Korean UI renders; the fade works — selecting `webapp.app` on the structure map keeps it, the modules it calls (teal) and its caller (amber), fades everything else to 22 %, and draws highlighted edges under the boxes; hovering a box in the call graph keeps only it, its neighbours and the edges between them.

## 5. SKILL.md acceptance test

A fresh agent with no prior context was given only the skill folder and the invented `examples/demo-shop` repository, with the step-1 answers fixed (English, quick, "learning the code"), and told to follow SKILL.md exactly.

| | |
|---|---|
| Wall-clock time | **≈ 4.5 min** (22:36:54 → 22:41:17), target ≤ 10 min for quick |
| Result | 3 journeys, 6 boundary cards, 4 entities, 9 findings (8 written and verified, 1 generated), **0 TODO left** |
| `build` / `verify` / `check` | exit 0 · 5 / 5 edges ok · up to date |
| Page | no errors and no console output at 390 px and 1440 px |

Gaps it reported, and what changed (each has a test in `tests/test_draft.py`):

| Reported | Fix |
|---|---|
| The draft dropped the handler's validation call (no sink below it) | A journey keeps every direct callee of the entry point; only deeper steps must lead to a sink |
| Two cards for one function (generic SDK card + model card) | A generic service card is dropped when profile cards cover all its functions |
| A bare `@shared_task` (no `.delay()`) got no card | Profile `draft_roles` receives the code map; the jobs profile drafts cards from decorators |
| SKILL.md requires `[[input_flows]]` but the draft made none | The draft proposes one per write route |
| `draft` and `todo` counted TODOs differently | One counter, including strings inside lists |
| "6–12 steps" does not fit short chains; swap guidance too narrow | Short journeys allowed when that is the whole chain; swap a journey that is only another's tail; add missing validation steps |
| No `init` option for the reader | `init --audience` |
| `evidence` said "lines read" while the rest says no line numbers | Evidence names functions/files and commands, no line numbers |
| `allowed-tools` lacked Write/Edit | Added |
| Running the vendored tools left `__pycache__/` in the target repo | No bytecode written; `init` adds `.gitignore` files |
