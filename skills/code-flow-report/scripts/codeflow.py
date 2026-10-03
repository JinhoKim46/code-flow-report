#!/usr/bin/env python3
"""codeflow — an interactive report of how a Python codebase actually works, generated from the source.

    codeflow.py init   [--root .] [--out docs/code-flow] [--lang en|ko] [--name NAME] [--audience TEXT]   detect config, vendor tools
    codeflow.py status [--root .]           repo size, existing report?, recommended depth
    codeflow.py map                         rebuild code_map.json and print coverage
    codeflow.py merge [PART.toml ...]       fold writer fragments (default: <out>/.parts/*.toml) into narrative.toml
    codeflow.py verify [--edges 5]          random call edges with their source lines, for a quick self-check
    codeflow.py draft  [--depth quick|standard|deep] [--force]   propose narrative.toml (TODO where prose is needed)
    codeflow.py query  SYMBOL [--depth 2]   a function's neighbourhood: calls, tables, boundaries, routes
    codeflow.py find   TEXT                 symbols whose name contains TEXT
    codeflow.py module NAME [NAME ...]      a module's overview (callers, callees, tables, boundaries, functions) to write its note
    codeflow.py todo                        list the narrative entries still marked TODO
    codeflow.py candidates [--limit 30]     every entry point ranked as a journey candidate
    codeflow.py build                       map + validate narrative + write the HTML (fails on stale narrative)
    codeflow.py check                       exit 1 if code_map.json, the narrative or the HTML is out of date
    codeflow.py install-test [--path tests/test_code_flow.py]   write a unittest that runs `check`
    codeflow.py report FILE.md              render a Markdown report as a matching HTML page

After `init`, the same scripts live in <out>/tools/, so anyone can rebuild without the skill installed.
Standard library only (Python 3.11+).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True  # never leave __pycache__ inside the target repo

import build as builder  # noqa: E402
import draft as drafter  # noqa: E402
import extract  # noqa: E402
from common import CONFIG_NAME, Paths, count_todo, load_map, load_narrative  # noqa: E402

SAMPLE_DIRS = {"examples", "example", "samples", "demos", "demo", "benchmarks", "benchmark", "notebooks", "cookbook", "docs_src"}
VENDORED = ["codeflow.py", "common.py", "extract.py", "build.py", "draft.py", "report.py"]


# --------------------------------------------------------------------------- init

def detect_config(root: Path, lang: str, name: str | None, audience: str = "") -> dict:
    """A starting codeflow.toml from what the repo looks like. Every value can be edited later."""
    exclude = list(extract.DEFAULT_EXCLUDE)
    include = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or child.name in exclude:
            continue
        if child.is_dir() and any(child.rglob("*.py")):
            include.append(child.name)
        elif child.suffix == ".py":
            include.append(child.name)
    # usage samples are not the code being explained: leave them out when there is other code to scan
    samples = [x for x in include if x.lower() in SAMPLE_DIRS]
    if len(samples) < len(include):
        include = [x for x in include if x not in samples]
    strip = ["src"] if (root / "src").is_dir() and any((root / "src").glob("*/__init__.py")) else []
    found = {f.suffix for f in extract.walk_files(root, set(exclude) - {"migrations"}) if f.suffix in (".sql", ".surql", ".surrealql")}
    schema = [g for g in extract.SCHEMA_GLOBS if g.rsplit(".", 1)[-1] in {s[1:] for s in found}]
    # first-parameter names used often enough to be a convention worth typing
    counts = Counter()
    cfg = {"scan": {"include": include or ["."], "exclude": exclude}}
    import ast
    import warnings
    for f in extract.source_files(root, cfg):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # the analysed code's own SyntaxWarnings are not ours to print
                tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.args.args:
                    a = n.args.args[0].arg
                    if a not in ("self", "cls"):
                        counts[a] += 1
        except SyntaxError:
            continue
    guesses = {"cur": "db.cursor()", "cursor": "db.cursor()", "conn": "db.connection()", "pg": "db.connection()",
               "session": "db.session()", "db": "db.session()", "request": "http.request()", "client": "http.client()"}
    param_types = {k: v for k, v in guesses.items() if counts[k] >= 10}
    return {
        "paths": {"root": ""},
        "project": {"name": name or root.name, "language": lang, "repo_url": "", "store_name": "database", "audience": audience},
        "scan": {"include": include or ["."], "exclude": exclude, "strip_prefixes": strip, "schema_globs": schema or ["**/*.sql"]},
        "conventions": {"param_types": param_types, "returns": {}, "gateways": [], "route_prefixes": {},
                        "noisy_services": ["Template render", "AWS CDK", "Jinja"]},
        "profiles": {"enable": [], "disable": []},
    }


def write_config(path: Path, cfg: dict) -> None:
    lines = ["# codeflow configuration — repo-specific knowledge the extractor cannot infer.",
             "# paths.root is the repo root relative to this file. param_types: first-parameter names that",
             "# always mean the same kind of object (lets `cur.execute(...)` resolve). gateways: function names",
             "# whose first string argument is an action label (a shared write/audit wrapper).",
             "# profiles: stack profiles are switched on by imports; force with enable / disable.", ""]
    lines.append(drafter.to_toml(cfg))
    path.write_text("\n".join(lines), encoding="utf-8")


def vendor(paths: Paths) -> None:
    paths.tools.mkdir(parents=True, exist_ok=True)
    for name in VENDORED:
        shutil.copy2(HERE / name, paths.tools / name)
    shutil.copy2(builder.TEMPLATE, paths.tools / "template.html")
    shutil.copytree(HERE / "profiles", paths.tools / "profiles", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (paths.tools / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (paths.out / ".gitignore").write_text(".parts/\n", encoding="utf-8")


def cmd_init(a) -> int:
    root = Path(a.root).resolve()
    out = (root / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg_file = out / CONFIG_NAME
    if cfg_file.exists() and not a.force:
        print(f"{cfg_file.relative_to(root)} exists — keeping it (use --force to re-detect).")
    else:
        cfg = detect_config(root, a.lang, a.name, a.audience or "")
        cfg["paths"]["root"] = str(Path(*[".."] * len(out.relative_to(root).parts))) if out != root else "."
        write_config(cfg_file, cfg)
        print(f"wrote {cfg_file.relative_to(root)}  (scan: {', '.join(cfg['scan']['include'])}; language: {a.lang})")
    paths = Paths(out)
    vendor(paths)
    print(f"vendored tools into {paths.tools.relative_to(root)}/ — rebuild later with: python {paths.tools.relative_to(root)}/codeflow.py build")
    return 0


# --------------------------------------------------------------------------- map / draft / build / check

def make_map(paths: Paths) -> dict:
    return extract.build(paths.root, paths.config)


def print_summary(cm: dict) -> None:
    s = cm["summary"]
    print(f"files {s['files']} · lines {s['lines']:,} · functions {s['functions']:,} · methods {s['methods']} · classes {s['classes']}")
    print(f"routes {s['routes']} · tables {s['tables']} (ORM models {s['orm_models']}) · SQL sites {s['sql_sites']} · "
          f"boundary sites {s['external_sites']} · gateway calls {s['gateway_sites']}")
    print(f"call sites {s['call_sites']:,}: internal {s['resolved_internal']:,} · library {s['resolved_external']:,} · builtin "
          f"{s['resolved_builtin']:,} · by convention {s['resolved_by_convention']:,} · unresolved {s['unresolved']:,} "
          f"→ resolved {s['resolved_ratio']:.1%}")
    print(f"graph coverage {s['graph_coverage']:.1%} (function calls with a known target — builtins and value-method-looking calls excluded) · "
          f"inferred edges {s['inferred_edges']:,} (unique method name, shown dashed) · "
          f"unresolved that look like value methods {s['unresolved_value_like']:,}")
    print(f"internal edges {s['internal_edges']:,} · reference edges {s['reference_edges']:,} · import cycles {s['import_cycles']} "
          f"(avoided by lazy import {s['lazy_import_cycles']}) · parse errors {s['parse_errors']}")
    if s.get("profiles"):
        print("stack profiles on: " + ", ".join(f"{k} ({v} records)" for k, v in s["profiles"].items()))
    print("most frequent unresolved: " + ", ".join(f"{n}×{c}" for n, c in s["top_unresolved_names"][:8]))


def cmd_map(a) -> int:
    paths = Paths.find()
    cm = make_map(paths)
    paths.code_map.write_text(extract.render(cm), encoding="utf-8")
    print_summary(cm)
    return 0


def cmd_draft(a) -> int:
    paths = Paths.find()
    if paths.narrative.exists() and not a.force:
        print(f"{paths.narrative.name} exists — not overwriting (use --force, or `todo` to see what is left).")
        return 1
    cm = make_map(paths)
    paths.code_map.write_text(extract.render(cm), encoding="utf-8")
    doc = drafter.draft(cm, paths.config, a.depth)
    paths.narrative.write_text(drafter.to_toml(doc, drafter.HEADER), encoding="utf-8")
    n = count_todo(load_narrative(paths))
    print(f"wrote {paths.narrative.name}: {len(doc['layers'])} layers · {len(doc['journeys'])} journeys · {len(doc['roles'])} boundary cards · "
          f"{len(doc['entities'])} entities · {n} TODOs to write")
    return 0


def _build(paths: Paths):
    cm = make_map(paths)
    data, problems = builder.build_data(paths, cm, load_narrative(paths))
    return cm, data, problems


def cmd_build(a) -> int:
    paths = Paths.find()
    cm, data, problems = _build(paths)
    paths.code_map.write_text(extract.render(cm), encoding="utf-8")
    if problems:
        print("the narrative no longer matches the code:")
        for p in problems:
            print("  -", p)
        return 1
    page = builder.render(data)
    paths.html.write_text(page, encoding="utf-8")
    print(f"wrote {paths.html} ({len(page.encode()) / 1024:,.0f} KB) · journeys {len(data['journeys'])} · boundary cards {len(data['roles'])} · "
          f"entities {len(data['entities'])} · findings {len(data['findings'])} · TODO left {data['todo']}")
    return 0


def check(paths: Paths) -> list[str]:
    cm, data, problems = _build(paths)
    out = list(problems)
    if not paths.code_map.exists() or paths.code_map.read_text(encoding="utf-8") != extract.render(cm):
        out.append(f"{paths.code_map.name} is stale — run: {data['regenCommand']}")
    if not problems and (not paths.html.exists() or paths.html.read_text(encoding="utf-8") != builder.render(data)):
        out.append(f"{paths.html.name} is stale — run: {data['regenCommand']}")
    return out


def cmd_check(a) -> int:
    problems = check(Paths.find())
    for p in problems:
        print(p)
    print("up to date" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# --------------------------------------------------------------------------- query helpers (for whoever writes the narrative)

def cmd_query(a) -> int:
    paths = Paths.find()
    cm = load_map(paths) if paths.code_map.exists() else make_map(paths)
    out, inn = {}, {}
    for x, y, line in cm["calls"] + cm["refs"]:
        out.setdefault(x, []).append((line, y))
        inn.setdefault(y, []).append((line, x))
    sql = {}
    for e in cm["sql"]:
        sql.setdefault(e["symbol"], []).append(e)
    ext = {}
    for e in cm["external"]:
        ext.setdefault(e["symbol"], set()).add(e["service"])
    targets = [a.symbol] if a.symbol in cm["symbols"] else [k for k in cm["symbols"] if k.endswith(":" + a.symbol) or k.endswith("." + a.symbol)]
    if not targets:
        print(f"no symbol {a.symbol!r}; try: codeflow.py find {a.symbol.split(':')[-1]}")
        return 1
    seen = set()

    def show(k, depth, ind):
        s = cm["symbols"].get(k, {})
        r = cm["routes"].get(k)
        print("  " * ind + f"{k}  {s.get('file')}:{s.get('line')}  ({', '.join(s.get('params', []))})" + (f"  {r['urls']} {r['guards']}" if r else ""))
        if s.get("doc"):
            print("  " * ind + "   doc: " + s["doc"][:140])
        for e in sql.get(k, []):
            print("  " * ind + "   sql: " + ", ".join(f"{op} {e[op]}" for op in ("insert", "update", "delete", "read") if e.get(op)) + f"  @{e['line']}")
        if k in ext:
            print("  " * ind + "   boundary: " + ", ".join(sorted(ext[k])))
        if depth == 0 or k in seen:
            return
        seen.add(k)
        for line, b in sorted(set(out.get(k, []))):
            print("  " * (ind + 1) + f"→ @{line} ", end="")
            show(b, depth - 1, ind + 1)

    for t in targets[:5]:
        callers = sorted(set(inn.get(t, [])))
        print(f"callers ({len(callers)}): " + ", ".join(f"{c}@{l}" for l, c in callers[:12]) + (" …" if len(callers) > 12 else ""))
        show(t, a.depth, 0)
        print()
    return 0


def cmd_module(a) -> int:
    """What a writer needs before describing a module: callers, callees, tables, boundaries, routes, functions."""
    from collections import Counter, defaultdict
    paths = Paths.find()
    cm = load_map(paths) if paths.code_map.exists() else make_map(paths)
    callers, callees = defaultdict(Counter), defaultdict(Counter)
    for x, y, _ in cm["calls"] + cm["refs"]:
        mx, my = x.split(":")[0], y.split(":")[0]
        if mx != my:
            callees[mx][my] += 1
            callers[my][mx] += 1
    tables = defaultdict(lambda: defaultdict(set))
    for e in cm["sql"]:
        for op in ("insert", "update", "delete", "read"):
            for t in e.get(op, []):
                tables[e["symbol"].split(":")[0]][op].add(t)
    ext = defaultdict(Counter)
    for e in cm["external"]:
        ext[e["symbol"].split(":")[0]][e["service"]] += 1
    for mod in a.modules:
        info = cm["modules"].get(mod)
        if not info:
            print(f"no module {mod!r}; modules look like: {', '.join(list(cm['modules'])[:5])} …")
            continue
        print(f"## {mod}  ({info['file']}, {info['lines']} lines{', python -m entry point' if info.get('cli') else ''})")
        print("docstring:", info["doc"] or "–")
        print("called by:", ", ".join(f"{m}×{c}" for m, c in callers[mod].most_common(10)) or "–")
        print("calls:", ", ".join(f"{m}×{c}" for m, c in callees[mod].most_common(12)) or "–")
        print("tables:", "; ".join(f"{op} {', '.join(sorted(v)[:10])}" for op, v in tables[mod].items()) or "–")
        print("boundaries:", ", ".join(f"{k}×{v}" for k, v in ext[mod].most_common()) or "–")
        fns = sorted(((k, s) for k, s in cm["symbols"].items() if k.startswith(mod + ":") and s["kind"] in ("function", "class", "method")),
                     key=lambda x: x[1]["line"])
        print(f"functions & classes ({len(fns)}):")
        for k, s in fns[: a.limit]:
            r = cm["routes"].get(k)
            print(f"  {k.split(':', 1)[1]}" + (f"  [{', '.join(f'{m} {u}' for m, u in r['urls'][:2])}]" if r else "") + (f" — {s['doc'][:110]}" if s["doc"] else ""))
        if len(fns) > a.limit:
            print(f"  … +{len(fns) - a.limit} more")
        print()
    return 0


def cmd_find(a) -> int:
    paths = Paths.find()
    cm = load_map(paths) if paths.code_map.exists() else make_map(paths)
    hits = sorted(k for k in cm["symbols"] if a.text.lower() in k.lower())
    for k in hits[:60]:
        s = cm["symbols"][k]
        print(f"{k}  {s['file']}:{s['line']}  {s['doc'][:80]}")
    print(f"{len(hits)} match(es)")
    return 0


def cmd_candidates(a) -> int:
    paths = Paths.find()
    cm = load_map(paths) if paths.code_map.exists() else make_map(paths)
    ranked = drafter.rank_entries(cm, drafter.Graph(cm))
    chosen = {s["symbol"] for j in load_narrative(paths).get("journeys", []) for s in j.get("steps", [])[:1]}
    for e in ranked[: a.limit]:
        mark = "*" if e["symbol"] in chosen else " "
        print(f"{mark} {e['score']:>4}  {e['symbol']}  [{e['kind']}] {e['trigger'][:60]}")
        print(f"        {len(e['steps'])} steps · sinks {', '.join(e['sinks'])} · writes {', '.join(e['writes']) or '–'}")
    print(f"{len(ranked)} entry points with a chain ( * = already a journey). Swap one in by editing narrative.toml, or re-run draft.")
    return 0


def cmd_todo(a) -> int:
    paths = Paths.find()
    doc = load_narrative(paths)
    n = 0

    def walk(x, where):
        nonlocal n
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                label = v.get("id") or v.get("symbol") or i if isinstance(v, dict) else i
                walk(v, f"{where}[{label}]")
        elif isinstance(x, str) and x.lstrip().startswith("TODO"):
            n += 1
            print(f"{where[1:]}: {x[:100]}")

    walk(doc, "")
    print(f"{n} TODO(s)")
    return 0


def cmd_status(a) -> int:
    """Size of the repo and whether a report exists — used to recommend a depth."""
    root = Path(a.root).resolve()
    cfg = {"scan": {"include": ["."], "exclude": list(extract.DEFAULT_EXCLUDE)}}
    files = extract.source_files(root, cfg)
    lines = sum(len(f.read_text(encoding="utf-8", errors="replace").splitlines()) for f in files)
    existing = (root / a.out / CONFIG_NAME).exists()
    rec = "standard" if lines < 30000 else "quick"
    print(f"python files {len(files)} · lines {lines:,} · existing report: {'yes' if existing else 'no'} · recommended depth: {rec}")
    if not files:
        print("no Python source found — this skill analyses Python only (stop and tell the user)")
        return 1
    return 0


def _entry_key(x):
    """What makes two entries the same one: the id, else the text/title (layer rules have no id), else the whole entry.
    Without a fallback, merging the same fragment twice would append its id-less entries twice."""
    if not isinstance(x, dict):
        return json.dumps(x, sort_keys=True)
    for k in ("id", "text", "title"):
        if x.get(k):
            return f"{k}:{x[k]}"
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def _merge_list(base: list, extra: list) -> list:
    out = list(base)
    index = {_entry_key(x): i for i, x in enumerate(out)}
    for item in extra:
        k = _entry_key(item)
        if k in index:
            out[index[k]] = None if isinstance(item, dict) and item.get("drop") else item
        elif isinstance(item, dict) and item.get("drop"):
            continue
        else:
            index[k] = len(out)
            out.append(item)
    return [x for x in out if x is not None]


def cmd_merge(a) -> int:
    """Fold TOML fragments (one per parallel writer) into narrative.toml, replacing entries by id.

    --check validates the merged result without writing it: parallel writers use it on their own fragment,
    because two writers merging at the same time would each overwrite the other's narrative.toml."""
    import tomllib
    from common import narrative_problems
    paths = Paths.find()
    doc = load_narrative(paths)
    parts = sorted(Path(p) for p in a.parts) if a.parts else sorted((paths.out / ".parts").glob("*.toml"))
    for part in parts:
        frag = tomllib.loads(part.read_text(encoding="utf-8"))
        for k, v in frag.items():
            if isinstance(v, list):
                doc[k] = _merge_list(doc.get(k, []), v)
            elif isinstance(v, dict):
                doc[k] = {**doc.get(k, {}), **v}
            else:
                doc[k] = v
        print(f"merged {part.name}: " + ", ".join(f"{k} {len(v) if isinstance(v, list) else 1}" for k, v in frag.items()))
    if not a.check:
        paths.narrative.write_text(drafter.to_toml(doc, drafter.HEADER), encoding="utf-8")
    problems = narrative_problems(doc, load_map(paths))
    for p in problems:
        print("  -", p)
    print(f"{count_todo(doc)} TODO(s) left · {len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_verify(a) -> int:
    """Random call edges with the calling line and the callee's definition, to check by eye."""
    import linecache
    import random
    paths = Paths.find()
    cm = load_map(paths)
    rng = random.Random(a.seed)
    sample = rng.sample(cm["calls"], min(a.edges, len(cm["calls"])))
    for caller, callee, line in sample:
        cfile = cm["symbols"].get(caller, {}).get("file") or cm["modules"][caller.split(":")[0]]["file"]
        d = cm["symbols"][callee]
        src = linecache.getline(str(paths.root / cfile), line).strip()
        dfn = linecache.getline(str(paths.root / d["file"]), d["line"]).strip()
        name = callee.split(":", 1)[1].split(".")[-1]
        ok = "ok " if name in src and name in dfn else "?? "
        print(f"{ok}{caller} -> {callee}")
        print(f"     call  {cfile}:{line}: {src[:120]}")
        print(f"     def   {d['file']}:{d['line']}: {dfn[:120]}")
    print(f"{len(sample)} edge(s); 'ok' = the callee's name is on the call line and on its def line. Read any '??' yourself.")
    return 0


TEST_TEMPLATE = '''"""The code-flow report must match the code. Fix: python {tools}/codeflow.py build"""
import subprocess
import sys
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[{depth}] / "{tools}" / "codeflow.py"


class CodeFlowReportIsCurrent(unittest.TestCase):
    def test_report_matches_code(self):
        run = subprocess.run([sys.executable, str(TOOL), "check"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
'''


def cmd_install_test(a) -> int:
    paths = Paths.find()
    target = (paths.root / a.path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rel_tools = paths.tools.relative_to(paths.root).as_posix()
    depth = len(target.relative_to(paths.root).parts) - 1
    target.write_text(TEST_TEMPLATE.format(tools=rel_tools, depth=depth), encoding="utf-8")
    print(f"wrote {target.relative_to(paths.root)} — it fails whenever the report is stale")
    return 0


def cmd_report(a) -> int:
    import report
    src = Path(a.file).resolve()
    paths = Paths.find()
    out = report.write(src, paths.config["project"].get("language", "en"))
    print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="codeflow.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--root", default="."); p.add_argument("--out", default="docs/code-flow")
    p.add_argument("--lang", default="en", choices=["en", "ko"]); p.add_argument("--name"); p.add_argument("--audience")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("status"); p.add_argument("--root", default="."); p.add_argument("--out", default="docs/code-flow"); p.set_defaults(fn=cmd_status)
    sub.add_parser("map").set_defaults(fn=cmd_map)
    p = sub.add_parser("merge"); p.add_argument("parts", nargs="*"); p.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("verify"); p.add_argument("--edges", type=int, default=5); p.add_argument("--seed", type=int, default=1); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("draft"); p.add_argument("--depth", default="quick", choices=list(drafter.DEPTH)); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_draft)
    p = sub.add_parser("query"); p.add_argument("symbol"); p.add_argument("--depth", type=int, default=2); p.set_defaults(fn=cmd_query)
    p = sub.add_parser("find"); p.add_argument("text"); p.set_defaults(fn=cmd_find)
    p = sub.add_parser("module"); p.add_argument("modules", nargs="+"); p.add_argument("--limit", type=int, default=60); p.set_defaults(fn=cmd_module)
    sub.add_parser("todo").set_defaults(fn=cmd_todo)
    p = sub.add_parser("candidates"); p.add_argument("--limit", type=int, default=30); p.set_defaults(fn=cmd_candidates)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    p = sub.add_parser("install-test"); p.add_argument("--path", default="tests/test_code_flow.py"); p.set_defaults(fn=cmd_install_test)
    p = sub.add_parser("report"); p.add_argument("file"); p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
