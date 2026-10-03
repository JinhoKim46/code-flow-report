# nanochat — example code-flow report

**[Open the report](code-flow-report.html)** (download it and open it in a browser; it is one offline file).

[karpathy/nanochat](https://github.com/karpathy/nanochat) — A full-stack ChatGPT clone in one small codebase: tokenizer, pretraining, SFT, RL, eval, chat. Analysed at commit [`92d63d4`](https://github.com/karpathy/nanochat/tree/92d63d4e8bb4df75c3b71618f31ddde2378b2bcd) (2026-07-03); every `file:line` in the report links to that commit.

What this example shows: an ML pipeline: training scripts whose work is top-level code, files on disk instead of a database, distributed training.

| | |
|---|---|
| Size | 30 files · 6,715 lines · 205 functions and methods |
| Resolved | 80.2% of function calls (graph coverage) · 83.7% of all call sites |
| Journeys | 6, 49 steps |
| Boundary and model cards | 8 |
| Entities · input paths · decisions | 0 · 0 · 8 |
| Layers · layer rules | 8 · 6 |
| Module notes | 30 |
| Findings | 15 — 0 high, 3 medium, 7 low, 5 info |

Files: `code-flow-report.html` (the page), `narrative.toml` (everything Claude wrote: prose naming symbols only), `code_map.json` (extracted structure), `codeflow.toml` (settings).

Findings are what the writers verified in the code at that commit; they are not reports to the project, and some may be deliberate design choices. The source code remains under its own license (MIT); this report only names its symbols and quotes short docstrings.

Rebuild it yourself: clone the repo at that commit, copy `codeflow.toml` and `narrative.toml` into `docs/code-flow/`, then ask Claude Code to *"regenerate the code-flow report"* (or run `init`, then `build`).
