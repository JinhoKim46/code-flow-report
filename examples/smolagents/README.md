# smolagents — example code-flow report

**[Open the report](code-flow-report.html)** (download it and open it in a browser; it is one offline file).

[huggingface/smolagents](https://github.com/huggingface/smolagents) — A library for building LLM agents that write and run Python code. Analysed at commit [`c30b115`](https://github.com/huggingface/smolagents/tree/c30b115286e000e98711fae5e85993547b73d826) (2026-09-30); every `file:line` in the report links to that commit.

What this example shows: a library: entry points are its public API (`CodeAgent().run()`), virtual calls across the agent and model class hierarchies, model gateways and code executors.

| | |
|---|---|
| Size | 18 files · 12,774 lines · 460 functions and methods |
| Resolved | 88.5% of function calls (graph coverage) · 88.7% of all call sites |
| Journeys | 6, 59 steps |
| Boundary and model cards | 15 |
| Entities · input paths · decisions | 0 · 5 · 10 |
| Layers · layer rules | 7 · 6 |
| Module notes | 18 |
| Findings | 24 — 0 high, 6 medium, 9 low, 9 info |

Files: `code-flow-report.html` (the page), `narrative.toml` (everything Claude wrote: prose naming symbols only), `code_map.json` (extracted structure), `codeflow.toml` (settings).

Findings are what the writers verified in the code at that commit; they are not reports to the project, and some may be deliberate design choices. The source code remains under its own license (Apache-2.0); this report only names its symbols and quotes short docstrings.

Rebuild it yourself: clone the repo at that commit, copy `codeflow.toml` and `narrative.toml` into `docs/code-flow/`, then ask Claude Code to *"regenerate the code-flow report"* (or run `init`, then `build`).
