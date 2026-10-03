"""code_map.json + narrative.toml → one self-contained HTML page.

The build fails (returns problems) when:
* the narrative names a symbol, module or table the code no longer has
* layers are declared and a module belongs to none of them (a new module the narrative doesn't know)
* a finding marked `check = "no_callers"` now has callers (the finding is no longer true)
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

try:
    from . import profiles as profile_registry
    from .common import Paths, count_todo, narrative_problems
except ImportError:  # script import
    import profiles as profile_registry
    from common import Paths, count_todo, narrative_problems

TEMPLATE = Path(__file__).resolve().parent / "template.html"
if not TEMPLATE.exists():  # inside the skill: scripts/ next to assets/
    TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "template.html"


def common_prefix(modules: list[str]) -> str:
    """`pkg.` when every module lives under one top-level package — trimmed in labels."""
    tops = {m.split(".")[0] for m in modules}
    if len(tops) == 1 and len(modules) > 1:
        return tops.pop() + "."
    return ""


def auto_layers(modules: dict) -> list[dict]:
    """One layer per package. With a single top-level package, one layer per subpackage plus one
    for the package's own flat modules. `pattern` is set only where `pkg.*` cannot swallow a sibling."""
    names = sorted(modules)
    prefix = common_prefix(names)
    groups, pattern = defaultdict(list), {}
    for m in names:
        rest = m[len(prefix):] if prefix and m.startswith(prefix) else m
        if prefix:
            if "." in rest:
                head = prefix + rest.split(".")[0]
                pattern[head] = True
            else:
                head = prefix[:-1]
        else:
            packages = {x.split(".")[0] for x in names if "." in x}
            head = m.split(".")[0] if ("." in m or m in packages) else "(top level)"
            if head != "(top level)":
                pattern[head] = True
        groups[head].append(m)
    if prefix and prefix[:-1] in groups:
        pattern.pop(prefix[:-1], None)  # the package's flat modules: explicit list, its subpackages are other layers
    layers = []
    for head, mods in sorted(groups.items(), key=lambda kv: (-sum(modules[m]["lines"] for m in kv[1]), kv[0])):
        lid = re.sub(r"[^a-z0-9]+", "-", head.lower()).strip("-") or "root"
        layers.append({"id": lid, "name": head, "owns": "", "modules": [head + ".*"] if pattern.get(head) else mods})
    return layers


def assign_layers(code_map: dict, narrative: dict) -> tuple[list[dict], dict[str, str], list[str]]:
    problems, mod_layer = [], {}
    layers = narrative.get("layers") or auto_layers(code_map["modules"])
    for layer in layers:
        for pat in layer.get("modules", []):
            matches = [m for m in code_map["modules"] if (m == pat[:-2] or m.startswith(pat[:-1])) ] if pat.endswith(".*") else ([pat] if pat in code_map["modules"] else [])
            for m in matches:
                if m in mod_layer and not pat.endswith(".*"):
                    problems.append(f"module {m} is in two layers: {mod_layer[m]} and {layer['id']}")
                mod_layer.setdefault(m, layer["id"])
    if narrative.get("layers"):
        for m in code_map["modules"]:
            if m not in mod_layer:
                problems.append(f"module {m} is in no layer — add it (or a `pkg.*` pattern) to [[layers]] in narrative.toml")
    return layers, mod_layer, problems


def check_rules(code_map: dict, narrative: dict, mod_layer: dict) -> list[dict]:
    rules = []
    for r in narrative.get("layer_rules", []):
        sources = set(r.get("from", []))
        for lid in r.get("from_layers", []):
            sources |= {m for m, layer in mod_layer.items() if layer == lid}
        violations = []
        for src in sorted(sources):
            info = code_map["modules"].get(src)
            if not info:
                continue
            for tgt in info["imports"] + info["lazy_imports"]:
                if any(tgt == f.rstrip(".") or (f.endswith(".") and tgt.startswith(f)) or tgt == f for f in r["forbid"]):
                    violations.append([src, tgt])
        rules.append({"text": r["text"], "sources": len(sources), "violations": violations})
    return rules


def incoming(code_map: dict) -> dict[str, set[str]]:
    inc = defaultdict(set)
    for a, b, _ in code_map["calls"] + code_map["refs"]:
        if a != b and not a.startswith(b + "."):
            inc[b].add(a)
    return inc


def finding_problems(narrative: dict, inc: dict) -> list[str]:
    out = []
    for f in narrative.get("findings", []):
        if f.get("check") == "no_callers" and f.get("symbols"):
            callers = sorted(inc.get(f["symbols"][0], ()))
            if callers:
                out.append(f"finding {f['id']}: {f['symbols'][0]} now has callers ({', '.join(callers[:3])}) — update or remove the finding")
    return out


def generated_findings(code_map: dict, narrative: dict, lang: str) -> list[dict]:
    ko = lang == "ko"
    named = {s for f in narrative.get("findings", []) for s in f.get("symbols", [])}
    out = []
    if code_map["import_cycles"]:
        out.append({"id": "gen-cycles", "severity": "medium", "category": "cycle", "generated": True,
                    "title": (f"모듈 수준 import 순환 {len(code_map['import_cycles'])}개" if ko else f"{len(code_map['import_cycles'])} module-level import cycle(s)"),
                    "detail": ("모듈 머리의 import 만으로 서로를 부른다. import 순서가 바뀌거나 새 import 가 생기면 ImportError 가 날 수 있다: " if ko else
                               "These modules import each other at module level; a change in import order or a new import can turn them into an ImportError: ") +
                              "; ".join(" ↔ ".join(c) for c in code_map["import_cycles"]),
                    "symbols": [], "modules": sorted({m for c in code_map["import_cycles"] for m in c})[:12],
                    "evidence": "Tarjan SCC over module-level imports (code_map.json import_cycles)."})
    dead = [s for s in code_map["dead_candidates"] if s not in named]
    if dead:
        out.append({"id": "gen-dead", "severity": "info", "category": "dead code", "generated": True,
                    "title": (f"내부 호출 · 참조 · 라우트 · 데코레이터가 없는 최상위 함수 {len(dead)}개" if ko else f"{len(dead)} top-level functions with no internal caller, reference, route or decorator"),
                    "detail": ("정적 분석의 후보일 뿐이다. 템플릿 · getattr · 외부 진입점 · 테스트 전용 도우미도 걸린다. 지우기 전에 grep 으로 확인하라." if ko else
                               "Candidates only: functions called from templates, via getattr, by an external entry point or only by tests also land here. grep before deleting."),
                    "symbols": dead, "evidence": "code_map.json dead_candidates."})
    public = {k: v for k, v in code_map["duplicate_names"].items() if not k.startswith("_")}
    if public:
        out.append({"id": "gen-dup-names", "severity": "info", "category": "duplicated logic", "generated": True,
                    "title": (f"같은 이름의 최상위 함수가 여러 모듈에 있는 경우 {len(public)}건" if ko else f"{len(public)} function names defined in more than one module"),
                    "detail": ("대부분은 우연히 같은 이름이지만 같은 일을 두 번 구현한 곳일 수 있다: " if ko else "Mostly coincidental names, but some may be the same logic written twice: ") +
                              "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(public.items())[:40]),
                    "symbols": sorted({s for v in public.values() for s in v})[:40], "evidence": "code_map.json duplicate_names."})
    if code_map["parse_errors"]:
        out.append({"id": "gen-parse", "severity": "low", "category": "coverage", "generated": True,
                    "title": (f"읽지 못한 파일 {len(code_map['parse_errors'])}개" if ko else f"{len(code_map['parse_errors'])} file(s) could not be parsed"),
                    "detail": "; ".join(f"{a}: {b}" for a, b in code_map["parse_errors"][:20]), "symbols": [], "evidence": "ast.parse failures."})
    s = code_map["summary"]
    out.append({"id": "gen-coverage", "severity": "info", "category": "coverage", "generated": True,
                "title": (f"함수 호출의 {s['graph_coverage']:.1%} 는 받는 쪽을 안다 (전체 호출 지점 기준 {s['resolved_ratio']:.1%})" if ko else
                          f"{s['graph_coverage']:.1%} of function calls have a known target ({s['resolved_ratio']:.1%} of all call sites)"),
                "detail": ((f"그래프 범위는 내장 함수와 값 메서드처럼 보이는 호출({s['unresolved_value_like']:,}개)을 뺀 값이다. 메서드 이름이 저장소 안 한 클래스에만 있는 호출 {s['inferred_edges']:,}개는 '추정' 간선(점선)으로 따로 그렸다. 동적 디스패치는 간선으로 나타나지 않는다. 해석 못 한 것 중 가장 많은 것: ") if ko else
                           (f"Graph coverage leaves out builtins and calls that look like value methods ({s['unresolved_value_like']:,}). {s['inferred_edges']:,} calls whose method name exists in exactly one class are drawn as dashed 'inferred' edges, not counted as resolved. Dynamic dispatch does not appear as edges. Most frequent unresolved: ")) +
                          ", ".join(f"{n}×{c}" for n, c in s["top_unresolved_names"][:8]),
                "symbols": [], "evidence": "code_map.json summary."})
    return out


def enrich(code_map: dict, key: str) -> dict:
    s = code_map["symbols"].get(key)
    if not s:
        info = code_map["modules"].get(key[:-2] if key.endswith(".*") else key, {})
        return {"symbol": key, "file": info.get("file", ""), "line": 1, "doc": info.get("doc", "")}
    out = {"symbol": key, "file": s["file"], "line": s["line"], "doc": s["doc"], "params": s.get("params", [])}
    if key in code_map["routes"]:
        out["urls"] = code_map["routes"][key]["urls"]
        out["guards"] = code_map["routes"][key]["guards"]
    return out


def build_data(paths: Paths, code_map: dict, narrative: dict) -> tuple[dict, list[str]]:
    cfg = paths.config
    if code_map.get("schema", 1) < 2:
        return {}, ["code_map.json is from an older version of the tools — run `codeflow.py map` (or `build`) to regenerate it"]
    lang = cfg["project"].get("language", "en")
    problems = narrative_problems(narrative, code_map)
    layers, mod_layer, lp = assign_layers(code_map, narrative)
    problems += lp
    inc = incoming(code_map)
    problems += finding_problems(narrative, inc)

    keys = sorted(code_map["symbols"])
    index = {k: i for i, k in enumerate(keys)}
    syms = []
    for k in keys:
        s = code_map["symbols"][k]
        mod, qual = k.split(":", 1)
        rec = {"m": mod, "q": qual, "t": s["kind"], "f": s["file"], "l": s["line"], "e": s["end"], "d": s["doc"]}
        if s.get("params"):
            rec["p"] = s["params"]
        if k in code_map["routes"]:
            r = code_map["routes"][k]
            rec["r"], rec["g"], rec["tp"] = r["urls"], r["guards"], r["templates"]
        syms.append(rec)
    edges = [[index[a], index[b], ln, 0] for a, b, ln in code_map["calls"] if a in index and b in index]
    edges += [[index[a], index[b], ln, 1] for a, b, ln in code_map["refs"] if a in index and b in index]
    edges += [[index[a], index[b], ln, 2] for a, b, ln in code_map.get("inferred_calls", []) if a in index and b in index]

    tables = {t: {"insert": set(), "update": set(), "delete": set(), "read": set(), "uses": set()} for t in code_map["tables"]}
    sym_tables = defaultdict(lambda: defaultdict(set))
    for e in code_map["sql"]:
        for op in ("insert", "update", "delete", "read"):
            for t in e.get(op, []):
                tables[t][op].add(e["symbol"])
                sym_tables[e["symbol"]][op].add(t)
    for t, users in code_map.get("orm_uses", {}).items():
        for u in users:
            tables.setdefault(t, {"insert": set(), "update": set(), "delete": set(), "read": set(), "uses": set()})["uses"].add(u)
            sym_tables[u]["uses"].add(t)
    tables = {t: {op: sorted(v) for op, v in ops.items()} for t, ops in tables.items()}
    sym_tables = {k: {op: sorted(v) for op, v in ops.items()} for k, ops in sym_tables.items()}

    notes = narrative.get("module_notes", {})
    modules = {m: {**info, "layer": mod_layer.get(m, "?"), "note": notes.get(m, ""), "funcs": [k for k in keys if k.startswith(m + ":")]}
               for m, info in code_map["modules"].items()}

    journeys = []
    for j in narrative.get("journeys", []):
        steps = [{**st, **{k: v for k, v in enrich(code_map, st["symbol"]).items() if k not in st}} for st in j.get("steps", [])]
        journeys.append({**j, "steps": steps})

    def with_loc(items):
        return [{**it, "_loc": enrich(code_map, it["symbol"])} if "symbol" in it else it for it in items]

    # stack profiles: their sections, and their per-symbol extras for the boundary cards
    by_name = {p.NAME: p for p in profile_registry.ALL}
    prof_sections, card_extras = [], defaultdict(list)
    for name, records in sorted(code_map.get("profiles", {}).items()):
        p = by_name.get(name)
        if not p:
            continue
        sec = p.section(records, code_map)
        prof_sections.append({"name": name, "title": p.TITLE.get(lang, p.TITLE["en"]), "intro": p.INTRO.get(lang, p.INTRO["en"]),
                              "columns": sec["columns"].get(lang, sec["columns"]["en"]), "rows": sec["rows"]})
        if hasattr(p, "card_extras"):
            for sym, rows in p.card_extras(records).items():
                card_extras[sym] += rows

    roles = [{**r, "_locs": [enrich(code_map, s) for s in r.get("symbols", [])]} for r in narrative.get("roles", [])]
    flows = [{**f, "steps": with_loc(f.get("steps", []))} for f in narrative.get("input_flows", [])]
    entities = [{**e, "events": with_loc(e.get("events", [])), "auto": tables.get(e.get("table", ""))} for e in narrative.get("entities", [])]
    findings = [{**f, "_locs": [enrich(code_map, s) for s in f.get("symbols", []) + f.get("modules", [])]} for f in narrative.get("findings", [])]
    findings += [{**f, "_locs": [enrich(code_map, s) for s in (f.get("symbols", []) + f.get("modules", []))[:12]]}
                 for f in generated_findings(code_map, narrative, lang)]

    gateways = defaultdict(list)
    for g in code_map["gateways"]:
        gateways[f'{g["gateway"]}("{g["action"]}")'].append([g["symbol"], g["line"]])

    # the most connected function is a better starting point for the explorer than an empty panel
    degree = defaultdict(int)
    for a, b, _ in code_map["calls"]:
        degree[a] += 1
        degree[b] += 1
    first_step = next((j["steps"][0]["symbol"] for j in narrative.get("journeys", []) if j.get("steps")), "")
    start = narrative.get("meta", {}).get("start_symbol") or first_step or (max(degree, key=lambda k: (degree[k], k)) if degree else "")

    rel_root = os.path.relpath(paths.root, paths.out).replace(os.sep, "/")
    meta = {"title": cfg["project"].get("name") or paths.root.name, "audience": cfg["project"].get("audience", ""), **narrative.get("meta", {})}
    vendored = (paths.tools / "codeflow.py").exists()
    regen = (f"python {os.path.relpath(paths.tools / 'codeflow.py', paths.root)} build" if vendored else "codeflow.py build")
    data = {
        "lang": lang, "meta": meta, "repo": cfg["project"].get("repo_url", "").rstrip("/"), "relRoot": rel_root + "/",
        "storeName": cfg["project"].get("store_name", "database"), "noisyServices": cfg["conventions"].get("noisy_services", []),
        "shortPrefix": common_prefix(list(code_map["modules"])), "startSymbol": start, "regenCommand": regen,
        "summary": code_map["summary"], "layers": [{k: v for k, v in l.items() if k != "modules"} for l in layers],
        "rules": check_rules(code_map, narrative, mod_layer), "modules": modules, "keys": keys, "syms": syms, "edges": edges,
        "tables": tables, "symTables": sym_tables, "external": code_map["external"], "gateways": dict(sorted(gateways.items())),
        "journeys": journeys, "roles": roles, "flows": flows, "entities": entities, "decisions": with_loc(narrative.get("decisions", [])),
        "findings": findings, "profiles": prof_sections, "cardExtras": dict(card_extras),
        "cycles": code_map["import_cycles"], "lazyCycles": code_map["lazy_import_cycles"],
        "problems": problems, "todo": count_todo(narrative),
    }
    return data, problems


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8")
    return page.replace("/*__DATA__*/{}", payload, 1).replace('<html lang="en">', f'<html lang="{data["lang"]}">', 1)
