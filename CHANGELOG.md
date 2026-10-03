# Changelog

## 0.5.0 — 2026-10

Found by running the skill on a Streamlit + SQLModel app and on ten trending public repos.

- New `ui` stack profile (Streamlit, Gradio, NiceGUI): widgets and callbacks are entry points, so a script-style app gets journeys instead of none, plus a "UI triggers" table. Profiles can now add `on_module(ctx, tree)`, `triggers(records, code_map)` and `SINK = False`.
- ORM session writes count: `s.add(M(...))`, `s.delete(row)`, `s.merge`, `s.exec(select(M))` on a SQLAlchemy / SQLModel `Session` become table writes and reads, naming the exact model when the code says it (constructed, typed, or assigned from `select(M)` / `s.get(M, …)`). Journeys now end where the data lands.
- `with f() as s` binds the yielded type of a `@contextmanager` (`-> Iterator[Session]` / `Generator[...]`): +3.7 points resolved on a SQLModel app.
- An unresolved `x.get_secret_value()` is AWS Secrets Manager only in a module that imports boto3 (pydantic's `SecretStr` has the same method).
- Layer rules can forbid third-party packages (`forbid = ["streamlit"]`); the code map lists each module's top-level `packages`.
- `init` leaves `examples/`, `samples/`, `benchmarks/`, `notebooks/` … out of the scan when the repo has other code.
- `merge --check` validates a fragment without writing: parallel writers no longer overwrite each other's `narrative.toml`. A fragment entry `{ id = "...", drop = true }` removes a wrong drafted entry.

## 0.4.0 — 2026-10

- Module notes are now written, not copied: `[module_notes."pkg.mod"]` has `purpose` (why it exists), `does` (2–5 capabilities), `flow` (who calls it → what it goes through → where it writes) and an optional `note`. The module panel shows them as labelled rows, the index shows purpose and does, tooltips the purpose; search covers all four.
- `draft` no longer prefills notes from docstrings (a first sentence says too little to follow the flow); every module starts as a structured TODO.
- `codeflow.py module NAME …` prints what a writer needs first: callers, callees, tables, boundaries, functions.
- SKILL.md: module notes are written last, once the journeys are understood; large repos split them across parallel writers by layer. A missing `purpose`/`does`/`flow` or an unknown field fails the build.

## 0.3.0 — 2026-10

- `[module_notes]` in the narrative: one line per module, what it owns. Shown first in the module panel, map tooltips, the module index and search; the docstring stays as the fallback (and is shown under the note when both exist). Modules without a docstring no longer show an empty description.
- `draft` proposes a note for every module — the docstring's first sentence where there is one, a TODO where there is none. A note for a module that no longer exists fails the build.
- SKILL.md and the writer brief: one line per module, essentials only.
- Module index columns sized so names and layers no longer wrap.

## 0.2.0 — 2026-10

Call resolution, measured on three real repositories (all call sites → function calls):
httpie 66.5 % → 82.7 % / 83.3 %, a 53k-line Flask app 81.0 % → 91.5 % / 96.2 %, FastAPI template 94.5 % → 97.0 % / 97.2 %.

- Value types: literals, f-strings, `dict()`/`list()`/`sorted()`, string-method results; `a or b` and `x if c else y`; loop variables over library iterables.
- Return types of internal functions (annotation, or every `return` agreeing), class fields from annotations (dataclass / pydantic / `self.x: T`), `Optional[...]`, `X | None` and string annotations, `super().method()`.
- Call-site parameter inference: a parameter that receives the same known type at every call site gets it (a second pass).
- Inferred edges: unique method names, kept separate and drawn dotted.
- New `graph_coverage` metric next to the overall ratio; `code_map.json` schema 2 (an old map asks to be regenerated).

## 0.1.0 — 2026-10

First release.

- `codeflow.py` with `status`, `init`, `map`, `draft`, `candidates`, `query`, `find`, `todo`, `merge`, `build`, `verify`, `check`, `install-test`, `report`.
- Stack-agnostic extractor (`ast`): modules, functions, classes, call and reference edges, Flask / FastAPI / Starlette / Django routes with prefixes, SQL table access, ORM models (SQLAlchemy `__tablename__`, Django, SQLModel), write gateways, external boundaries, import cycles (module-level vs lazy), dead-code candidates, duplicate names. Type inference for locals, `with … as`, chained calls, annotated parameters, `self.x` attributes, imported module-level objects and inherited library methods.
- Stack profiles, routed by import: `llm` (model calls) and `jobs` (task queues and schedulers).
- Narrative draft from the code map: layers, ranked journey call chains, boundary cards, data lifecycles.
- Self-checking build: stale symbols, modules outside every layer, `no_callers` findings that are no longer true.
- One offline page, English and Korean, with fade-on-select for the structure map and the call graph.
