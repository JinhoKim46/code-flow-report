"""LLM profile: model calls — provider, model, settings, message roles, tools, output schema.

Switched on when the repo imports a model SDK. Calls are recognised by their shape (the suffix
of the dotted call), because the client object's type is rarely visible statically.
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


def on_call(ctx, node, resolved, chain):
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
    rows = [[{"sym": r["symbol"], "line": r["line"]}, f'{r["provider"]} · {r["call"]}', _settings(r),
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
    by_fn = {}
    for r in records:
        by_fn.setdefault(r["symbol"], r)
    roles = []
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
