# Changelog

## 0.6.0 — 2026-10

The whole stack: infrastructure as code.

- **AWS CDK, TypeScript or Python.** A new scanner (`scripts/infra.py`, standard library only, comments and strings respected, brackets matched) reads the infrastructure and adds an "Infrastructure" section to the page:
  - **Resources:** Lambda, API Gateway, AppSync, SQS, SNS, EventBridge, Step Functions, DynamoDB, S3, Aurora/RDS, OpenSearch, Kendra, Cognito, IAM roles, KMS, Secrets Manager, SSM, CloudFront, ECS, SageMaker, CodeBuild.
  - **Wiring:** API routes with their paths, event sources, S3 notifications to Lambda, SQS or SNS, subscriptions, EventBridge targets and schedules, AppSync data sources, Step Functions `LambdaInvoke` tasks, `grant*` permissions, and environment variables that name a resource.
- **Lambda → Python.** Each Lambda's `handler` and code asset (`Code.fromAsset(path.join(__dirname, …))`, `from_asset("…")`, `PythonFunction(entry, index, handler)`) resolve to the Python function it runs.
  - That function becomes a journey entry whose trigger reads like "S3 UploadBucket (S3 event) → SQS IngestionQueue (Sqs) → Lambda UploadHandler".
  - The draft makes one card per Lambda, prefilled with what invokes it, what it may use and what its environment names.
  - On aws-samples/aws-genai-llm-chatbot: 93 resources, 181 wiring edges, and all 17 Python Lambdas linked (the other 3 run Node.js).
- **References are followed the way CDK code passes them:**
  - import aliases (`Function as LambdaFunction`);
  - properties of the repo's own constructs (`storage.ordersTable`) and nested chains (`ragEngines.auroraPgVector.createAuroraWorkspaceWorkflow`), including instances created behind a condition;
  - `this.x = y` aliases;
  - `props.x` back to what the parent passed, `...props` spreads included;
  - a helper's parameter back to the argument it is called with.
- `codeflow.py infra [filter]` prints the resources and the wiring for whoever writes the narrative; `[infra] enabled = false` switches the scanner off.
- A bare `import openai` never resolves to a module inside another package (`…/adapters/openai.py`): the third-party package wins.
- Drafted layers no longer put a subpackage's `__init__` in two layers.
- `integtests/`, `integration_tests/` and `e2e/` are test folders.
- New example: [aws-genai-llm-chatbot](examples/aws-genai-llm-chatbot).

## 0.5.0 — 2026-10

Found by running the skill on a Streamlit + SQLModel app, comparing it with a report built by a 1,633-line extractor written for that app, and probing ten trending public repos. On that app the generic skill now matches the hand-built map on model calls (9 sites, 7 roles), injected callables, table access and test-only functions.

- **Model-call gateways**: the `llm` profile finds the repo's own wrappers around an SDK (a client class's methods, or a function that takes the prompt) and records every call to them with its label, model setting, messages builder and output schema. The draft makes one model card per role, prefilled. HTTP calls whose URL names a model host (OpenRouter, Anthropic, …) count as model calls. Profiles can add `find_gateways(records, calls, symbols)`.
- **Injected callables**: a `Callable[...]` field bound at construction (`Deps(make_llm=make_llm)`) resolves calls through it (`deps.make_llm(...)`) to the bound functions; the code map lists them as `binds`. `self.x = param` takes the parameter's annotation.
- **Tests are read for callers only**: they add no edges or numbers, but "only tests call this" and "nothing calls this" (methods included, when no unresolved call could reach them) are generated findings now.
- **Findings retire themselves**: `check` can be `no_callers`, `symbol_exists`, `{kind = "text_in", pattern}`, `{kind = "calls", target}` or `{kind = "not_calls", target}`. When the code no longer shows a finding it moves to a "Fixed" list on the page instead of failing the build; `status = "fixed"` + `fixed_in` keeps hand-marked history.
- A read-then-write function counts as both reader and writer; a `select(M)` built in one function is that function's read.
- `import ui_common` from a script folder binds the name to the module it resolves to (`app.ui_common`), so `ui_common.x()` resolves.
- **Faster map**: looking for `*.sql` no longer walks `.venv`, `node_modules` or hidden folders (8.3 s → 1.7 s on a repo with a virtualenv inside).
- `Any`, `Self`, `Protocol` annotations are not treated as types.
- New `ui` stack profile (Streamlit, Gradio, NiceGUI): widgets and callbacks are entry points, so a script-style app gets journeys instead of none, plus a "UI triggers" table. Profiles can now add `on_module(ctx, tree)`, `triggers(records, code_map)` and `SINK = False`.
- ORM session writes count: `s.add(M(...))`, `s.delete(row)`, `s.merge`, `s.exec(select(M))` on a SQLAlchemy / SQLModel `Session` become table writes and reads, naming the exact model when the code says it (constructed, typed, or assigned from `select(M)` / `s.get(M, …)`). Journeys now end where the data lands.
- `with f() as s` binds the yielded type of a `@contextmanager` (`-> Iterator[Session]` / `Generator[...]`): +3.7 points resolved on a SQLModel app.
- An unresolved `x.get_secret_value()` is AWS Secrets Manager only in a module that imports boto3 (pydantic's `SecretStr` has the same method).
- Layer rules can forbid third-party packages (`forbid = ["streamlit"]`); the code map lists each module's top-level `packages`.
- `init` leaves `examples/`, `samples/`, `benchmarks/`, `notebooks/` … out of the scan when the repo has other code.
- `merge --check` validates a fragment without writing: parallel writers no longer overwrite each other's `narrative.toml`. A fragment entry `{ id = "...", drop = true }` removes a wrong drafted entry. It also reports layer-assignment problems and prints any layer rule the code breaks; re-merging no longer duplicates entries without an id (layer rules, decisions).

Then three example reports were built on huggingface/smolagents, lfnovo/open-notebook and karpathy/nanochat ([`examples/`](examples/)), which surfaced:

- **Libraries**: journey candidates now include a library's public API: names in `__all__`, a package's re-exports (`from .agents import *` exports a module's public classes and functions), and the entry methods of exported classes (`run`, `__call__`, `generate`, …) found through their bases. `[project.scripts]` console commands are entry points too.
- **Scripts**: top-level code that does real work becomes a symbol (`scripts.base_train:<module>`), so a training or seed script can start a journey and appears in the graph.
- **Virtual calls**: a call to a method that subclasses override gets dashed edges to every override, and journeys follow them (`self._step_stream()` → `CodeAgent._step_stream`). Attribute types are inherited (`self.model`, set in a base class's `__init__`); `Note.get_all()` resolves a classmethod defined on a base.
- **Polymorphic model gateways**: a base method becomes a gateway when an override is one (`Model.generate`), climbing through classes that do not override it. An SDK method handed to a retry wrapper (`retryer(client.chat.completions.create, …)`) counts as a model call, as do LangChain `model.invoke` / `chain.ainvoke` and esperanto's `AIFactory.create_*`.
- **More data shapes**: SurrealQL schemas (`DEFINE TABLE` in `.surql` / `.surrealql`); active-record models that name their table (`table_name: ClassVar[str] = "note"`, `__tablename__`, `_table` …) with `obj.save()`, `obj.delete()`, `Model.get()`, `Model.objects.filter()` as table access. `class X(Model)` is a table only when `Model` is the ORM's, not the repo's own class.
- Router prefixes are kept per module: every router file may call its variable `router` (all of open-notebook's routes had one file's prefix).
- A long entry method keeps at most three setup steps before the work that reaches a sink, so its journey gets to the point.
- A profile whose stack is imported but whose shape is never found shows no empty table; `text_in` checks match line by line (`^` works); the analysed code's `SyntaxWarning`s are not printed during `init`.

## 0.4.0 — 2026-10

- Module notes are now written, not copied: `[module_notes."pkg.mod"]` has `purpose` (why it exists), `does` (2–5 capabilities), `flow` (who calls it → what it goes through → where it writes) and an optional `note`. The module panel shows them as labelled rows, the index shows purpose and does, tooltips the purpose; search covers all four.
- `draft` no longer prefills notes from docstrings (a first sentence says too little to follow the flow); every module starts as a structured TODO.
- `codeflow.py module NAME …` prints what a writer needs first: callers, callees, tables, boundaries, functions.
- SKILL.md: module notes are written last, once the journeys are understood; large repos split them across parallel writers by layer. A missing `purpose`/`does`/`flow` or an unknown field fails the build.

## 0.3.0 — 2026-10

- `[module_notes]` in the narrative: one line per module, what it owns. Shown first in the module panel, map tooltips, the module index and search; the docstring stays as the fallback (and is shown under the note when both exist). Modules without a docstring no longer show an empty description.
- `draft` proposes a note for every module — the docstring's first sentence where there is one, a TODO where there is none. A note for a module that no longer exists fails the build.
- SKILL.md and the writer brief: one line per module, essentials only.
- Module index columns sized so names and layers no longer wrap.

## 0.2.0 — 2026-10

Call resolution, measured on three real repositories (all call sites → function calls):
httpie 66.5 % → 82.7 % / 83.3 %, a 53k-line Flask app 81.0 % → 91.5 % / 96.2 %, FastAPI template 94.5 % → 97.0 % / 97.2 %.

- Value types: literals, f-strings, `dict()`/`list()`/`sorted()`, string-method results; `a or b` and `x if c else y`; loop variables over library iterables.
- Return types of internal functions (annotation, or every `return` agreeing), class fields from annotations (dataclass / pydantic / `self.x: T`), `Optional[...]`, `X | None` and string annotations, `super().method()`.
- Call-site parameter inference: a parameter that receives the same known type at every call site gets it (a second pass).
- Inferred edges: unique method names, kept separate and drawn dotted.
- New `graph_coverage` metric next to the overall ratio; `code_map.json` schema 2 (an old map asks to be regenerated).

## 0.1.0 — 2026-10

First release.

- `codeflow.py` with `status`, `init`, `map`, `draft`, `candidates`, `query`, `find`, `todo`, `merge`, `build`, `verify`, `check`, `install-test`, `report`.
- Stack-agnostic extractor (`ast`): modules, functions, classes, call and reference edges, Flask / FastAPI / Starlette / Django routes with prefixes, SQL table access, ORM models (SQLAlchemy `__tablename__`, Django, SQLModel), write gateways, external boundaries, import cycles (module-level vs lazy), dead-code candidates, duplicate names. Type inference for locals, `with … as`, chained calls, annotated parameters, `self.x` attributes, imported module-level objects and inherited library methods.
- Stack profiles, routed by import: `llm` (model calls) and `jobs` (task queues and schedulers).
- Narrative draft from the code map: layers, ranked journey call chains, boundary cards, data lifecycles.
- Self-checking build: stale symbols, modules outside every layer, `no_callers` findings that are no longer true.
- One offline page, English and Korean, with fade-on-select for the structure map and the call graph.
