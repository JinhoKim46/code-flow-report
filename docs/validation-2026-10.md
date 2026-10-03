# Validation — October 2026 (v0.1.0)

How the skill was checked before release. Every number below was measured on the stated run; nothing is estimated.

## 1. Test suite

`python3 -m unittest discover -s tests -t tests` → **49 tests, OK** (≈5 s, no network, no packages). Seven fixture repos under `tests/fixtures/`, all invented:

| Fixture | Pins down |
|---|---|
| `flask_app` | blueprint prefix → route URLs, guards, templates, SQL table access via a module constant, a write gateway, boundaries, dead-code candidates, convention-typed calls, `tests/` excluded |
| `fastapi_llm` | `include_router(prefix) + APIRouter(prefix)` order, the `llm` profile switched on by import (model through a constant, settings, roles `system → user`, output schema), `profiles.disable` |
| `django_site` | `path()` to function and class-based views, `models.Model` and `Meta.db_table` → tables, ORM use |
| `celery_jobs` | the `jobs` profile: task decorators and `.delay()` linked to the task |
| `src_layout_lib` | `src/` stripping, relative import, re-export through `__init__`, `self.method()`, a real import cycle told apart from a lazy one |
| `oo_lib` | attribute types from `__init__`, inherited methods of a library subclass, an imported module-level object, an annotated library parameter, SQLModel `table=True` |
| `broken` | a syntax error is recorded and skipped, never fatal |

Plus end-to-end CLI runs on copies: init → draft → build → check, staleness after a code change, a renamed function naming the stale narrative entry, a new module outside every layer, a `no_callers` finding breaking once a caller appears, Korean output with quotes round-tripping through TOML, both profile sections, and the Markdown report.

## 2. Real repositories (zero configuration)

`init → map → draft --depth standard → build`, default settings, on a copy of each repository.

| Repository | Kind | Files · lines | `map` | Resolved calls | Routes · tables | Draft |
|---|---|---|---|---|---|---|
| a private Flask app + batch loader + AWS CDK (the report this skill was generalised from) | web app | 126 · 53,087 | 0.8 s | **81.0 %** (hand-tuned original: 82.8 %) | 200 · 46 | 7 layers, 6 journeys, 15 boundary cards, 10 entities |
| fastapi/full-stack-fastapi-template | API + SQLModel | 27 · 1,686 | 0.1 s | **94.5 %** | 23 · 2 | 3 layers, 5 journeys, 2 entities |
| httpie/cli | class-heavy CLI library | 86 · 10,630 | 0.2 s | **66.5 %** | 0 · 0 | 3 layers, 2 journeys |

What the runs changed in the code (each now has a fixture test):

- Router prefixes were joined in module order (`/v1/api`); now mount prefix + declared prefix.
- A package's `__init__` module could land in two auto layers and fail the build.
- The analysed repo's own `SyntaxWarning`s were printed; now silenced.
- Methods inherited from a library base class, attributes set in `__init__`, objects imported from another module and annotated library parameters were unresolved (httpie 62.1 % → 66.5 %).
- SQLModel `table=True` models were not tables (FastAPI template: 0 → 2 tables).
- Draft journeys descended into plumbing helpers (`connect`, `log`) and ranked admin screens and one-off scripts above core flows; now hubs are not descended into, write paths go first, and journeys are ranked by how central the tables they write are (the private app's candidates changed from "change password, backfill script" to "submit feedback, call-centre intake, edit/delete contract, file a work log").

Known limit seen: one file in the FastAPI template uses Python 3.14 syntax (`except A, B:`) and is skipped on 3.12, listed as a finding.

## 2b. Call resolution in 0.2.0

The unresolved calls were classified first (receiver is a literal / name matches a function of the repo / builtin-type method name / unknown object / bare name). On the 53k-line app, three quarters of them were value methods (`row.get`, `items.append`); on httpie, half were calls whose name matches a method of the repo on objects of unknown type — real missed edges. The fixes in the changelog target both; each rule has a case in `tests/fixtures/types_lib`.

| Repository | 0.1.0 all call sites | 0.2.0 all call sites | 0.2.0 graph coverage | Internal edges 0.1.0 → 0.2.0 | Inferred edges |
|---|---|---|---|---|---|
| private Flask app (53k lines) | 81.0 % | 91.5 % | 96.2 % | 3,689 → 3,694 | 8 |
| fastapi/full-stack-fastapi-template | 94.5 % | 97.0 % | 97.2 % | 73 → 73 | 0 |
| httpie/cli | 66.5 % | 82.7 % | 83.3 % | 541 → 621 | 40 |

What still cannot be seen statically: parameters whose callers pass different or unknown types, objects returned by libraries without annotations, and callbacks invoked through a variable (`work(cur)`).

## 3. Accuracy spot checks

- `verify --edges 5` on the private app: 5 / 5 edges — the callee's name on the call line and on its `def` line.
- During the original hand-built report: 5 / 5 random edges and one 12-step journey walked against the source matched.

## 4. Page

Checked in a headless browser on the private app's report (953 KB): no page errors; no horizontal overflow at 390 px (full-page screenshot exactly 390 px wide); the Korean UI renders; the fade works — selecting `webapp.app` on the structure map keeps it, the modules it calls (teal) and its caller (amber), fades everything else to 22 %, and draws highlighted edges under the boxes; hovering a box in the call graph keeps only it, its neighbours and the edges between them.

## 5. SKILL.md acceptance test

A fresh agent with no prior context was given only the skill folder and the invented `examples/demo-shop` repository, with the step-1 answers fixed (English, quick, "learning the code"), and told to follow SKILL.md exactly.

| | |
|---|---|
| Wall-clock time | **≈ 4.5 min** (22:36:54 → 22:41:17), target ≤ 10 min for quick |
| Result | 3 journeys, 6 boundary cards, 4 entities, 9 findings (8 written and verified, 1 generated), **0 TODO left** |
| `build` / `verify` / `check` | exit 0 · 5 / 5 edges ok · up to date |
| Page | no errors and no console output at 390 px and 1440 px |

Gaps it reported, and what changed (each has a test in `tests/test_draft.py`):

| Reported | Fix |
|---|---|
| The draft dropped the handler's validation call (no sink below it) | A journey keeps every direct callee of the entry point; only deeper steps must lead to a sink |
| Two cards for one function (generic SDK card + model card) | A generic service card is dropped when profile cards cover all its functions |
| A bare `@shared_task` (no `.delay()`) got no card | Profile `draft_roles` receives the code map; the jobs profile drafts cards from decorators |
| SKILL.md requires `[[input_flows]]` but the draft made none | The draft proposes one per write route |
| `draft` and `todo` counted TODOs differently | One counter, including strings inside lists |
| "6–12 steps" does not fit short chains; swap guidance too narrow | Short journeys allowed when that is the whole chain; swap a journey that is only another's tail; add missing validation steps |
| No `init` option for the reader | `init --audience` |
| `evidence` said "lines read" while the rest says no line numbers | Evidence names functions/files and commands, no line numbers |
| `allowed-tools` lacked Write/Edit | Added |
| Running the vendored tools left `__pycache__/` in the target repo | No bytecode written; `init` adds `.gitignore` files |

## v0.5.0 re-validation

**Test suite:** `python3 -m unittest discover -s tests -t tests` → **66 tests, OK**. New fixtures: `streamlit_app` (widgets as entry points, SQLModel session writes through a `@contextmanager`, pydantic `SecretStr` not mistaken for AWS), `llm_app` (calls to the repo's own model client as roles, injected `Callable` fields, `self.x = param` typing, script-folder imports), `lib_pkg` (library API from `__all__` and re-exports, console scripts, top-level script code, active-record models on a SurrealQL schema, LangChain `.invoke`, an SDK method passed to a retry wrapper, polymorphic gateways, override edges).

**Against a hand-built report.** A Streamlit + SQLModel LLM app had a report generated by a 1,633-line extractor written only for it. The generic skill now agrees with it on:

| Measure | Hand-built | Skill |
|---|---|---|
| Functions and methods | 253 | the same 253 |
| Shared call and construct edges | — | 580 (7 only in the hand-built map: 6 edges to a callable field, which the skill draws to the bound function, and 1 missed) |
| Model call sites and roles | 9 sites, 7 roles | the same 9 sites, 7 roles |
| Injected callables | 3 | the same 3 |
| Table writers and deleters | every one | every one; readers 33 against 32 |
| Functions only tests call | 1 | the same 1 |

**Map coverage**, zero configuration:

| Repository | Map time | Graph coverage | All call sites |
|---|---|---|---|
| fastapi/full-stack-fastapi-template | 0.1 s | 98.4 % | 98.1 % |
| the Streamlit app | 1.7 s | 95.0 % | 94.2 % |
| huggingface/smolagents | 0.7 s | 88.5 % | 88.7 % |
| lfnovo/open-notebook | 1.0 s | 87.9 % | 89.1 % |
| httpie/cli | 0.5 s | 84.7 % | 83.6 % |
| karpathy/nanochat | 0.4 s | 80.2 % | 83.7 % |

**Example reports.** Each of the three examples in `examples/` was built at `standard` depth with parallel writers, then checked:

- `build` and `check`: clean;
- `verify --edges 20`: 20 of 20 edges match their source lines;
- no finding marked fixed when it is not;
- the page renders with no errors and no horizontal scroll at 390 and 1440 px.

Every medium finding was re-read in the code by the dispatching session before publishing.

## v0.6.0: infrastructure as code

**Test suite:** **73 tests, OK**. New fixtures:

- `cdk_ts_app` (TypeScript CDK): an import alias (`Function as LambdaFunction`); `path.join(__dirname, …)` assets; a construct property (`storage.ordersTable`); a helper parameter; an API route with its path; an SQS event source; grants; environment variables; and a construct in a comment that must not count.
- `cdk_py_app` (Python CDK): an S3 notification, `grant_read`, and an environment dict.
- `llm_app` now also holds a package `adapters/openai.py`, which must not capture `import openai`.

**On aws-samples/aws-genai-llm-chatbot** (TypeScript CDK, 50 files; Python Lambdas, 155 modules):

- **Resources:** 93, linked by 181 wiring edges.
- **Lambda → Python links:** 17 of 20 Lambdas link to the exact Python function they run, which is every Python Lambda; the other 3 run Node.js.
- **Unresolved references:** 2 of 181 edges, a CodeBuild project and a CloudFront access identity; both classes have since been added.
- **Triggers:**
  - S3 UploadBucket → SQS IngestionQueue → UploadHandler;
  - SNS MessagesTopic → SQS → the request handlers;
  - EventBridge schedules → the RSS Lambdas;
  - Step Functions tasks → the workspace Lambdas.
- **Checks:** the report built at `standard` depth passes the same checks as the other examples (`build` and `check` clean, 20 of 20 edges, no false "fixed", renders at 390 and 1440 px).

## v0.7.0: Terraform

**Test suite:** **89 tests, OK** (79 at the Terraform milestone, 6 for containers, 4 more from the examples below). New fixtures:

- `tf_aws_app`: an `archive_file` Lambda, a container-image Lambda (`image_uri` → `docker_image` build → `jobs/Dockerfile` `CMD`), an SQS event source, an EventBridge schedule, an IAM policy with two statements, and environment variables.
- `tf_gcp_app`: a Cloud Function with `entry_point` and its source archive, a Pub/Sub `event_trigger`, a Cloud Scheduler job, and a bucket IAM binding for its service account.
- `tf_azure_app`: a Function App with `app_settings` and a role assignment on its identity, plus `function_app.py` with `route`, `queue_trigger` and `timer_trigger` decorators (the `cloudfn` profile).

**On aws-samples/sample-scribe-ai** (scanner measurements only; not shipped as an example — Terraform, 19 `.tf` files; Python, 28 modules):

- **Resources:** 31, linked by 21 wiring edges, with the Aurora, VPC and ECS community modules counted as resources.
- **Function → Python links:** 2 of 3 functions. The events Lambda is a container image and links through its Dockerfile; `log_to_s3` links through `archive_file`. The third, the voice processor, runs TypeScript.
- **Grants:** each IAM policy statement attaches its own actions to its own resource, so Bedrock actions are no longer shown on the Cognito pool, an error the first draft made.
- **Checks:**
  - `build` and `check` are clean, and 5 of 5 sampled edges are `ok`.
  - The page renders at 390 and 1440 px with no horizontal scroll and no errors.

**No regressions** on the earlier repositories: graph coverage is unchanged (95.0, 88.5, 87.9, 80.2 and 88.0 %), and aws-genai-llm-chatbot still reads 93 resources with 17 of 20 Lambdas linked.

### Containers (Docker Compose, Kubernetes, Helm)

**Fixtures:**

- `compose_app`:
  - an API built from `backend/` whose override file replaces the command with uvicorn;
  - a celery worker and a `python -m` script;
  - PostgreSQL and Redis by image, with `${VAR:-default}` in a URL;
  - an image of the repository itself whose root Dockerfile's last stage inherits a `supervisord` `CMD` (two Python programs and one Node program);
  - a copy of the stack under `examples/` that must be skipped.
- `k8s_app`:
  - a Deployment whose image `ghcr.io/example/api` is matched to `api/Dockerfile`, which runs an entrypoint script that ends in gunicorn `"api.wsgi:create_app()"`;
  - a Service, an Ingress, a CronJob with `python -m`;
  - a ConfigMap, a Secret and a claim referenced by `env`, `envFrom` and volumes;
  - a PostgreSQL StatefulSet;
  - a Helm chart whose name and image come from `values.yaml`.

**On GoogleCloudPlatform/bank-of-anthos** (scanner measurements only; not shipped as an example — 12 Python files; Kubernetes manifests, kustomize bases and overlays, Terraform for GKE):

- **Resources:** 42, linked by 51 wiring edges. Every Service routes to its Deployment by selector, and the Ingress routes to the frontend Service.
- **Python links:** 4 of 4 Python workloads link to the function they run (three `create_app` factories and the Locust file). The two PostgreSQL StatefulSets are recognised from their Dockerfile's base image; the Java services are listed and not counted.
- **Two problems found on this repository and fixed:**
  - `extras/` held alternative copies of every object and sorted first. It is now read only when alone, and kustomize bases win over overlays.
  - `POSTGRES_DB=accounts-db` was read as a host. A bare name is now an edge only in a variable named like a host.
- **Checks:** `build` and `check` are clean, 20 of 20 sampled edges are `ok`, and the page renders at 390 and 1440 px with no horizontal scroll and no errors.

**On earlier repositories:**

- **lfnovo/open-notebook:** its published image is followed through the root Dockerfile, the inherited `CMD` and `supervisord.conf` to `api.main`. Its `examples/` and `scripts/` compose files are skipped.
- **aws-samples/sample-scribe-ai:** shows its two local-dev Compose stacks beside the Terraform. A repeated `app` service becomes `events/app` and `web/app`, `image: scribe-web` is matched to `web/Dockerfile`, and 4 of 5 functions are linked (the fifth runs TypeScript).
- **Unchanged:** graph coverage is the same on every repository, and aws-genai-llm-chatbot still reads 93 resources with 17 of 20 linked.

### The shipped examples for 0.7.0

**aws-ia/terraform-aws-control_tower_account_factory** (51 Python files; 115 `.tf` files in 17 local modules):

- **Before the fixes**, the first map linked 0 of 18 Lambdas and found 11 wiring edges.
  - Every function takes `filename = var.…_archive_path`. The value comes from the root `module "…" { … = module.packaging.… }`, then from the packaging module's `output`, then from a `resource "archive_file"`.
  - Policies and the three state machine definitions are `templatefile()` calls.
- **After the fixes:** 18 of 18 Lambdas linked and 54 wiring edges:
  - 11 Step Functions tasks, including one template written with `${ name }`;
  - 32 per-statement grants;
  - EventBridge targets and DynamoDB stream triggers.
- **Two bugs that only a real repository showed:**
  - `image_build` shadowed the folder pointer, caught by the sample-scribe-ai regression and now covered by `tf_aws_app`.
  - A `set()` made the edge order follow the hash seed, so `check` flagged a fresh map as stale; now covered by a test that maps under three seeds.

**vllm-project/production-stack** (69 Python files; a Helm chart, an operator's manifests, tutorials):

- The router Deployment links through `docker/Dockerfile`'s `ENTRYPOINT` and the repository's `vllm-router` console script to `vllm_router.app:main`. It was chosen over `Dockerfile.kvaware` because both start the same command.
- The cache server's own `command` runs `lmcache_server`, an installed package, so it is shown and not linked. Before the fix, the image name's shared word `vllm` sent it to the router's Dockerfile.
- Ingress → `release-router-service` → `release-deployment-router` is found by name, because the chart builds selectors with `include`.
- Tutorials are skipped.

**Checks on all six shipped examples** (smolagents, open-notebook, nanochat, aws-genai-llm-chatbot, aft, production-stack):

- Each was rebuilt with the final scripts.
- `check` is "up to date" under two hash seeds.
- 20 of 20 sampled edges are `ok`.
- Each renders at 390 and 1440 px with no horizontal scroll and no errors.
- No example carries a high-severity security finding about its repository.
