# narrative.toml — field reference

The narrative is the only hand-written input. Every `symbol`, `symbols`, `module`, `modules`, `table` and `tables` value is checked against `code_map.json` on every build; a name the code no longer has fails the build. Never write line numbers. A string that starts with `TODO` is shown as unwritten and counted.

Symbols: `pkg.mod:function` · `pkg.mod:Class.method` · `pkg.mod:outer.inner` (nested) · a module is `pkg.mod` (no colon) · a layer may also use `pkg.*`.

## [meta]

| key | meaning |
|---|---|
| `title` | page title (default: project name) |
| `lede` | two sentences: what the system does and how the main parts connect |
| `audience` | who the report is written for |
| `start_symbol` | optional: the function the call-graph explorer opens on (default: first journey's first step) |

## [[layers]]

```toml
[[layers]]
id = "web"
name = "Web routes"
owns = "HTTP handlers: parse the form, check permission, call the domain layer, render."
modules = ["shop.views", "shop.api.*"]
```

Order = left-to-right on the map. Once `[[layers]]` exist, every module must match one (a new module fails the build until it is placed) — prefer `pkg.*` patterns.

## [[layer_rules]]

Re-checked against the import graph (module-level and function-level imports) on every build; violations are listed on the page.

```toml
[[layer_rules]]
text = "The domain layer never imports the web layer."
from_layers = ["domain"]          # and/or from = ["pkg.mod", ...]
forbid = ["shop.views", "shop.api."]   # exact module, or a prefix ending in "."
```

## [[journeys]]

```toml
[[journeys]]
id = "place-order"                # unique, kebab-case
title = "Place an order"
actor = "customer · browser"
trigger = "POST /shop/orders"
summary = "Two sentences: what happens and where it ends."
  [[journeys.steps]]
  symbol = "shop.views:create_order"
  actor = "browser"               # who calls this step (first step; later steps default to the previous step's module)
  action = "Validates the form and hands the write to run_write"
  receives = "request.form: customer, items[], total"
  returns = "302 to /shop/orders/<id>, or 400 with the form re-rendered"
  stores = "nothing yet"
  tables = ["orders"]             # optional: tables this step reads or writes
  payload = '''
{"customer": "Jane Doe", "items": [{"sku": "A-100", "qty": 2}], "total": 4200}
'''
  note = "Why it is done this way — from a comment or docstring you read."
```

Usually 6–12 steps; a short journey (3–5) is right when that is the whole chain — do not pad it. Each step must really be on the chain (check with `codeflow.py query`). Payloads are small, realistic and invented.

## [[roles]] — boundary and background-work cards

```toml
[[roles]]
id = "payment-api"
name = "Payment provider"
kind = "external"                 # external | background | model | record
symbols = ["shop.payments:charge"]   # first = main one
purpose = "What and why"
input = "What the message is built from (template + variables, or fields)"
message = ["header: idempotency key", "body: amount, currency, card token"]
config = "Where it is configured: env var / config field NAMES, never values"
output = "What comes back and how success is judged"
validation = "Retries, timeouts, idempotency, what happens on failure"
logging = "Where a call or failure is recorded"
cost = "Cost or limits — 'not measured' if unknown; never invent"
result_use = "What code does with the result"
```

For `kind = "model"` (LLM profile), `input` is where the prompt comes from (template file + variables), `message` the message roles in order (system / user / assistant / tool) with what each carries, `output` the schema, `validation` the parse/repair rule. The profile adds the provider, model and settings found at the call site automatically.

## [[input_flows]]

```toml
[[input_flows]]
id = "upload"
source = "Uploaded CSV (user file)"
sink = "products table and the import report"
  [[input_flows.steps]]
  symbol = "shop.imports:read_csv"
  guard = "Size limit, header check, encoding fallback"
```

## [[entities]]

```toml
[[entities]]
id = "order"
name = "Order"
table = "orders"                  # optional; adds the SQL/ORM counts under the timeline
summary = "One row = one placed order."
  [[entities.events]]
  stage = "born"                  # born | transform | update | store | archive | restore | read | delete
  symbol = "shop.orders:insert_order"
  by = "checkout (customer)"
  text = "Inserted with status 'new'"
```

## [[decisions]]

```toml
[[decisions]]
decision = "Whether a coupon applies"
by = "code"                       # code | people | people (config file) | model
how = "Date window and minimum total checked in SQL"
symbol = "shop.coupons:applicable"
```

## [[findings]]

```toml
[[findings]]
id = "doc-retry-count"
severity = "low"                  # high | medium | low | info
category = "doc vs code"          # doc vs code | dead code | cycle | duplicated logic | risk
title = "README says 5 retries; the client retries 3 times"
detail = "What is true now · what trigger makes it go wrong · how far it reaches."
symbols = ["shop.payments:charge"]
evidence = "How you verified: the functions/files you read, the command you ran and what it printed (no line numbers — they go stale)"
check = "no_callers"              # optional: fail the build once symbols[0] gains a caller
```

Generated findings (import cycles, dead-code candidates, duplicate names, parse errors, coverage) are added by the builder and disappear when fixed — do not repeat them by hand unless you verified and want to add detail.
