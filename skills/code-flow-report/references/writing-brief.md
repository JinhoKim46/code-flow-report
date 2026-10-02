# Brief for a narrative writer (give this to each parallel agent verbatim, plus its assignment)

You are writing part of the narrative for a code-flow report. The structure is already extracted; you add explanations. **Do not edit any source file and do not edit `docs/code-flow/narrative.toml`.** Write exactly one file: `docs/code-flow/.parts/<your-name>.toml`, containing complete `[[journeys]]` / `[[roles]]` / `[[entities]]` / … entries for your assignment (an entry with the same `id` as a drafted one replaces it).

Language: write all prose in **{LANGUAGE}**. Reader: **{AUDIENCE}**. Plain, concrete sentences; identifiers stay as they are in code.

## Tools (run from the repo root)

```
python3 docs/code-flow/tools/codeflow.py query <symbol-or-name> [--depth 2]   # callers, callees, SQL, boundaries, routes
python3 docs/code-flow/tools/codeflow.py find <text>                          # symbol names containing text
python3 docs/code-flow/tools/codeflow.py todo                                 # what is still TODO
python3 docs/code-flow/tools/codeflow.py merge docs/code-flow/.parts/<your-name>.toml   # dry check of your fragment
```

The drafted `narrative.toml` already holds call chains for the journeys — start from it, then read each step's function. Read only what you need: the functions on your chains and the files they live in. Do not sweep the whole repository.

## Rules

1. **Every fact comes from code you read.** Docs may be stale; where a doc disagrees with the code, the code wins — record it as a finding citing both (doc sentence + function).
2. **Symbols, not line numbers**: `pkg.mod:function`, `pkg.mod:Class.method`, `pkg.mod:outer.inner`. Use `find` when unsure of the exact name.
3. **Never read or quote** `.env*`, secrets, credentials, or real personal/customer data. Example payloads use invented values (e.g. "Jane Doe", "ACME Ltd", order 1042, 4200 cents).
4. **Journey steps** must be on the real call chain, in order. For each: what it receives, what it returns, what it stores, and one small realistic payload where data changes shape. Usually 6–12 steps; fewer is right when that is the whole chain. Add a missing validation or permission step; drop plumbing that adds nothing.
5. **Cards**: configuration means *where* (env var / config field names), never values. Unknown cost → "not measured".
6. **Findings**: state what is true now, the trigger that makes it go wrong, and how far it reaches. Severity `high` only for data loss, security, or money. A dead-code finding gets `check = "no_callers"`. Each finding has `evidence` saying how you verified it.
7. **Decisions**: one row per real decision — who makes it (`code` / `people` / `people (config file)` / `model`) and how.
8. Field reference: `references/narrative-schema.md` (in the skill) — severities `high|medium|low|info`; stages `born|transform|update|store|archive|restore|read|delete`.

## Done when

- `codeflow.py merge docs/code-flow/.parts/<your-name>.toml` reports **0 problems** for your fragment (it also merges it — that is fine).
- No `TODO` remains in your entries.
- Your final message lists: the file you wrote, counts per section, and anything you are unsure of. Do not paste the narrative back.
