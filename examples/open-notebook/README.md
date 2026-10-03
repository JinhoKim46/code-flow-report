# open-notebook — example code-flow report

**[Open the report](code-flow-report.html)** (download it and open it in a browser; it is one offline file).

[lfnovo/open-notebook](https://github.com/lfnovo/open-notebook) — An open-source NotebookLM alternative: FastAPI + LangGraph + SurrealDB. Analysed at commit [`5f021c5`](https://github.com/lfnovo/open-notebook/tree/5f021c5405f825a7201f92e6d5fb92f546c3b503) (2026-10-02); every `file:line` in the report links to that commit.

What this example shows: a web app: 116 FastAPI routes, SurrealDB tables from SurrealQL migrations, active-record models, a background command queue, LangChain/esperanto model roles.

| | |
|---|---|
| Size | 84 files · 20,952 lines · 523 functions and methods |
| Resolved | 87.9% of function calls (graph coverage) · 89.1% of all call sites |
| Journeys | 6, 61 steps |
| Boundary and model cards | 18 |
| Entities · input paths · decisions | 15 · 5 · 13 |
| Layers · layer rules | 10 · 8 |
| Module notes | 84 |
| Findings | 31 — 0 high, 8 medium, 16 low, 7 info |

Files: `code-flow-report.html` (the page), `narrative.toml` (everything Claude wrote: prose naming symbols only), `code_map.json` (extracted structure), `codeflow.toml` (settings).

Findings are what the writers verified in the code at that commit; they are not reports to the project, and some may be deliberate design choices. The source code remains under its own license (MIT); this report only names its symbols and quotes short docstrings.

Rebuild it yourself: clone the repo at that commit, copy `codeflow.toml` and `narrative.toml` into `docs/code-flow/`, then ask Claude Code to *"regenerate the code-flow report"* (or run `init`, then `build`).
