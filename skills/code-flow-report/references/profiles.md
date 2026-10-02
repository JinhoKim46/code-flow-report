# Stack profiles

The core extractor is stack-agnostic. A **profile** adds detail for one stack and is switched on only when the repo imports that stack (`[profiles] enable / disable` in `codeflow.toml` overrides). A repo that does not use the stack never sees its section.

| Profile | Switched on by importing | Adds |
|---|---|---|
| `llm` | openai, anthropic, litellm, langchain*, google (genai), ollama, mistralai, cohere, groq, together, vertexai | "Model calls" table — provider, model and settings as written at the call site, message roles in order, tools, output schema; the same detail on the boundary card of the calling function; one drafted `kind = "model"` card per calling function |
| `jobs` | celery, rq, dramatiq, huey, apscheduler, schedule, arq, prefect, airflow, dagster, luigi | "Background jobs" table — task decorators, schedule registrations, enqueue calls (`.delay`, `.apply_async`, `.enqueue`) with who triggers them; tasks become journey entry points; drafted background cards |

## Writing a profile

Add `scripts/profiles/<name>.py` and list the module in `profiles/__init__.py`'s `ALL`. It defines:

```python
NAME = "events"
PACKAGES = ["kafka", "confluent_kafka", "aiokafka"]          # any one switches it on
TITLE = {"en": "Events", "ko": "이벤트"}
INTRO = {"en": "…", "ko": "…"}

def on_call(ctx, node, resolved, chain):
    """Called for every ast.Call. Return a dict to keep (must include "symbol" and "line"), or None.
    ctx.here() = current function, ctx.resolve_expr(expr), ctx.const_text(expr) for string constants."""

def section(records, code_map):
    return {"columns": {"en": [...], "ko": [...]},
            "rows": [[{"sym": "pkg.mod:fn", "line": 12}, "text", ...], ...]}

def card_extras(records):          # optional: {symbol: [[label, value], ...]} shown on boundary cards
def draft_roles(records):          # optional: [role dict, ...] proposed by `draft`
```

Records are stored in `code_map.json` under `profiles.<name>`, so they are part of the staleness check like everything else. Add a fixture under `tests/fixtures/` and a test that the profile switches on there and off elsewhere.
