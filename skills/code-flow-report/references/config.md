# codeflow.toml — repo-specific knowledge

`codeflow.py init` writes `docs/code-flow/codeflow.toml` from what the repo looks like. Change it only when `map` shows something is off, then re-run `map`.

| Section · key | Meaning | When to change |
|---|---|---|
| `paths.root` | Repo root relative to this file | Only if you move the folder |
| `project.name` / `language` / `audience` | Title, page language (`en`/`ko`), reader | Language is asked at the start |
| `project.repo_url` | e.g. `https://github.com/org/repo/blob/main` — `file:line` become web links | Set when the report is shared; empty = relative file links |
| `project.store_name` | Label of the database lane in journey diagrams | e.g. "PostgreSQL" |
| `scan.include` | Folders/files to analyse (default: every top-level folder with `.py`) | Wrong or too-wide scope |
| `scan.exclude` | Folder names to skip anywhere (tests, venvs, build output, docs …) | Generated code or vendored libraries still scanned |
| `scan.exclude_globs` | Path globs to skip, e.g. `"pkg/legacy/*"` | Finer exclusions |
| `scan.strip_prefixes` | Leading path parts that are not part of module names, e.g. `["src"]` | `src/` layout not detected; imports unresolved |
| `scan.schema_globs` | Where CREATE TABLE/VIEW statements live (default `**/*.sql`) | Schema elsewhere |
| `conventions.param_types` | First-parameter names that always mean one kind of object: `{cur = "db.cursor()", session = "db.session()"}` | Many unresolved `execute` / `query` / `add` calls |
| `conventions.returns` | Internal functions whose return type is known: `{"app.db:connect" = "psycopg.connect"}` | Calls on a connection returned by a wrapper stay unresolved |
| `conventions.gateways` | Function names whose first string argument names an action (a shared write/audit wrapper): `["run_write"]` | The repo funnels writes through one function |
| `conventions.route_prefixes` | Extra blueprint/router variable → URL prefix: `{api = "/api/v1"}` | Prefix set in a way the extractor cannot see |
| `conventions.entry_names` | Function names never reported as dead code (entry points) | Framework hooks reported as dead |
| `conventions.noisy_services` | Boundary services hidden by default in the call-site table | Template rendering, IaC |
| `infra.enabled` | Read AWS CDK code (TypeScript or Python) for resources, wiring and the Python handler of each Lambda; on by default, and it only does something when CDK code is present | Switch off for a repo whose CDK code is unrelated to the scanned Python |
| `profiles.enable` / `disable` | Force a stack profile on or off (normally routed by imports) | False positive / negative |

Reading the `map` summary:

- **graph coverage** = calls with a known target (internal + library + by-convention) / calls that are not builtins and do not merely look like value methods. This is the figure that says how much of the call graph is visible; 85–97 % is typical. Below ~75 % look at "most frequent unresolved".
- **resolved** = (internal + library + builtin + by-convention) / all call sites — the same, without leaving anything out.
- **inferred edges**: a method called on an object of unknown type whose name exists in exactly one class of the repo. Drawn dotted, never counted as resolved.
- **unresolved that look like value methods**: unresolved calls named like a `dict`/`list`/`str` method (`get`, `append`, `strip`) that no class of the repo defines.
- **by convention** counts calls resolved only through `param_types` — reported separately so the ratio stays honest.
- **parse errors** are files `ast` could not read (syntax for a newer/older Python, templates with `.py` names); they are skipped, listed as a finding, and never stop the run.
