"""LLM profile: model calls — provider, model, settings, message roles, tools, output schema.

Switched on when the repo imports a model SDK. Calls are recognised by their shape (the suffix
of the dotted call), because the client object's type is rarely visible statically; an HTTP call
whose URL names a model host counts too.

Most apps wrap the SDK in their own client (`LLMClient.chat_json(role, messages, Schema, model=…)`).
The SDK call alone says only "OpenAI"; the roles, prompts and schemas are written where the app
calls its wrapper. So `find_gateways` names those wrappers after a first pass, and a second pass
records every call to them (kind "gateway") with its label, model, messages builder and schema.
"""
from __future__ import annotations

import ast

NAME = "llm"
PACKAGES = ["openai", "anthropic", "litellm", "langchain", "langchain_openai", "langchain_anthropic",
            "langchain_core", "google", "ollama", "mistralai", "cohere", "groq", "together", "vertexai"]
TITLE = {"en": "Model calls", "ko": "모델 호출"}
INTRO = {"en": "Every call to a language-model API found in the code: provider, model and settings as written at the call site, the message roles in order, tools and the output schema. Values shown as code (not quoted) come from a variable; follow the function to see where it is set.",
         "ko": "코드에서 찾은 언어 모델 API 호출: 호출 지점에 적힌 제공자 · 모델 · 설정, 메시지 역할의 순서, 도구와 출력 스키마. 따옴표 없이 보이는 값은 변수에서 온다 — 함수를 따라가면 어디서 정해지는지 보인다."}

SUFFIXES = [
    ("messages.create", "Anthropic"), ("messages.stream", "Anthropic"), ("messages.parse", "Anthropic"),
    ("chat.completions.create", "OpenAI-compatible"), ("chat.completions.parse", "OpenAI-compatible"),
    ("responses.create", "OpenAI"), ("responses.parse", "OpenAI"), ("completions.create", "OpenAI-compatible"),
    ("embeddings.create", "Embeddings"), ("models.generate_content", "Gemini"), ("generate_content", "Gemini"),
    ("litellm.completion", "LiteLLM"), ("litellm.acompletion", "LiteLLM"), ("ollama.chat", "Ollama"),
]
CONSTRUCTORS = {"ChatOpenAI": "LangChain/OpenAI", "ChatAnthropic": "LangChain/Anthropic",
                "ChatGoogleGenerativeAI": "LangChain/Gemini", "AzureChatOpenAI": "LangChain/Azure"}
SETTINGS = ["model", "temperature", "max_tokens", "max_output_tokens", "max_completion_tokens", "top_p", "top_k",
            "reasoning_effort", "reasoning", "thinking", "effort", "seed", "stop", "stream", "timeout"]
SCHEMA_KEYS = ["response_format", "text_format", "output_format", "output_config", "response_model",
               "response_schema", "output_type"]


def _short(node, limit=80):
    text = " ".join(ast.unparse(node).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _kw(node, name):
    return next((k.value for k in node.keywords if k.arg == name), None)


MODEL_HOSTS = {"openrouter": "OpenRouter", "api.openai": "OpenAI", "openai.azure": "Azure OpenAI", "anthropic": "Anthropic",
               "generativelanguage": "Gemini", "aiplatform.googleapis": "Vertex AI", "mistral": "Mistral", "groq": "Groq",
               "together": "Together", "deepseek": "DeepSeek", "cohere": "Cohere", "11434": "Ollama", "ollama": "Ollama",
               "fireworks": "Fireworks", "perplexity": "Perplexity", "x.ai": "xAI"}
HTTP_LIBS = ("httpx", "requests", "aiohttp", "urllib3")
HTTP_METHODS = {"post", "request", "stream", "send"}
LABEL_KW = ("role", "name", "purpose", "task", "label", "agent", "kind")
PROMPT_PARAMS = {"messages", "prompt", "msgs", "conversation", "history", "contents", "input", "chat_history", "system"}


def _http_model_call(ctx, node, resolved):
    """`httpx.post(settings.openrouter_url, json=…)`: an HTTP call whose URL text names a model host."""
    if not (resolved and resolved[0] == "external" and resolved[1].split(".")[0] in HTTP_LIBS
            and resolved[1].rsplit(".", 1)[-1] in HTTP_METHODS and (node.args or _kw(node, "url") is not None)):
        return None
    url = _kw(node, "url") if _kw(node, "url") is not None else node.args[-1 if resolved[1].endswith("request") and len(node.args) > 1 else 0]
    text = (ctx.const_text(url) or ast.unparse(url)).lower()
    return next((prov for key, prov in MODEL_HOSTS.items() if key in text), None)


def _gateway_call(ctx, node, target, provider):
    """A call to the repo's own model wrapper: what the call site says about the role, prompt and schema."""
    rec = {"kind": "gateway", "symbol": ctx.here(), "line": node.lineno, "provider": provider,
           "call": target.split(":", 1)[1], "gateway": target, "settings": {}, "message_roles": []}
    label = next((ctx.const_text(a) for a in node.args[:1] if ctx.const_text(a)), None)
    label = label or next((ctx.const_text(_kw(node, k)) for k in LABEL_KW if _kw(node, k) is not None and ctx.const_text(_kw(node, k))), None)
    model = _kw(node, "model")
    if model is not None:
        rec["settings"]["model"] = repr(ctx.const_text(model)) if ctx.const_text(model) else _short(model)
        field = next((part for part in _short(model, 200).replace("(", " ").split() if ".models." in part or part.startswith("models.")), "")
        label = label or (field.rsplit(".", 1)[-1] if field else None)
    rec["label"] = label or rec["symbol"].split(":", 1)[1].split(".")[-1]
    for k in node.keywords:
        if k.arg in SETTINGS and k.arg != "model":
            lit = ctx.const_text(k.value)
            rec["settings"][k.arg] = repr(lit) if lit is not None else (repr(k.value.value) if isinstance(k.value, ast.Constant) else _short(k.value))
        elif k.arg is None:
            rec["settings"]["**"] = _short(k.value, 30)
    for a in list(node.args) + [k.value for k in node.keywords if k.arg in SCHEMA_KEYS + ["schema", "messages", "prompt"]]:
        r = ctx.resolve_expr(a.func) if isinstance(a, ast.Call) else ctx.resolve_expr(a)
        if not (r and r[0] == "internal"):
            continue
        kind = ctx.res.symbols.get(r[1], {}).get("kind")
        if kind == "class" and not isinstance(a, ast.Call) and "output_schema" not in rec:
            rec["output_schema"] = r[1].split(":", 1)[1]
        elif kind in ("function", "method", "nested") and isinstance(a, ast.Call) and "messages" not in rec:
            rec["messages"] = r[1]
            rec["message_roles"] = [f"<{r[1].split(':', 1)[1]}()>"]
    return rec


def find_gateways(records, calls, symbols):
    """The repo's own wrappers around a model call: functions holding an SDK / model-HTTP call, plus the functions
    of the same class (or module, for plain functions) that call one of them — `chat_json` → `self.chat` → SDK."""
    # a wrapper, not a one-off: a method of a client class, or a function that takes the prompt as a parameter.
    # `def answer(question): client.messages.create(system=…, …)` builds its own prompt — its callers are not roles.
    gw = {r["symbol"]: r["provider"] for r in records if r.get("kind") != "gateway" and r["symbol"] in symbols
          and (symbols[r["symbol"]]["kind"] == "method" or set(symbols[r["symbol"]].get("params", [])) & PROMPT_PARAMS)}

    def owner(k):
        mod, qual = k.split(":", 1)
        return f"{mod}:{qual.rsplit('.', 1)[0]}" if symbols.get(k, {}).get("kind") == "method" else mod

    changed = True
    while changed:
        changed = False
        for a, b, _ in calls:
            if b in gw and a not in gw and a in symbols and owner(a) == owner(b) and symbols[a]["kind"] in ("method", "function"):
                gw[a] = gw[b]
                changed = True
    return gw


def on_call(ctx, node, resolved, chain):
    gateways = ctx.res.gateways.get(NAME, {})
    if resolved and resolved[0] == "internal" and resolved[1] in gateways and ctx.here() not in gateways:
        return _gateway_call(ctx, node, resolved[1], gateways[resolved[1]])
    host = _http_model_call(ctx, node, resolved)
    if host:
        return {"symbol": ctx.here(), "line": node.lineno, "provider": host, "call": f"HTTP · {resolved[1]}",
                "settings": {}, "message_roles": []}
    full = resolved[1] if resolved and resolved[0] in ("external", "convention") else chain
    provider = None
    if full:
        for suffix, prov in SUFFIXES:
            if full == suffix or full.endswith("." + suffix):
                provider = prov
                break
    if provider is None:
        last = (resolved[1] if resolved else chain or "").split(".")[-1]
        if last in CONSTRUCTORS:
            provider, full = CONSTRUCTORS[last], last
    if provider is None:
        return None
    rec = {"symbol": ctx.here(), "line": node.lineno, "provider": provider, "call": full, "settings": {}}
    for key in SETTINGS:
        v = _kw(node, key)
        if v is not None:
            lit = ctx.const_text(v)
            rec["settings"][key] = repr(lit) if lit is not None else (repr(v.value) if isinstance(v, ast.Constant) else _short(v))
    for key in SCHEMA_KEYS:
        v = _kw(node, key)
        if v is not None:
            rec["output_schema"] = f"{key}={_short(v)}"
    if _kw(node, "tools") is not None:
        rec["tools"] = _short(_kw(node, "tools"))
    roles = []
    if _kw(node, "system") is not None:
        roles.append("system (system=)")
    msgs = _kw(node, "messages") or _kw(node, "input") or _kw(node, "contents")
    if isinstance(msgs, (ast.List, ast.Tuple)):
        for el in msgs.elts:
            if isinstance(el, ast.Dict):
                for k, v in zip(el.keys, el.values):
                    if isinstance(k, ast.Constant) and k.value == "role":
                        roles.append(v.value if isinstance(v, ast.Constant) else _short(v, 30))
            elif isinstance(el, ast.Starred):
                roles.append(f"*{_short(el.value, 30)}")
            else:
                roles.append(_short(el, 30))
    elif msgs is not None:
        roles.append(f"<{_short(msgs, 40)}>")
    rec["message_roles"] = roles
    return rec


def _settings(r):
    return ", ".join(f"{k}={v}" for k, v in r["settings"].items()) or "–"


def section(records, code_map):
    rows = [[{"sym": r["symbol"], "line": r["line"]},
             (f'{r["label"]} — via {r["call"]} ({r["provider"]})' if r.get("kind") == "gateway" else f'{r["provider"]} · {r["call"]}'),
             _settings(r),
             " → ".join(r["message_roles"]) or "–",
             " · ".join(x for x in [r.get("output_schema"), r.get("tools") and "tools=" + r["tools"]] if x) or "–"]
            for r in records]
    return {"columns": {"en": ["Function", "Provider · call", "Model & settings", "Message roles", "Output schema · tools"],
                        "ko": ["함수", "제공자 · 호출", "모델 · 설정", "메시지 역할", "출력 스키마 · 도구"]},
            "rows": rows}


def card_extras(records):
    out = {}
    for r in records:
        rows = out.setdefault(r["symbol"], [])
        rows.append(["model call", f'{r["provider"]} · {r["call"]} ({_settings(r)})'])
        if r["message_roles"]:
            rows.append(["roles", " → ".join(r["message_roles"])])
        if r.get("output_schema"):
            rows.append(["schema", r["output_schema"]])
    return out


def draft_roles(records, code_map=None):
    roles = []
    by_label = {}
    for r in records:
        if r.get("kind") == "gateway":
            by_label.setdefault(r["label"], []).append(r)
    for label, recs in sorted(by_label.items()):
        first = recs[0]
        roles.append({"id": "model-" + label.replace("_", "-").replace(".", "-").lower(), "name": f"Model role: {label}",
                      "kind": "model", "symbols": sorted({r["symbol"] for r in recs})[:6],
                      "purpose": "TODO: what this model role decides or writes, in one sentence",
                      "input": (f"TODO: the prompt — built by {first['messages']}" if first.get("messages")
                                else "TODO: where the prompt comes from (template file + the variables filled in)"),
                      "message": ["TODO: message roles in order, with what each carries"],
                      "config": f"model: {first['settings']['model']} — TODO: where that is configured" if first["settings"].get("model")
                      else "TODO: where model and settings are configured",
                      "output": (f"{first['output_schema']} — TODO: what it holds" if first.get("output_schema") else "TODO: output type / schema"),
                      "validation": "TODO: validation, retry or repair",
                      "logging": "TODO: how the call is logged and costed", "result_use": "TODO: what code does with the result"})
    wrapped = {r["gateway"] for r in records if r.get("kind") == "gateway"}
    by_fn = {}
    for r in records:
        if r.get("kind") != "gateway":
            by_fn.setdefault(r["symbol"], r)
    if wrapped:  # the SDK sites sit inside the gateways: one card for the gateway layer, not one per inner method
        roles.append({"id": "model-gateway", "name": "Model gateway", "kind": "model",
                      "symbols": sorted(set(by_fn) | wrapped)[:6],
                      "purpose": "TODO: what every model call goes through, and why",
                      "config": "TODO: where provider, keys and defaults are configured",
                      "validation": "TODO: retries, timeouts, output validation and repair",
                      "logging": "TODO: how each call is logged and costed"})
        return roles
    for sym, r in sorted(by_fn.items()):
        fn = sym.split(":", 1)[1]
        roles.append({"id": "model-" + fn.replace(".", "-").replace("_", "-").lower(), "name": f"Model call: {fn}",
                      "kind": "model", "symbols": [sym],
                      "purpose": "TODO: what this model role decides or writes, in one sentence",
                      "input": "TODO: where the prompt comes from (template file + the variables filled in)",
                      "message": ["TODO: message roles in order, with what each carries"],
                      "config": "TODO: where model and settings are configured",
                      "output": "TODO: output type / schema", "validation": "TODO: validation, retry or repair",
                      "logging": "TODO: how the call is logged and costed", "result_use": "TODO: what code does with the result"})
    return roles
