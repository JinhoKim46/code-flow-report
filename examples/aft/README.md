# aft — example code-flow report

**[Open the report](code-flow-report.html)** (download it and open it in a browser; it is one offline file).

[aws-ia/terraform-aws-control_tower_account_factory](https://github.com/aws-ia/terraform-aws-control_tower_account_factory) — AWS Control Tower Account Factory for Terraform: a serverless pipeline of Lambdas, DynamoDB streams, an SQS FIFO queue, EventBridge and Step Functions that creates and customises AWS accounts. Analysed at commit [`c5d8717`](https://github.com/aws-ia/terraform-aws-control_tower_account_factory/tree/c5d871757803f73e0ffa144f433e6038b59f366b) (2026-09-17); every `file:line` in the report links to that commit.

What this example shows: Terraform modules read for their wiring — every Lambda linked to its Python handler through a module input, the packaging module's output and its archive_file; Step Functions tasks and IAM policies read through templatefile(); stream triggers, EventBridge targets and per-statement grants.

| | |
|---|---|
| Size | 51 files · 6,057 lines · 229 functions and methods |
| Resolved | 98.4% of function calls (graph coverage) · 96.3% of all call sites |
| Journeys | 6, 51 steps |
| Boundary and model cards | 33 |
| Entities · input paths · decisions | 8 · 3 · 16 |
| Layers · layer rules | 10 · 6 |
| Module notes | 51 |
| Infrastructure (Terraform CDK) | 163 resources · 54 wiring edges · 18 of 18 Lambdas linked to their Python handler |
| Findings | 22 — 0 high, 3 medium, 11 low, 8 info |

Files: `code-flow-report.html` (the page), `narrative.toml` (everything Claude wrote: prose naming symbols only), `code_map.json` (extracted structure), `codeflow.toml` (settings).

Findings are what the writers verified in the code at that commit; they are not reports to the project, and some may be deliberate design choices. The source code remains under its own license (Apache-2.0); this report only names its symbols and quotes short docstrings.

Rebuild it yourself: clone the repo at that commit, copy `codeflow.toml` and `narrative.toml` into `docs/code-flow/`, then ask Claude Code to *"regenerate the code-flow report"* (or run `init`, then `build`).
