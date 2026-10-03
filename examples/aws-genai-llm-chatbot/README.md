# aws-genai-llm-chatbot — example code-flow report

**[Open the report](code-flow-report.html)** (download it and open it in a browser; it is one offline file).

[aws-samples/aws-genai-llm-chatbot](https://github.com/aws-samples/aws-genai-llm-chatbot) — A multi-model LLM chatbot on AWS: AppSync GraphQL API, Python Lambdas, Bedrock and SageMaker models, RAG over Aurora, OpenSearch, Kendra and Bedrock knowledge bases, deployed with TypeScript CDK. Analysed at commit [`b7283c5`](https://github.com/aws-samples/aws-genai-llm-chatbot/tree/b7283c59ecf95dd3f0e7e2f9041b7cac26353ec0) (2026-06-30); every `file:line` in the report links to that commit.

What this example shows: a full serverless stack: TypeScript CDK read for its wiring — every Lambda linked to the Python function it runs, journeys crossing AppSync, SNS, SQS, Step Functions and EventBridge into the next Lambda, grants and environment variables per function.

| | |
|---|---|
| Size | 155 files · 15,670 lines · 490 functions and methods |
| Resolved | 88.0% of function calls (graph coverage) · 78.8% of all call sites |
| Journeys | 6, 60 steps |
| Boundary and model cards | 40 |
| Entities · input paths · decisions | 7 · 4 · 11 |
| Layers · layer rules | 10 · 6 |
| Module notes | 155 |
| Infrastructure (TypeScript CDK) | 93 resources · 181 wiring edges · 17 of 20 Lambdas linked to their Python handler |
| Findings | 29 — 0 high, 11 medium, 14 low, 4 info |

Files: `code-flow-report.html` (the page), `narrative.toml` (everything Claude wrote: prose naming symbols only), `code_map.json` (extracted structure), `codeflow.toml` (settings).

Findings are what the writers verified in the code at that commit; they are not reports to the project, and some may be deliberate design choices. The source code remains under its own license (MIT-0); this report only names its symbols and quotes short docstrings.

Rebuild it yourself: clone the repo at that commit, copy `codeflow.toml` and `narrative.toml` into `docs/code-flow/`, then ask Claude Code to *"regenerate the code-flow report"* (or run `init`, then `build`).
