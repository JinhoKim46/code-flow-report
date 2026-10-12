"""System map: one spec, several outputs.

A map is layers, parts (nodes) and labelled connections (edges), optionally with walkthrough steps
and tags. The same spec renders as:

* `to_fragment`   an interactive HTML block that drops into any page (the report, a docs site)
* `standalone_page` the same block as a complete single file
* `to_mermaid`    a flowchart GitHub draws inside a PR description or comment
* `to_markdown`   Mermaid plus a table of parts, for a PR body or a README

Spec (JSON; `codeflow.py system-map` writes one, the report reads `docs/code-flow/system_map.json`
when it exists and otherwise derives one from the code):

    {
      "title":  "…",
      "lang":   "en" | "ko",
      "layers": [{"id": "ui", "label": "UI", "color": "ui"}],       # color: ui | core | svc | lab | any
      "nodes":  [{"id": "home", "layer": "ui", "name": "Home", "sub": "app/views",
                  "job": "…", "files": ["…"], "facts": ["…"], "tags": ["R2"],
                  "x": 100, "y": 70}],                              # x / y optional: auto layout
      "edges":  [["home", "history", "reads progress"]],              # [from, to, label?]
      "steps":  [{"title": "…", "nodes": ["home"], "edges": [["home", "history"]], "text": "…"}],
      "tags":   ...                                                  # derived from node "tags"
    }
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC_FILE = "system_map.json"
COLORS = ("ui", "core", "svc", "lab")
W, H = 150, 52          # box size in the SVG (system_map.js draws the same)
COL_GAP, ROW_GAP = 180, 130
MAX_COLS = 6            # a wider layer wraps onto further rows, so a big repo grows down, not sideways
PAD = 40

LABELS = {
    "en": {"intro": "Click any box, tag or step.", "nothing": "Nothing selected. Click a box, a tag or a step.",
           "selected": "Selected", "outgoing": "outgoing", "incoming": "incoming", "clear": "Clear",
           "files": "Files", "facts": "Facts", "tags": "Tags", "calls": "Calls", "called_by": "Called by",
           "tag": "Tag", "walkthrough": "Walkthrough", "start": "Start walkthrough", "step": "Step",
           "of": "of", "prev": "Previous step", "next": "Next step", "show": "Show on map",
           "hint": "Arrows point from caller to callee. Double-click a stacked box to look inside. Esc clears the selection, then goes back up.",
           "open": "Look inside", "inside": "modules", "trail": "Where you are in the map"},
    "ko": {"intro": "상자, 태그 또는 단계를 누르세요.", "nothing": "선택한 것이 없습니다. 상자, 태그 또는 단계를 누르세요.",
           "selected": "선택", "outgoing": "나가는 연결", "incoming": "들어오는 연결", "clear": "해제",
           "files": "파일", "facts": "사실", "tags": "태그", "calls": "호출", "called_by": "호출하는 곳",
           "tag": "태그", "walkthrough": "흐름 따라가기", "start": "흐름 시작", "step": "단계",
           "of": "/", "prev": "이전 단계", "next": "다음 단계", "show": "맵에 표시",
           "hint": "화살표는 호출하는 쪽에서 호출받는 쪽을 가리킵니다. 겹친 상자를 더블클릭하면 안을 봅니다. Esc 는 선택 해제, 다시 누르면 한 단계 위로.",
           "open": "안 보기", "inside": "모듈", "trail": "맵에서 현재 위치"},
}


# --------------------------------------------------------------------------- validation and layout

def validate(spec: dict) -> list[str]:
    """Every problem in the spec, as text. An empty list means it can be rendered."""
    problems = []
    layers = spec.get("layers") or []
    layer_ids = [l.get("id") for l in layers]
    if len(set(layer_ids)) != len(layer_ids):
        problems.append("layer ids must be unique")
    nodes = spec.get("nodes") or []
    node_ids = [n.get("id") for n in nodes]
    if len(set(node_ids)) != len(node_ids):
        problems.append("node ids must be unique")
    for n in nodes:
        if not n.get("name"):
            problems.append(f"node {n.get('id')!r} has no name")
        if n.get("layer") not in layer_ids:
            problems.append(f"node {n.get('id')!r} is in unknown layer {n.get('layer')!r}")
    known = set(node_ids)
    edges = spec.get("edges") or []
    pairs = set()
    for i, e in enumerate(edges):
        if len(e) < 2:
            problems.append(f"edge {i} needs a start and an end")
            continue
        pairs.add((e[0], e[1]))
        for end in e[:2]:
            if end not in known:
                problems.append(f"edge {e[0]} -> {e[1]} ends at unknown node {end!r}")
    for s in spec.get("steps") or []:
        for nid in s.get("nodes", []):
            if nid not in known:
                problems.append(f"step {s.get('title')!r} names unknown node {nid!r}")
        for a, b in s.get("edges", []):
            if (a, b) not in pairs:
                problems.append(f"step {s.get('title')!r} names edge {a} -> {b}, which is not in the map")
    for n in nodes:  # a part's inside view (drill-down) follows the same rules
        if n.get("children"):
            problems += [f"inside {n.get('id')!r}: {p}" for p in validate(n["children"])]
    return problems


def layout(spec: dict) -> dict:
    """A copy with x, y on every node and the SVG `view` box. Layers are rows in layer order; a layer
    with more than MAX_COLS parts wraps onto further rows. Nodes that already carry x and y keep them.
    A part's inside view (`children`) is laid out the same way."""
    by_layer = defaultdict(list)
    for n in spec["nodes"]:
        by_layer[n["layer"]].append(n)
    placed, row = {}, 0
    for layer in spec["layers"]:
        members = by_layer.get(layer["id"], [])
        auto = [n for n in members if "x" not in n or "y" not in n]
        for n in members:
            if n not in auto:
                placed[n["id"]] = (n["x"], n["y"])
        for i, n in enumerate(auto):
            placed[n["id"]] = (80 + (i % MAX_COLS) * COL_GAP + W / 2, 50 + (row + i // MAX_COLS) * ROW_GAP + H / 2)
        if auto:
            row += (len(auto) - 1) // MAX_COLS + 1
    xs = [x for x, _ in placed.values()] or [0]
    ys = [y for _, y in placed.values()] or [0]
    x0, y0 = min(xs) - W / 2 - PAD, min(ys) - H / 2 - PAD
    view = [x0, y0, max(xs) + W / 2 + PAD - x0, max(ys) + H / 2 + PAD - y0]
    out = dict(spec)
    out["nodes"] = []
    for n in spec["nodes"]:
        node = {**n, "x": placed[n["id"]][0], "y": placed[n["id"]][1]}
        if n.get("children"):
            node["children"] = layout(n["children"])
        out["nodes"].append(node)
    out["edges"] = [list(e) for e in spec.get("edges") or []]
    out["view"] = [round(v, 1) for v in view]
    return out


def load(spec: dict) -> dict:
    """Validate, then lay out. Raises ValueError with every problem at once."""
    problems = validate(spec)
    if problems:
        raise ValueError("\n".join(problems))
    return layout(spec)


# --------------------------------------------------------------------------- Mermaid and Markdown

MERMAID_FILL = {"ui": "#e4ebf7", "core": "#e0f0ee", "svc": "#f6e1ea", "lab": "#f3e9dd", "data": "#eaf0dc", "any": "#eceeef"}


def _mid(text: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", text)


def _label(text: str) -> str:
    return str(text).replace('"', "#quot;").replace("\n", " ").replace("|", "/")


def to_mermaid(spec: dict) -> str:
    lines = ["flowchart LR"]
    by_layer = defaultdict(list)
    for n in spec["nodes"]:
        by_layer[n["layer"]].append(n)
    classes = defaultdict(list)
    for layer in spec["layers"]:
        members = by_layer.get(layer["id"])
        if not members:
            continue
        lines.append(f'  subgraph {_mid("L_" + layer["id"])}["{_label(layer["label"])}"]')
        for n in members:
            text = n["name"] + (f"<br/>{n['sub']}" if n.get("sub") else "")
            lines.append(f'    {_mid(n["id"])}["{_label(text)}"]')
            classes[layer.get("color") or "core"].append(_mid(n["id"]))
        lines.append("  end")
    for e in spec["edges"]:
        arrow = f'-->|"{_label(e[2])}"|' if len(e) > 2 and e[2] else "-->"
        lines.append(f"  {_mid(e[0])} {arrow} {_mid(e[1])}")
    for color, ids in sorted(classes.items()):
        fill = MERMAID_FILL.get(color, "#eeeeee")
        lines.append(f"  classDef {color} fill:{fill},stroke:#5b6764,color:#1b2422")
        lines.append(f"  class {','.join(ids)} {color}")
    return "\n".join(lines) + "\n"


def _cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def to_markdown(spec: dict) -> str:
    """For a PR body or README: the Mermaid chart, then the parts, then the walkthrough."""
    labels = LABELS.get(spec.get("lang", "en"), LABELS["en"])
    out = [f"## {spec['title']}", "", "```mermaid", to_mermaid(spec).rstrip(), "```", ""]
    layer_label = {l["id"]: l["label"] for l in spec["layers"]}
    out += ["| Part | Layer | Job | Files |", "|---|---|---|---|"]
    for n in spec["nodes"]:
        files = ", ".join(f"`{f}`" for f in n.get("files", [])[:4])
        out.append(f"| **{_cell(n['name'])}** | {_cell(layer_label.get(n['layer'], ''))} | {_cell(n.get('job', ''))} | {files} |")
    if spec.get("steps"):
        out += ["", f"### {labels['walkthrough']}", ""]
        for i, s in enumerate(spec["steps"], 1):
            out.append(f"{i}. **{_cell(s['title'])}** — {_cell(s.get('text', ''))}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- HTML

def assets_html() -> str:
    """The stylesheet and script every fragment needs, once per page."""
    css = (HERE / "system_map.css").read_text(encoding="utf-8")
    js = (HERE / "system_map.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    return f"<style>\n{css}\n</style>\n<script>\n{js}\n</script>"


def to_fragment(spec: dict) -> str:
    """The interactive block. Needs `assets_html()` on the page (once)."""
    lang = spec.get("lang", "en")
    if "view" not in spec:
        spec = layout(spec)
    payload = {**spec, "labels": LABELS.get(lang, LABELS["en"])}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = html.escape(spec["title"], quote=True)
    return (f'<h3 class="sysmap-title">{html.escape(spec["title"])}</h3>\n'
            f'<div class="sysmap" data-sysmap role="region" aria-label="{title}">\n'
            f'  <script type="application/json" class="sysmap-data">{data}</script>\n'
            f'  <noscript>{html.escape(spec["title"])}: {len(spec["nodes"])} parts, {len(spec["edges"])} connections.</noscript>\n'
            f'</div>\n')


def standalone_page(spec: dict) -> str:
    lang = spec.get("lang", "en")
    page = """<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  html { color-scheme: light dark; }
  body { margin: 0; background: #f5f6f4; color: #1b2422; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  @media (prefers-color-scheme: dark) { body { background: #111615; color: #e4ebe8; } }
  .page { max-width: 1120px; margin: 0 auto; padding: 24px 16px 48px; }
  .sysmap-title { font-size: 22px; margin: 0 0 12px; }
</style>
__ASSETS__
</head>
<body>
<main class="page">
__FRAGMENT__
</main>
</body>
</html>
"""
    return (page.replace("__LANG__", lang).replace("__TITLE__", html.escape(spec["title"]))
            .replace("__ASSETS__", assets_html()).replace("__FRAGMENT__", to_fragment(spec)))
