# code-flow-report

**Ask Claude how a Python codebase works, and get one offline page that traces it call by call, from the click to the database. Every claim is checked against the source on each build.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](https://code.claude.com/docs/en/discover-plugins)
[![Python 3.11+ · stdlib only](https://img.shields.io/badge/python-3.11%2B%20%C2%B7%20stdlib%20only-3776ab.svg)](#faq)

![Structure map: one module selected, everything unconnected fades](docs/screenshot-structure.png)

<p align="center"><a href="#examples">Example reports</a> · <a href="#quick-start">Quick start</a> · <a href="#how-it-works">How it works</a> · <a href="#limits">Limits</a> · <a href="#faq">FAQ</a></p>

## Why

Reading an unfamiliar repo usually means grepping, guessing, and asking someone. A wiki page or diagram written last quarter is already wrong. code-flow-report gives a newcomer, a reviewer, or you six months from now the answer to *"what actually happens when a user does X?"*, without trusting anyone's memory.

- **Facts are extracted, not remembered.** Modules, call edges, routes, SQL and ORM access, SDK calls and widgets come from Python's `ast`. Nothing structural is typed by hand.
- **The explanation cannot drift.** The prose names code only by symbol (`shop.orders:create_order`). A rename or deletion makes the build fail and name the stale sentence. Findings re-check themselves and move to a "Fixed" list once the code no longer shows them.
- **Journeys, not file trees.** The main flows are traced step by step. Each step shows what a function receives, returns and stores, with a small example payload.
- **One file, no server.** A single offline HTML page that works on a phone, in English or Korean. The page loads no scripts from the network, and the tools are standard-library Python.
- **Yours to keep.** The tools are copied into your repo, so anyone can rebuild the page later without the plugin.

## Quick start

In Claude Code:

```
/plugin marketplace add JinhoKim46/code-flow-report
/plugin install code-flow-report@code-flow-report
```

Then, in any Python repo, ask:

```
how does this code work? make a code-flow report
```

You can also run `/code-flow-report:code-flow-report`. Claude asks three things: the report language (English or Korean), the depth (`quick` ≈ 3 journeys, `standard` ≈ 6, `deep` ≈ 12), and who will read it. Then it maps, drafts, writes and checks. The result is `docs/code-flow/code-flow-report.html`; open it in any browser.

<details>
<summary>From a shell, a specific scope, or updating</summary>

```bash
claude plugin marketplace add JinhoKim46/code-flow-report
claude plugin install code-flow-report@code-flow-report            # --scope project to share it with the repo
claude plugin update code-flow-report@code-flow-report             # third-party marketplaces do not auto-update
```
</details>

## What you get

| Section | The question it answers |
|---|---|
| **Layers** and a note for every module | What is each part for? Who calls it, what does it go through, and where does it write? Which import rules hold between layers? (They are re-checked on every build.) |
| **Journeys** | What happens, call by call, when a user signs in, submits, or opens the main screen, or when the nightly job runs? |
| **Boundaries and background work** | Where does the code leave its process: HTTP, cloud SDKs, databases, queues, email, files? What runs on its own? |
| **Model calls** *(when an LLM SDK is used)* | Which roles call a model, with which prompt builder, model setting and output schema, and through which gateway? |
| **UI triggers** *(Streamlit, Gradio, NiceGUI)* | Which button, chat box or upload runs which code? |
| **Untrusted input** | Where does outside text enter, and which checks does it pass before it is stored or sent on? |
| **Data lifecycles** | For each table, who creates, changes, reads and deletes its rows? |
| **Who decides** | Which decisions are made by code, by people (in config), or by a model? |
| **Findings** | Where do docs and code disagree? Also: real risks with their trigger and reach, dead or test-only code, and import cycles. |
| **Call-graph explorer** | Search anything. Click a node and everything unconnected fades. |

![A journey: one request as a sequence of calls, step by step](docs/screenshot-journey.png)

## How it works

```
 your repo ──ast──▶ code_map.json ──draft──▶ narrative.toml ──build──▶ code-flow-report.html
            (facts: symbols, calls,       (prose by Claude, names        (fails if the prose
             routes, SQL/ORM, SDKs)        symbols, never line numbers)    names missing code)
```

1. **Map** (seconds). The extractor reads every `.py` file and records modules, functions, call edges, routes, SQL and ORM access, external calls, and stack-specific shapes. It infers types from annotations, `with … as`, return types, `__init__` parameters, injected callables and call sites. It reports how much it could resolve, and the page shows that number too.
2. **Draft.** From the map it proposes the narrative skeleton: entry points ranked as journey candidates, their call chains, boundary and model cards (prefilled with schema and prompt builder where the code says them), data lifecycles and layers. Only the explanations are left as `TODO`.
3. **Write.** Claude reads the functions on each chain and fills in the prose. At larger depths it splits the work across parallel agents. Each writes one fragment and validates it without touching the others, then the fragments are merged once. Module notes are written last, after the whole flow is understood.
4. **Build and check.** Every symbol the narrative names is checked against the map. Random call edges are printed next to their source lines to be read by eye, and one journey is walked against the code.

<details>
<summary>What it adds to your repo</summary>

```
docs/code-flow/
├─ codeflow.toml            settings detected at init (editable)
├─ code_map.json            extracted structure (generated)
├─ narrative.toml           the explanations (the only hand-written file)
├─ code-flow-report.html    the report (generated)
└─ tools/                   a copy of the scripts: python3 docs/code-flow/tools/codeflow.py build
```

Optional, and only if you say yes: `tests/test_code_flow.py`, a unittest that fails when the report no longer matches the code.
</details>

## Commands

You rarely need these: Claude runs them for you. After `init` they are all `python3 docs/code-flow/tools/codeflow.py <command>`.

| Command | Does |
|---|---|
| `status` | repo size, whether a report exists, recommended depth |
| `init` | detect settings and copy the tools into the repo |
| `map` | extract `code_map.json` and print coverage |
| `draft --depth quick\|standard\|deep` | propose the narrative skeleton |
| `candidates` | every entry point ranked as a journey candidate |
| `query SYMBOL` · `find TEXT` · `module NAME` | callers, callees, tables and boundaries of a function or module, for whoever writes the prose |
| `todo` | what is still unwritten |
| `merge [--check] [FILE…]` | fold writers' fragments into the narrative (`--check` validates without writing) |
| `build` | validate the narrative and write the page |
| `verify --edges N` | random call edges next to their source lines |
| `check` | fail if the map, narrative or page is out of date |
| `install-test` | add the staleness unittest |
| `report FILE.md` | render a Markdown document in the same look |

## Configuration

`init` writes `docs/code-flow/codeflow.toml` from what the repo looks like. You only edit it when the resolved share is low or the wrong folders were scanned.

```toml
[scan]
include = ["app", "src"]          # folders to read; examples/, samples/, benchmarks/ are left out by default
exclude = ["tests", "migrations"] # tests are still read, but only to find "only tests call this"
strip_prefixes = ["src"]          # src layout: src/pkg/mod.py is the module pkg.mod

[conventions]
param_types = { cur = "db.cursor()" }   # a first parameter that always means the same kind of object
gateways = ["run_write"]                # a shared write/audit wrapper whose first string argument is an action label

[profiles]
enable = []                       # force a stack profile on…
disable = []                      # …or off
```

Full reference: [`references/config.md`](skills/code-flow-report/references/config.md).

## Stack profiles

The core knows only generic shapes: calls, imports, routes, SQL and ORM, external SDKs. Stack detail is added by profiles, which switch on only when the repo imports that stack.

| Profile | Switched on by | Adds |
|---|---|---|
| `llm` | openai, anthropic, litellm, langchain, google, ollama, mistralai, … | Model calls with provider, model, settings, message roles and schema. It finds your own wrappers around the SDK (`LLMClient.chat_json`) and records every call to them as a role. |
| `jobs` | celery, rq, dramatiq, huey, apscheduler, schedule, arq, prefect, airflow, … | Tasks, schedules and enqueue sites, so that work with no visible caller shows up |
| `ui` | streamlit, gradio, nicegui | Buttons, chat inputs, uploads and callbacks as journey entry points, plus a "UI triggers" table |

A profile is one Python file. See [`references/profiles.md`](skills/code-flow-report/references/profiles.md).

## Examples

| Repository | What it shows | Report |
|---|---|---|
| [`examples/demo-shop`](examples/demo-shop) (invented) | Flask routes, SQL, a background job, an LLM call | [code-flow-report.html](examples/demo-shop/docs/code-flow/code-flow-report.html) |

To view a report, download the HTML file and open it, or browse it through any static file host.

## Measured

Maps built with zero configuration:

| Repository | Kind | Size | Map time | Function calls resolved (graph coverage) | All call sites resolved |
|---|---|---|---|---|---|
| a private Flask app + batch loader + CDK | web app | 126 files · 53k lines | 1.7 s | **96.2 %** | 91.5 % |
| a Streamlit + SQLModel LLM app | app with an LLM layer | 53 files · 7.6k lines | 1.7 s | **94.6 %** | 93.8 % |
| fastapi/full-stack-fastapi-template | API + ORM | 27 files · 1.7k lines | 0.1 s | **97.2 %** | 97.0 % |
| httpie/cli | class-heavy CLI library | 86 files · 10.6k lines | 0.4 s | **83.3 %** | 82.7 % |

On the Streamlit app, the generic skill was compared with a report built from a 1,633-line extractor written for that app. The two maps share the same 253 functions and 580 call edges. They agree on all 9 model call sites (7 roles), all injected callables and all table readers, writers and deleters, and both find the one function that only tests call.

*Graph coverage* is the share of function calls whose target is known. It leaves out builtins, and calls that only look like methods on plain values (`row.get` on an untyped variable). A method name that exists in exactly one class is drawn as a dotted *inferred* edge and is never counted as resolved. Method: [`docs/validation-2026-10.md`](docs/validation-2026-10.md).

## Limits

What static analysis cannot see, and what the report does about it:

- **Dynamic dispatch**: `getattr`, callback tables, plugin registries. These calls are not edges. The page shows the most frequent unresolved names, so you can tell how much is hidden.
- **Calls from outside Python**: templates, SQL built at runtime, framework hooks registered by name. Journeys stop at the boundary, and the step says so.
- **Values known only at run time**: environment-dependent config, feature flags. Cards name *where* a value is configured, never its value.
- **Python only.** Other languages would need an extractor adapter.
- **Newer syntax than the running Python**: such files are skipped and listed as a finding.

## Privacy

- Extraction, build and checks run locally. The tools make no network calls, and the page loads nothing from the network.
- The prose is written by Claude in your own Claude Code session, so code reaches only the model you already use there.
- Writers are told never to read `.env*` files, secrets or real personal data, and to use invented values in example payloads.

## FAQ

**Does it run my code?** No. It parses the source with `ast` and never imports it.

**How long does it take?** The map takes seconds. Writing takes about 10 minutes at `quick`, 30 at `standard`, and longer at `deep`, mostly spent reading functions.

**What does it cost?** Only the Claude usage of your session. `quick` fits in a single session; `standard` and `deep` use parallel agents.

**My repo is large.** Use `quick` or `standard`. Journeys cover the main flows, and module notes are split across writers by layer, at most about 25 modules each.

**The code changed. Do I start over?** No. Ask Claude to *"regenerate the code-flow report"*. `check` lists the stale entries, and only those are rewritten.

**Why standard library only?** So the copied tools keep working in any repo, CI job or teammate's machine, with nothing to install.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `build` says *the narrative no longer matches the code* | Each line names an entry and the missing symbol. Find the new name with `find NAME` and fix that entry. |
| Low resolved share after `map` | Read *most frequent unresolved*. Set `strip_prefixes` for a `src/` layout and `param_types` for a recurring first parameter, and check `scan.include`. |
| A finding moved to "Fixed" | Its `check` no longer holds in the code. If it really is fixed, leave it as history or delete it. If not, correct the check. |
| No journeys proposed | The repo's entry points may be a shape the core does not know yet. Run `candidates`, then add a journey by hand with `query ENTRY --depth 3`. |

## Contributing

Issues and pull requests are welcome, especially new stack profiles and fixture repos that show a missed shape.

```bash
python3 -m unittest discover -s tests -t tests   # fixture repos under tests/fixtures/
python3 tests/make_fixtures.py                    # regenerate the fixtures
python3 examples/make_demo.py                     # regenerate the example app
claude plugin validate . --strict
```

Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
