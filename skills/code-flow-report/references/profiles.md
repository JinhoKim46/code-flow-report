# Stack profiles

The core extractor is stack-agnostic. A **profile** adds detail for one stack and is switched on only when the repo imports that stack (`[profiles] enable / disable` in `codeflow.toml` overrides). A repo that does not use the stack never sees its section.

| Profile | Switched on by importing | Adds |
|---|---|---|
| `llm` | openai, anthropic, litellm, langchain*, langgraph, esperanto, google (genai), ollama, mistralai, cohere, groq, together, vertexai, huggingface_hub | "Model calls" table — provider, model and settings as written at the call site, message roles in order, tools, output schema. Also: SDK methods handed to a retry wrapper, LangChain `.invoke` / `.ainvoke` on a model or chain, esperanto factories, HTTP calls to a model host. `find_gateways` names the repo's own wrappers (methods of a client class, functions that take the prompt, and base methods whose overrides are gateways); a second pass records every call to them (kind `gateway`) with its label, model setting, messages builder and schema, and the draft makes one prefilled card per role plus one gateway card |
| `ui` | streamlit, gradio, nicegui | "UI triggers" table — `st.Page` registrations, every button / chat box / upload / form submit that runs code, and `on_click=` / Gradio `.click(fn)` callbacks. A widget inside a function makes that function a journey entry; a top-level `if st.button(...):` block makes the functions it calls entries. Its records are triggers, not sinks |
| `cloudfn` | azure.functions, functions_framework, chalice | "Function triggers" table — Azure Functions v2 decorators (`route`, `queue_trigger`, `blob_trigger`, `timer_trigger`, Service Bus, Event Grid, Event Hub, Cosmos DB, Durable), `functions_framework.http` / `cloud_event`, Chalice (`route`, `on_sqs_message`, `on_s3_event`, `schedule`, …); each decorated function is a journey entry (`ENTRY_KIND = "infra"`) |
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
