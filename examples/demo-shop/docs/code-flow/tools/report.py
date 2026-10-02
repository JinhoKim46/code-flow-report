"""A Markdown report → a matching single-file HTML page (same look as the code-flow report).

The Markdown stays the source; the HTML is generated from it so the two can never disagree.
Handles what such a report uses: headings, paragraphs, tables, lists, fenced code, **bold**,
`code` and [links](url).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

try:
    from .build import TEMPLATE
except ImportError:
    from build import TEMPLATE

UI = {"en": {"brand": "Report", "flow": "Code flow →", "theme_dark": "Dark", "theme_light": "Light",
             "footer": "Generated from {src}. Edit the Markdown and re-run `codeflow.py report {src}`."},
      "ko": {"brand": "보고서", "flow": "코드 흐름 →", "theme_dark": "어둡게", "theme_light": "밝게",
             "footer": "{src} 에서 생성했다. Markdown 을 고친 뒤 `codeflow.py report {src}` 를 다시 돌린다."}}


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return out


def cells(line: str) -> list[str]:
    body, parts, cur, in_code, i = line.strip().strip("|"), [], "", False, 0
    while i < len(body):
        ch = body[i]
        if ch == "`":
            in_code = not in_code
        if ch == "\\" and body[i + 1: i + 2] == "|":
            cur, i = cur + "|", i + 2
            continue
        if ch == "|" and not in_code:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur.strip())
    return parts


def convert(md: str):
    lines, out, toc, title, i, open_sec = md.splitlines(), [], [], "", 0, False
    while i < len(lines):
        line = lines[i]
        if line.startswith("# ") and not title:
            title, i = line[2:].strip(), i + 1
            continue
        if line.startswith("## "):
            if open_sec:
                out.append("</section>")
            head, sid = line[3:].strip(), f"s{len(toc) + 1}"
            toc.append((sid, re.sub(r"^\d+\.\s*", "", head)))
            out.append(f'<section id="{sid}"><div class="section-head"><h2>{inline(head)}</h2></div>')
            open_sec, i = True, i + 1
            continue
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:].strip())}</h3>")
            i += 1
            continue
        if line.startswith("```"):
            block, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            out.append(f'<pre class="payload">{html.escape(chr(10).join(block))}</pre>')
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            out.append('<div class="tablewrap"><table class="data"><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            out += ["<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body]
            out.append("</tbody></table></div>")
            continue
        if re.match(r"^\s*(\d+\.|-)\s", line):
            tag = "ol" if re.match(r"^\s*\d+\.\s", line) else "ul"
            items = []
            while i < len(lines) and re.match(r"^\s*(\d+\.|-)\s", lines[i]):
                items.append(re.sub(r"^\s*(\d+\.|-)\s+", "", lines[i]))
                i += 1
            out.append(f'<{tag} class="prose-list">' + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
            continue
        if line.strip() == "---":
            i += 1
            continue
        if line.strip():
            out.append(f"<p>{inline(line.strip())}</p>")
        i += 1
    if open_sec:
        out.append("</section>")
    return title, "\n".join(out), toc


def page(src: Path, lang: str = "en") -> str:
    ui = UI.get(lang, UI["en"])
    title, body, toc = convert(src.read_text(encoding="utf-8"))
    tpl = TEMPLATE.read_text(encoding="utf-8")
    css = tpl[tpl.index("<style>") + len("<style>"):tpl.index("</style>")]
    nav = "".join(f'<a href="#{sid}">{html.escape(label)}</a>' for sid, label in toc)
    first = body.find("<section")
    lede, rest = (body[:first], body[first:]) if first >= 0 else (body, "")
    flow_link = f'<a href="code-flow-report.html">{ui["flow"]}</a>' if (src.parent / "code-flow-report.html").exists() else ""
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title or ui["brand"])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{css}
.prose-list {{ margin: 0; padding-left: 22px; display: grid; gap: 6px; max-width: 80ch; }}
table.data td {{ min-width: 110px; }}
.topnav .wrap {{ scrollbar-width: none; }}
</style>
</head>
<body>
<nav class="topnav" aria-label="Sections"><div class="wrap"><a class="brand" href="#top">{html.escape(title or ui["brand"])}</a>{nav}{flow_link}<button class="themebtn" id="themebtn" type="button"></button></div></nav>
<main class="wrap" id="top">
<header class="hero"><h1>{html.escape(title)}</h1>{lede}</header>
{rest}
<footer><p>{inline(ui["footer"].format(src=src.name))}</p></footer>
</main>
<script>
(function () {{
  const get = (k) => {{ try {{ return localStorage.getItem(k); }} catch (e) {{ return null; }} }};
  const set = (k, v) => {{ try {{ localStorage.setItem(k, v); }} catch (e) {{}} }};
  const root = document.documentElement, btn = document.getElementById("themebtn");
  const saved = get("codeflow-theme"); if (saved) root.setAttribute("data-theme", saved);
  const dark = () => root.getAttribute("data-theme") ? root.getAttribute("data-theme") === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const label = () => {{ btn.textContent = dark() ? {ui["theme_light"]!r} : {ui["theme_dark"]!r}; }};
  label();
  btn.addEventListener("click", () => {{ const n = dark() ? "light" : "dark"; root.setAttribute("data-theme", n); set("codeflow-theme", n); label(); }});
}})();
</script>
</body>
</html>
"""


def write(src: Path, lang: str = "en") -> Path:
    out = src.with_suffix(".html")
    out.write_text(page(src, lang), encoding="utf-8")
    return out
