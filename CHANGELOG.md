# Changelog

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
