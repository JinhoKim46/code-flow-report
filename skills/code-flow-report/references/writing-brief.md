# Brief for a narrative writer (give this to each parallel agent verbatim, plus its assignment)

You are writing part of the narrative for a code-flow report. The structure is already extracted; you add explanations. **Do not edit any source file and do not edit `docs/code-flow/narrative.toml`.** Write exactly one file: `docs/code-flow/.parts/<your-name>.toml`, containing complete `[[journeys]]` / `[[roles]]` / `[[entities]]` / … entries for your assignment (an entry with the same `id` as a drafted one replaces it).

Language: write all prose in **{LANGUAGE}**. Reader: **{AUDIENCE}**. Plain, concrete sentences; identifiers stay as they are in code.

## Tools (run from the repo root)

```
python3 docs/code-flow/tools/codeflow.py query <symbol-or-name> [--depth 2]   # callers, callees, SQL, boundaries, routes
python3 docs/code-flow/tools/codeflow.py find <text>                          # symbol names containing text
python3 docs/code-flow/tools/codeflow.py todo                                 # what is still TODO
python3 docs/code-flow/tools/codeflow.py infra [filter]                       # CDK resources, which Python handler each Lambda runs, and the wiring
python3 docs/code-flow/tools/codeflow.py merge --check docs/code-flow/.parts/<your-name>.toml   # validate your fragment (writes nothing)
```

The drafted `narrative.toml` already holds call chains for the journeys — start from it, then read each step's function. Read only what you need: the functions on your chains and the files they live in. Do not sweep the whole repository.

## Rules

- **Infrastructure** (when `infra` prints resources): journey steps name Python symbols; when a journey crosses infrastructure (an API route, a queue, a topic, a Step Functions state machine), say so in the step's text ("publishes to SNS MessagesTopic → SQS → Lambda RequestHandler") and continue with the next Lambda's handler. DynamoDB tables and S3 buckets are not SQL tables: name them in text, not in a `tables` field. Read the `.ts` / CDK files when you need detail.

0. A drafted entry that is wrong (a false detection, a duplicate) is removed by writing `{ id = "<its id>", drop = true }` — as `[[roles]]` / `[[journeys]]` … with just `id` and `drop = true`.

1. **Every fact comes from code you read.** Docs may be stale; where a doc disagrees with the code, the code wins — record it as a finding citing both (doc sentence + function).
2. **Symbols, not line numbers**: `pkg.mod:function`, `pkg.mod:Class.method`, `pkg.mod:outer.inner`. Use `find` when unsure of the exact name.
3. **Never read or quote** `.env*`, secrets, credentials, or real personal/customer data. Example payloads use invented values (e.g. "Jane Doe", "ACME Ltd", order 1042, 4200 cents).
4. **Journey steps** must be on the real call chain, in order. For each: what it receives, what it returns, what it stores, and one small realistic payload where data changes shape. Usually 6–12 steps; fewer is right when that is the whole chain. Add a missing validation or permission step; drop plumbing that adds nothing.
5. **Module notes** (`[module_notes."pkg.mod"]`): `purpose` (why it exists — one sentence), `does` (2–5 capabilities, not a function list), `flow` (who calls it and when → what it goes through → where it writes, with real module/table names), optional `note` (a rule or trap). Start from `codeflow.py module <name>`, read the header and the key functions. Never copy the docstring's first sentence; no filler.
6. **Cards**: configuration means *where* (env var / config field names), never values. Unknown cost → "not measured".
7. **Findings**: state what is true now, the trigger that makes it go wrong, and how far it reaches. Severity `high` only for data loss, security, or money. Give every finding the code can re-check a `check` so it retires itself once fixed: `"no_callers"` (dead code), `"symbol_exists"`, `{ kind = "text_in", pattern = "<regex>" }`, `{ kind = "calls", target = "m:f" }` or `{ kind = "not_calls", target = "m:f" }` — all about `symbols[0]`. Each finding has `evidence` saying how you verified it.
8. **Decisions**: one row per real decision — who makes it (`code` / `people` / `people (config file)` / `model`) and how.
9. Field reference: `references/narrative-schema.md` (in the skill) — severities `high|medium|low|info`; stages `born|transform|update|store|archive|restore|read|delete`.

## Done when

- `codeflow.py merge --check docs/code-flow/.parts/<your-name>.toml` reports **0 problems** for your fragment (it also prints any layer rule the code breaks, marked `!`). Never run `merge` without `--check`: other writers are working at the same time, and the dispatcher merges all fragments once you are all done.
- No `TODO` remains in your entries.
- Your final message lists: the file you wrote, counts per section, and anything you are unsure of. Do not paste the narrative back.
