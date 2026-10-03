"""Script-style UI profile: apps whose "routes" are widgets — Streamlit, Gradio, NiceGUI.

Switched on when the repo imports one of them. Such an app has no URL table: a page is a script that
reruns top to bottom, and work starts where a widget fires — `if st.button("Save"):`, `if text :=
st.chat_input(...)`, an `on_click=` / `on_submit=` callback, or Gradio's `btn.click(fn, ...)`. This
profile records those triggers so the draft can start journeys there, and lists pages registered with
`st.Page(...)`. Its records are triggers, not sinks: a widget is where a journey begins, not where it ends.
"""
from __future__ import annotations

import ast

NAME = "ui"
PACKAGES = ["streamlit", "gradio", "nicegui"]
SINK = False
TITLE = {"en": "UI triggers", "ko": "화면 트리거"}
INTRO = {"en": "Where work starts in a script-style UI: each button, chat box, upload or form submit that runs code, and the callbacks wired to widgets. A page reruns top to bottom on every interaction, so these — not URLs — are the app's entry points.",
         "ko": "스크립트형 화면에서 일이 시작되는 곳: 코드를 실행하는 버튼, 채팅 입력, 업로드, 폼 제출, 그리고 위젯에 연결된 콜백. 페이지는 상호작용마다 위에서부터 다시 실행되므로 URL 대신 이것들이 앱의 진입점이다."}

WIDGETS = {"button", "form_submit_button", "chat_input", "file_uploader", "download_button"}
CALLBACK_KW = {"on_click", "on_change", "on_submit", "on_upload", "fn"}
EVENT_METHODS = {"click", "submit", "change", "upload", "select"}  # Gradio: component.click(fn, inputs, outputs)


def _name(node):
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)


def _is_widget(ctx, node):
    if not (isinstance(node, ast.Call) and _name(node.func) in WIDGETS):
        return False
    r = ctx.resolve_expr(node.func)
    return bool(r and r[0] in ("external", "convention"))


def _label(ctx, node):
    if node.args:
        t = ctx.const_text(node.args[0])
        return t if t is not None else ast.unparse(node.args[0])[:40]
    kw = next((k.value for k in node.keywords if k.arg in ("label", "placeholder")), None)
    return (ctx.const_text(kw) or ast.unparse(kw)[:40]) if kw is not None else ""


def on_call(ctx, node, resolved, chain):
    name = _name(node.func)
    if name == "Page" and resolved and resolved[0] == "external" and node.args:
        page = ctx.const_text(node.args[0])
        if page:
            return {"kind": "page", "symbol": ctx.here(), "line": node.lineno, "page": page}
    cb = next((k.value for k in node.keywords if k.arg in CALLBACK_KW), None)
    if cb is None and name in EVENT_METHODS and node.args and isinstance(node.func, ast.Attribute):
        cb = node.args[0]
    if cb is not None:
        r = ctx.resolve_expr(cb)
        if r and r[0] == "internal":
            return {"kind": "callback", "symbol": ctx.here(), "line": node.lineno, "widget": name, "target": r[1],
                    "label": _label(ctx, node) if name in WIDGETS else ""}
    if _is_widget(ctx, node):
        return {"kind": "widget", "symbol": ctx.here(), "line": node.lineno, "widget": name, "label": _label(ctx, node)}
    return None


def on_module(ctx, tree):
    """Top-level `if <widget>:` blocks — the page's own handlers, outside any function. The draft starts a
    journey at the functions called inside the block (line range `line`..`end`)."""
    out = []

    def visit(stmts):
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # inside a function the function itself is the entry (see on_call)
            if isinstance(s, ast.If):
                w = next((n for n in ast.walk(s.test) if _is_widget(ctx, n)), None)
                if w is not None:
                    out.append({"kind": "block", "symbol": f"{ctx.mod}:<module>", "line": s.lineno, "end": s.end_lineno,
                                "widget": _name(w.func), "label": _label(ctx, w)})
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(s, field, None) or [])
            for h in getattr(s, "handlers", None) or []:
                visit(h.body)
    visit(tree.body)
    return out


def _block_calls(r, code_map):
    return sorted({b for a, b, line in code_map["calls"]
                   if a == r["symbol"] and r["line"] <= line <= r["end"] and b in code_map["symbols"]})


def triggers(records, code_map):
    """(symbol, trigger text) entry points for the draft: a widget inside a function starts at that function; a
    top-level widget block starts at each internal function it calls; a callback starts at its target."""
    out = []
    for r in records:
        mod = r["symbol"].split(":")[0]
        what = f'{r.get("widget", "")} "{r.get("label", "")}"'.strip() if r.get("label") else r.get("widget", "")
        where = code_map["modules"].get(mod, {}).get("file", mod)
        if r["kind"] == "widget" and not r["symbol"].endswith(":<module>"):
            out.append((r["symbol"], f"{what} · {where}"))
        elif r["kind"] == "callback":
            out.append((r["target"], f"{what} callback · {where}"))
        elif r["kind"] == "block":
            out += [(b, f"{what} · {where}") for b in _block_calls(r, code_map)]
    merged = {}
    for sym, trig in out:
        merged.setdefault(sym, [])
        if trig not in merged[sym]:
            merged[sym].append(trig)
    return [(s, " | ".join(t[:3])) for s, t in merged.items()]


def section(records, code_map):
    def at(r):
        mod = r["symbol"].split(":")[0]
        return {"sym": r["symbol"], "line": r["line"]} if not r["symbol"].endswith(":<module>") \
            else f'{code_map["modules"].get(mod, {}).get("file", mod)}:{r["line"]}'

    rows = []
    blocks = {(r["symbol"], r["line"]): r for r in records if r["kind"] == "block"}
    for r in sorted(records, key=lambda r: (r["symbol"], r["line"])):
        if r["kind"] == "page":
            rows.append(["page", r["page"], "–", at(r)])
        elif r["kind"] == "callback":
            rows.append([r["widget"], r.get("label", ""), r["target"].split(":", 1)[1], at(r)])
        elif r["kind"] == "widget":
            if not r["symbol"].endswith(":<module>"):
                runs = "the enclosing function"
            else:
                blk = next((b for (sym, line), b in blocks.items() if sym == r["symbol"] and line <= r["line"] <= b["end"]
                            and line >= r["line"] - 8), None)
                runs = ", ".join(c.split(":", 1)[1] for c in _block_calls(blk, code_map)) if blk else "–"
            rows.append([r["widget"], r.get("label", ""), runs or "–", at(r)])
    return {"columns": {"en": ["Widget", "Label / page", "Runs", "Where"], "ko": ["위젯", "이름 / 페이지", "실행", "위치"]},
            "rows": rows}
