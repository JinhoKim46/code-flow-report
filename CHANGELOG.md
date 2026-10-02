# Changelog

## 0.1.0 — 2026-10

First release.

- `codeflow.py` with `status`, `init`, `map`, `draft`, `candidates`, `query`, `find`, `todo`, `merge`, `build`, `verify`, `check`, `install-test`, `report`.
- Stack-agnostic extractor (`ast`): modules, functions, classes, call and reference edges, Flask / FastAPI / Starlette / Django routes with prefixes, SQL table access, ORM models (SQLAlchemy `__tablename__`, Django, SQLModel), write gateways, external boundaries, import cycles (module-level vs lazy), dead-code candidates, duplicate names. Type inference for locals, `with … as`, chained calls, annotated parameters, `self.x` attributes, imported module-level objects and inherited library methods.
- Stack profiles, routed by import: `llm` (model calls) and `jobs` (task queues and schedulers).
- Narrative draft from the code map: layers, ranked journey call chains, boundary cards, data lifecycles.
- Self-checking build: stale symbols, modules outside every layer, `no_callers` findings that are no longer true.
- One offline page, English and Korean, with fade-on-select for the structure map and the call graph.
