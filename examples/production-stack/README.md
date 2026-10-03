# production-stack — example code-flow report

**[Open the report](code-flow-report.html)** (download it and open it in a browser; it is one offline file).

[vllm-project/production-stack](https://github.com/vllm-project/production-stack) — vLLM's production stack: a Python router that sends each OpenAI-compatible request to one of several vLLM engines, deployed with a Helm chart. Analysed at commit [`014d070`](https://github.com/vllm-project/production-stack/tree/014d070e6f7611978d321bdb05cbe9a934b614e7) (2026-10-02); every `file:line` in the report links to that commit.

What this example shows: the Helm chart rendered from values.yaml — Ingress → Service → router Deployment, linked through its Dockerfile ENTRYPOINT and the vllm-router console script to vllm_router.app:main; one engine Deployment per model, its Secret, ConfigMaps and shared volume; third-party engine images listed but not counted.

| | |
|---|---|
| Size | 69 files · 11,443 lines · 396 functions and methods |
| Resolved | 95.4% of function calls (graph coverage) · 91.6% of all call sites |
| Journeys | 6, 44 steps |
| Boundary and model cards | 10 |
| Entities · input paths · decisions | 7 · 3 · 13 |
| Layers · layer rules | 9 · 5 |
| Module notes | 69 |
| Infrastructure (Helm, Kubernetes, Terraform CDK) | 28 resources · 13 wiring edges · 1 of 1 Lambdas linked to their Python handler |
| Findings | 31 — 0 high, 16 medium, 12 low, 3 info |

Files: `code-flow-report.html` (the page), `narrative.toml` (everything Claude wrote: prose naming symbols only), `code_map.json` (extracted structure), `codeflow.toml` (settings).

Findings are what the writers verified in the code at that commit; they are not reports to the project, and some may be deliberate design choices. The source code remains under its own license (Apache-2.0); this report only names its symbols and quotes short docstrings.

Rebuild it yourself: clone the repo at that commit, copy `codeflow.toml` and `narrative.toml` into `docs/code-flow/`, then ask Claude Code to *"regenerate the code-flow report"* (or run `init`, then `build`).
