---
name: code-flow-report
description: Build an interactive, self-checking HTML report of how a Python codebase actually works — layers, the exact call chain of each main user journey (click → database → response, with example payloads), external boundaries and background jobs (plus model calls when the repo uses an LLM SDK), the untrusted-input path, data lifecycles, who decides what (code vs people), and findings where docs and code disagree. Structure is extracted from the source with `ast`; the hand-written narrative names only symbols, so a later code change makes the report fail its own check instead of drifting. Use when someone wants to understand, onboard onto, review or document an unfamiliar or complex Python repo — "how does this code work", "explain this codebase", "map the call flow", "architecture report", "code walkthrough", "코드가 어떻게 돌아가는지 보고서", "코드 흐름 보고서" — or asks to regenerate or update such a report after code changes.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/codeflow.py *) Bash(python3 docs/code-flow/tools/codeflow.py *) Read Grep Glob Write Edit
license: MIT
compatibility: Claude Code with Python 3.11+ on PATH as python3. Standard library only; the generated page works offline.
metadata:
  version: 0.5.0
  repository: https://github.com/JinhoKim46/code-flow-report
---

# Code flow report

Produces `docs/code-flow/code-flow-report.html` in the target repo: one offline page, generated from `code_map.json` (structure, extracted by script) plus `narrative.toml` (the explanation, written by you). Everything below is done through one command, `codeflow.py`; never write the extractor, the page or the JSON by hand.

`CF` below means `python3 ${CLAUDE_SKILL_DIR}/scripts/codeflow.py` before `init` and `python3 docs/code-flow/tools/codeflow.py` after it (init copies the scripts into the repo so anyone can rebuild without this skill).

## Ground rules

- **Facts come from the code.** Read the function before you describe it. Docs can be stale: when a doc and the code disagree, the code wins and the disagreement becomes a finding (cite both sides).
- **Name symbols, never line numbers.** `package.module:function`, `package.module:Class.method`, `package.module:outer.inner`. The builder adds `file:line`, so the narrative survives edits.
- **Never read or quote** `.env*`, secrets, credentials, or real personal/customer data. Example payloads use invented values only.
- **Size risks honestly**: what is true now, what trigger makes it go wrong, how far it reaches. No trigger and no reach → not a finding.
- **Report measurements**, not impressions: the resolved-call ratio, edges checked, what `check` printed.

## 1. Ask first (one AskUserQuestion call)

Run `CF status` (before init: `python3 ${CLAUDE_SKILL_DIR}/scripts/codeflow.py status`). If it says there is no Python source, stop and say so. If a report already exists, go to **§7 Regenerate** instead.

Then ask, together:
1. **Report language** — English (default, first option) / 한국어.
2. **Depth** — put the recommended one from `status` first: `quick` (3 journeys, ~10 min), `standard` (6 journeys, ~30 min), `deep` (12 journeys, everything filled).
3. **Reader** — learning the code / owns the code / reviewing it. This sets the tone and goes into `meta.audience`.

## 2. Map

```
CF init --lang <en|ko> --audience "<reader>" [--name "<project name>"]
CF map
```

Read the summary line. If **resolved < 60 %**, look at "most frequent unresolved" and fix the config before going on (`references/config.md`): a `src/` layout → `strip_prefixes`; a first parameter that is always the same kind of object (`cur`, `session`, `client`) → `param_types`; a shared write/audit wrapper → `gateways`; the wrong folders scanned → `scan.include`. Re-run `CF map` and note both numbers for the final report.

## 3. Draft

```
CF draft --depth <depth>
CF candidates          # every entry point ranked as a journey candidate (* = already chosen)
CF todo                # what is left to write
```

`draft` fills layers, journey call chains, boundary cards, stack-profile cards, input-flow candidates and data lifecycles from the code and leaves `TODO:` wherever prose is needed. Then judge the journeys against `candidates`: the set should cover the flows a newcomer most needs — for an app: sign-in, the main create/submit action, the main read screen, the main background job; for a library: its main public calls (e.g. `Agent().run()`), past virtual calls into the subclasses that do the work; for a pipeline: its stages in order; for a serverless app (the map line says "infrastructure … CDK"): the main request path, the main event-driven path (queue, schedule, upload), and one workflow, each crossing Lambdas as the infrastructure wires them. Swap out a journey that is an admin screen, a one-off script, or only the tail of another journey, and drop the drafted one with `drop = true` (copy the replacement's chain with `CF query <entry> --depth 3`). Add any step a chain is missing (a validation call, a permission check) and drop plumbing steps that add nothing. When two cards explain the same function, keep the more specific one.

## 4. Write the narrative

Replace every `TODO:`; delete a TODO'd item instead if it is not worth explaining. Field reference: `references/narrative-schema.md`.

- **quick**: write it yourself. Read README / main entry points first, then only the functions on each journey (`CF query <symbol>` shows a function's callers, callees, SQL and boundaries without reading whole files).
- **standard / deep**: split the work across parallel general-purpose agents, one per row below, each given `references/writing-brief.md` verbatim plus its assignment. Each writes **one fragment file** `docs/code-flow/.parts/<name>.toml` and never edits `narrative.toml`. Writers check their fragment with `CF merge --check <file>` (writes nothing); once all are done, you run `CF merge` once to fold them in (entries replace drafted ones with the same `id`).

| Writer | Assignment |
|---|---|
| journeys-a | first half of the journeys + the input flows they pass through |
| journeys-b | second half of the journeys |
| boundaries | every `[[roles]]` card (external services, background work, profile cards) + `[[decisions]]` |
| data | `[[entities]]`, `[[layers]]` `owns` text and `[[layer_rules]]`, doc-vs-code `[[findings]]` |
| modules-1 … n | `[module_notes]` for one or two layers each (split so each writer has ≤ ~25 modules); start after the journeys are merged so the writers can read them |

Always add, whatever the depth, **`[module_notes]` for every module — written last, once you understand the whole flow** (the journeys are done). For each module run `CF module <name>` (callers, callees, tables, boundaries, functions), read its header and the few functions that carry it, then fill:
  - `purpose` — why it exists: what would not work without it (one sentence);
  - `does` — what it does, as 2–5 capabilities, not a function list;
  - `flow` — who calls it and when → what it goes through → where it writes (name the real modules, tables, services);
  - `note` (optional) — a rule, trap or deliberate exception worth knowing.
  Concrete and short; never copy the docstring's first sentence, never pad ("This module is responsible for various…"). The draft leaves all of them as TODO on purpose. Then `meta.lede` (two sentences), at least two `[[decisions]]` (code vs people), `[[input_flows]]` for each place outside data enters (forms, uploads, imported files, API payloads, messages), and `[[findings]]` you verified. Give each finding the code can re-check a `check` (`no_callers`, `symbol_exists`, `text_in`, `calls`, `not_calls`) so it retires itself to the "Fixed" list once the code changes.

## 5. Build and self-check

```
CF build               # fails with a list if the narrative names something the code no longer has
CF verify --edges 5    # standard: --edges 20
```

- `build` must exit 0. Fix each listed problem (usually a typo'd symbol — `CF find <name>`).
- `verify`: every `??` line must be read and either explained or fixed; report how many of N matched.
- Walk **one journey** against the source: open each step's function and confirm the order and what it passes on. Fix the narrative where it is wrong.
- If a browser tool is available, open the HTML at phone and desktop width and confirm it renders without errors.

## 6. Report back

Tell the user, briefly:
- what the report covers (journeys, cards, entities, findings counts) and where it is (`docs/code-flow/code-flow-report.html`);
- coverage: resolved-call ratio and what static analysis cannot see (dynamic dispatch, calls inside templates, framework hook registration, SQL assembled at runtime, non-Python code);
- the top 5 findings with `file:line`;
- how to regenerate: `python3 docs/code-flow/tools/codeflow.py build`.

Then ask whether to install the staleness test (`CF install-test`): it fails whenever the report no longer matches the code, which keeps the report honest **and** means every PR that moves a function must run `build`. Install only on a yes.

Optional, only if asked for an overview/executive report: write `docs/code-flow/<date>-project-report.md` (goal, scope vs requirements → where met → evidence, architecture and key decisions with trade-offs, test status with real numbers from actually running the tests, risks, next steps; tables over prose) and render it with `CF report <file>.md`.

## 7. Regenerate after code changes

```
CF check               # lists exactly which narrative entries went stale
```

Fix only the listed entries (`CF query` / `CF find` to locate the renamed or moved code), then `CF build`. New TODOs from new modules: `CF todo`. Do not re-draft an existing narrative unless the user asks (`draft --force` overwrites it).

## Do not

- Edit `code-flow-report.html` or `code_map.json` by hand — they are regenerated.
- Write line numbers in the narrative, or invent test results, payloads from real data, or callers you did not see.
- Widen the scan to `tests/`, virtualenvs or generated code to raise the numbers.
