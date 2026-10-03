"""Propose a narrative from the code map, so a human (or model) only writes the explanations.

Everything structural is filled from the code: layers, journey call chains (entry point → the
steps that reach storage or an external boundary, in call order), boundary cards per service and
per active stack profile, and data lifecycles from SQL/ORM use. Text a reader needs explained is
left as "TODO: …". The build counts TODOs and shows them, so a partly written report is honest.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

try:
    from . import infra as infra_scanner
    from . import profiles as profile_registry
    from .build import auto_layers, common_prefix
except ImportError:
    import infra as infra_scanner
    import profiles as profile_registry
    from build import auto_layers, common_prefix

DEPTH = {"quick": {"journeys": 3, "roles": 6, "entities": 6}, "standard": {"journeys": 6, "roles": 10, "entities": 10},
         "deep": {"journeys": 12, "roles": 16, "entities": 20}}
BACKGROUND = re.compile(r"(worker|job|task|cron|schedul|sweep|remind|consumer|listener|daemon|beat)", re.I)


# --------------------------------------------------------------------------- TOML writer (no dependency)

def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        if "\n" in v:
            return "'''\n" + v.replace("'''", "''\\'") + "\n'''" if "'''" not in v else json.dumps(v, ensure_ascii=False)
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_toml_key(k)} = {_toml_value(x)}" for k, x in v.items()) + "}"
    raise TypeError(type(v))


def _toml_key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def to_toml(doc: dict, header: str = "") -> str:
    out = [header.rstrip() + "\n"] if header else []
    # an empty list is left out, not written as `key = []`: a later [[key]] section would then be a TOML error
    simple = {k: v for k, v in doc.items() if not isinstance(v, (dict, list)) or (isinstance(v, list) and v and not any(isinstance(x, dict) for x in v))}
    for k, v in simple.items():
        out.append(f"{_toml_key(k)} = {_toml_value(v)}")
    for k, v in doc.items():
        if isinstance(v, dict) and v and all(isinstance(x, dict) for x in v.values()):
            for kk, vv in v.items():
                out.append(f"\n[{k}.{_toml_key(kk)}]")
                for k3, v3 in vv.items():
                    out.append(f"{_toml_key(k3)} = {_toml_value(v3)}")
        elif isinstance(v, dict):
            out.append(f"\n[{k}]")
            for kk, vv in v.items():
                out.append(f"{_toml_key(kk)} = {_toml_value(vv)}")
    for k, v in doc.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v:
                out.append(f"\n[[{k}]]")
                for kk, vv in item.items():
                    if isinstance(vv, list) and vv and all(isinstance(x, dict) for x in vv):
                        continue
                    out.append(f"{_toml_key(kk)} = {_toml_value(vv)}")
                for kk, vv in item.items():
                    if isinstance(vv, list) and vv and all(isinstance(x, dict) for x in vv):
                        for sub in vv:
                            out.append(f"  [[{k}.{kk}]]")
                            for k3, v3 in sub.items():
                                out.append(f"  {_toml_key(k3)} = {_toml_value(v3)}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- helpers

def _first_sentence(doc: str) -> str:
    if not doc:
        return ""
    m = re.split(r"(?<=[.!?。])\s", doc.strip(), maxsplit=1)
    text = m[0].strip()
    return text if len(text) <= 110 else text[:109] + "…"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "item"


class Graph:
    def __init__(self, cm: dict):
        self.cm = cm
        self.out = defaultdict(list)
        for a, b, line in cm["calls"] + cm.get("override_calls", []):  # an override really runs: follow it
            self.out[a].append((line, b))
        for a, b, line in cm["refs"]:
            if cm["symbols"].get(b, {}).get("kind") in ("function", "nested", "method"):
                self.out[a].append((line, b))  # callbacks passed as values usually run
        for k in self.out:
            self.out[k].sort()
        self.sinks = defaultdict(set)
        for e in cm["sql"]:
            if any(e.get(op) for op in ("insert", "update", "delete")):
                self.sinks[e["symbol"]].add("write")
            elif e.get("read"):
                self.sinks[e["symbol"]].add("read")
        for e in cm["external"]:
            self.sinks[e["symbol"]].add("external")
        for g in cm["gateways"]:
            self.sinks[g["symbol"]].add("gateway")
        sinking = {p.NAME for p in profile_registry.ALL if getattr(p, "SINK", True)}
        for name, recs in cm.get("profiles", {}).items():
            for r in recs if name in sinking else ():
                self.sinks[r["symbol"]].add("profile")
        # hubs: helpers called from very many places (connect, log, json helpers). Walking into them
        # floods a journey with plumbing, so a journey keeps a hub as one step at most and never descends.
        fan_in = Counter(b for a, b, _ in cm["calls"])
        cut = max(12, sorted(fan_in.values())[int(len(fan_in) * 0.98)] if fan_in else 12)
        self.hubs = {k for k, c in fan_in.items() if c >= cut}
        self.table_weight = Counter()
        for e in cm["sql"]:
            for op in ("insert", "update", "delete", "read"):
                for t in e.get(op, []):
                    self.table_weight[t] += 1
        self._reach = {}

    def reaches(self, k, depth=5, seen=None):
        """Sinks reachable from k within `depth` hops."""
        key = (k, depth)
        if key in self._reach:
            return self._reach[key]
        seen = seen or set()
        found = set(self.sinks.get(k, ()))
        if depth > 0 and k not in seen:
            seen = seen | {k}
            for _, b in self.out.get(k, []):
                found |= self.reaches(b, depth - 1, seen)
        self._reach[key] = found
        return found

    def chain(self, entry, limit=12):
        """Call-ordered walk from `entry`, keeping calls that lead to a sink; write paths first."""
        steps, seen = [], set()

        def walk(k, depth):
            if len(steps) >= limit or k in seen or depth > 6:
                return
            seen.add(k)
            if k in self.hubs and k != entry:
                if self.sinks.get(k, set()) & {"write", "gateway"}:
                    steps.append(k)
                return
            steps.append(k)
            callees = [b for _, b in self.out.get(k, []) if b not in seen and b in self.cm["symbols"]]
            if depth == 0:
                # the handler's own steps (validation, lookups) belong to the story even without a sink — but only a
                # few of them, or a long entry method spends the whole chain on setup before the real work starts
                kids = [b for b in callees if b not in self.hubs or self.sinks.get(b)]
                quiet = [b for b in kids if not self.reaches(b, 4)][3:]
                kids = [b for b in kids if b not in quiet]
            else:
                kids = [b for b in callees if self.reaches(b, 4)]
            writers = [b for b in kids if self.reaches(b, 4) & {"write", "gateway", "external", "profile"}]
            ordered = kids if depth == 0 else (writers or kids)
            for b in ordered:
                walk(b, depth + 1)

        walk(entry, 0)
        return steps

    def written_tables(self, steps):
        return {t for e in self.cm["sql"] if e["symbol"] in steps for op in ("insert", "update", "delete") for t in e.get(op, [])}


def entry_points(cm: dict) -> list[tuple[str, str, str]]:
    """(symbol, kind, trigger) — routes, CLI mains, decorated tasks, scheduled-looking modules."""
    out = []
    for k, r in cm["routes"].items():
        out.append((k, "route", " · ".join(f"{m} {u}" for m, u in r["urls"][:2])))
    for m, info in cm["modules"].items():
        # `python -m a.b` needs `a` to be a package; a script folder without __init__.py is run by path
        parent = m.rsplit(".", 1)[0] if "." in m else None
        in_script_folder = parent is not None and parent not in cm["modules"]
        run = f"python {info['file']}" if in_script_folder else f"python -m {m}"
        if info.get("cli") and f"{m}:main" in cm["symbols"]:
            out.append((f"{m}:main", "cli", run))
        elif f"{m}:<module>" in cm["symbols"] and (info.get("cli") or in_script_folder):
            out.append((f"{m}:<module>", "cli", run))  # a script whose work is its top-level code
    for name, target in cm.get("console_scripts", {}).items():
        mod, _, fn = target.partition(":")
        key = f"{mod}:{fn.split('.')[0]}" if fn else ""
        mod_key = next((m for m in cm["modules"] if m == mod or m.endswith("." + mod) or mod.endswith("." + m)), None)
        if mod_key and f"{mod_key}:{fn}" in cm["symbols"]:
            out.append((f"{mod_key}:{fn}", "cli", name))
        elif key in cm["symbols"]:
            out.append((key, "cli", name))
    out += library_api(cm)
    for sym, trig in infra_scanner.triggers(cm.get("infra") or {}):  # SQS IngestionQueue (Sqs) → Lambda UploadHandler
        if sym in cm["symbols"]:
            out.append((sym, "infra", trig))
    for r in cm.get("profiles", {}).get("jobs", []):
        out.append((r["job"], "job", r.get("how", "")))
    for k, s in cm["symbols"].items():
        if any(d.split(".")[-1] in ("task", "shared_task", "actor", "job") for d in s.get("decorators", [])):
            out.append((k, "job", "@" + s["decorators"][0]))
    by_name = {p.NAME: p for p in profile_registry.ALL}
    for name, recs in sorted(cm.get("profiles", {}).items()):
        p = by_name.get(name)
        if p and hasattr(p, "triggers"):
            out += [(sym, "ui", trig) for sym, trig in p.triggers(recs, cm) if sym in cm["symbols"]]
    seen, uniq = set(), []
    for e in out:
        if e[0] not in seen:
            seen.add(e[0])
            uniq.append(e)
    return uniq


ACTOR = {"route": "client", "cli": "operator (CLI)", "job": "scheduler / worker", "ui": "user (UI)", "api": "library user",
         "infra": "AWS (invokes the Lambda)"}

# a library's journeys start where its users call it: the entry methods of the classes it exports
API_METHODS = ("run", "__call__", "invoke", "ainvoke", "execute", "stream", "chat", "generate", "predict", "fit", "transform",
               "serve", "start", "process", "search", "query", "load", "convert", "parse")


def library_api(cm: dict) -> list[tuple[str, str, str]]:
    """Exported functions, and the entry methods (found through the bases) of exported classes, from each `__all__`."""
    syms, out = cm["symbols"], []

    def method_through_bases(cls_key, name, depth=0):
        if f"{cls_key}.{name}" in syms or depth > 5:
            return f"{cls_key}.{name}" if f"{cls_key}.{name}" in syms else None
        mod = cls_key.split(":", 1)[0]
        for b in syms.get(cls_key, {}).get("bases", []):
            b = b.rsplit(".", 1)[-1]
            hits = [f"{mod}:{b}"] if f"{mod}:{b}" in syms else [k for k, v in syms.items() if v["kind"] == "class" and k.endswith(":" + b)]
            found = method_through_bases(hits[0], name, depth + 1) if len(hits) == 1 else None
            if found:
                return found
        return None

    for mod, info in sorted(cm["modules"].items()):
        if mod.split(".")[-1].startswith("_"):
            continue
        for name in info.get("exports", []):
            key = f"{mod}:{name}"
            kind = syms.get(key, {}).get("kind")
            if kind == "function":
                out.append((key, "api", f"{name}()"))
            elif kind == "class":
                for m in API_METHODS:
                    target = method_through_bases(key, m)
                    if target:
                        out.append((target, "api", f"{name}().{m}()" if m != "__call__" else f"{name}()(…)"))
    return out


SIDE_WORDS = re.compile(r"(admin|backfill|migrat|seed|dump|debug|test|fixture|audit|sweep|export|import_|verify|revalidat)", re.I)


def rank_entries(cm: dict, g: "Graph") -> list[dict]:
    """Every entry point with its chain and a score — the draft takes the top ones, `candidates` prints them all."""
    out = []
    for sym, kind, trigger in entry_points(cm):
        steps = g.chain(sym)
        sinks = set().union(*(g.sinks.get(s, set()) for s in steps)) if steps else set()
        if len(steps) < 2 or not sinks:
            continue
        written = g.written_tables(steps)
        score = (len(sinks) * 10 + ("write" in sinks) * 15 + ("external" in sinks) * 6 + ("gateway" in sinks) * 10
                 + min(sum(g.table_weight[t] for t in written), 200) // 2 + min(len(steps), 10))
        if kind == "route" and any(m in ("POST", "PUT", "PATCH", "DELETE") for m, _ in cm["routes"][sym]["urls"]):
            score += 6
        if SIDE_WORDS.search(sym) or SIDE_WORDS.search(trigger):
            score -= 30
        out.append({"symbol": sym, "kind": kind, "trigger": trigger, "steps": steps, "sinks": sorted(sinks),
                    "writes": sorted(written), "score": score})
    out.sort(key=lambda x: (-x["score"], x["symbol"]))
    return out


def propose_journeys(cm: dict, g: Graph, n: int, cfg_noisy=("Template render", "Jinja", "AWS CDK")) -> list[dict]:
    scored = [(e["score"], e["symbol"], e["kind"], e["trigger"], e["steps"]) for e in rank_entries(cm, g)]
    picked, used_mods = [], Counter()
    for score, sym, kind, trigger, steps in scored:
        mod = sym.split(":")[0]
        if used_mods[mod] >= 2:  # spread the journeys across the codebase
            continue
        used_mods[mod] += 1
        picked.append((sym, kind, trigger, steps))
        if len(picked) >= n:
            break
    journeys, ids = [], set()
    for sym, kind, trigger, steps in picked:
        fn = sym.split(":", 1)[1]
        js = []
        for i, s in enumerate(steps):
            sd = cm["symbols"][s]
            st = {"symbol": s, "action": _first_sentence(sd.get("doc", "")) or f"TODO: what {s.split(':', 1)[1]} does here"}
            if i == 0:
                st["actor"] = ACTOR[kind]
            st["receives"] = ", ".join(p for p in sd.get("params", []) if p not in ("self", "cls")) or "–"
            st["returns"] = "TODO: what comes back"
            tables = sorted({t for e in cm["sql"] if e["symbol"] == s for op in ("insert", "update", "delete", "read") for t in e.get(op, [])})
            if tables:
                st["tables"] = tables
            noisy = set(cfg_noisy)
            ext = sorted({e["service"] for e in cm["external"] if e["symbol"] == s and e["service"] not in noisy})
            if ext:
                st["stores"] = ", ".join(ext)
            js.append(st)
        js[0]["payload"] = "TODO: a small, realistic example of what arrives here (invented values only)"
        jid = _slug(fn)
        if jid in ids:
            jid = _slug(sym.replace(":", "-"))
        ids.add(jid)
        journeys.append({"id": jid, "title": f"TODO: name this journey ({fn})", "actor": ACTOR[kind], "trigger": trigger,
                         "summary": "TODO: two sentences — what this does and where it ends", "steps": js})
    return journeys


def propose_roles(cm: dict, n: int) -> list[dict]:
    by_service = defaultdict(Counter)
    for e in cm["external"]:
        by_service[e["service"]][e["symbol"]] += 1
    noisy = {"Template render", "Jinja", "AWS CDK"}
    roles = []
    for service, users in sorted(by_service.items(), key=lambda kv: -sum(kv[1].values())):
        if service in noisy:
            continue
        real = [s for s, _ in users.most_common() if s in cm["symbols"]][:4]
        if not real:
            continue
        roles.append({"id": _slug(service), "name": service, "kind": "external", "symbols": real,
                      "purpose": f"TODO: what this code uses {service} for", "message": ["TODO: what is sent, in order"],
                      "config": "TODO: where it is configured (env var / config field names, never values)",
                      "output": "TODO: what comes back and how success is judged", "validation": "TODO: retries, timeouts, what happens on failure",
                      "logging": "TODO: where a call or a failure is recorded", "result_use": "TODO: what code does with the result"})
        if len(roles) >= n:
            break
    for m, info in sorted(cm["modules"].items()):
        if info.get("cli") and BACKGROUND.search(m) and f"{m}:main" in cm["symbols"]:
            roles.append({"id": "bg-" + _slug(m), "name": f"Background: {m}", "kind": "background", "symbols": [f"{m}:main"],
                          "purpose": "TODO: what runs, when, and who starts it", "validation": "TODO: idempotency, retries, failure handling",
                          "logging": "TODO: where a failed run is noticed"})
    by_name = {p.NAME: p for p in profile_registry.ALL}
    profile_roles = []
    for name, recs in sorted(cm.get("profiles", {}).items()):
        p = by_name.get(name)
        if p and hasattr(p, "draft_roles"):
            profile_roles += p.draft_roles(recs, cm)
    profile_roles += infra_roles(cm)
    covered = {s for r in profile_roles for s in r.get("symbols", [])}
    # a generic service card whose functions a profile card already explains would be a duplicate
    roles = [r for r in roles if not (r["kind"] == "external" and set(r["symbols"]) <= covered)]
    return roles + profile_roles


def infra_roles(cm: dict) -> list[dict]:
    """One card per Lambda whose Python handler is known: what invokes it, what it may touch, what tells it where."""
    infra = cm.get("infra") or {}
    roles = []
    for i, r in enumerate(infra.get("resources", [])):
        if not r.get("handler_symbol") or r["handler_symbol"] not in cm["symbols"]:
            continue
        edges = infra["edges"]
        inbound = [f"{infra_scanner.describe(infra, e['from'])} ({e['label']})" for e in edges if e["to"] == i and e["kind"] != "env"]
        grants = [f"{infra_scanner.describe(infra, e['to'])} ({e['label']})" for e in edges if e["from"] == i and e["kind"] == "grant"]
        env = [f"{e['label']} → {infra_scanner.describe(infra, e['to'])}" for e in edges if e["from"] == i and e["kind"] == "env"]
        roles.append({"id": "lambda-" + _slug(r["id"] + "-" + r["file"].rsplit("/", 1)[-1].split(".")[0]), "kind": "infra",
                      "name": f"Lambda {r['id']}", "symbols": [r["handler_symbol"]],
                      "purpose": "TODO: what this function is for, in one sentence",
                      "message": [f"invoked by: {x}" for x in inbound] or ["TODO: what invokes it (no trigger found in the CDK code)"],
                      "config": f"defined in {r['file']}:{r['line']}" + (f" · environment: {'; '.join(env)}" if env else ""),
                      "output": "TODO: what it returns or writes",
                      "validation": "TODO: retries, timeouts, dead-letter handling",
                      "logging": "TODO: where a failure is noticed",
                      "result_use": ("may use: " + "; ".join(grants)) if grants else "TODO: what it may touch (no grants found)"})
    return roles


def propose_input_flows(cm: dict, g: "Graph", n: int = 4) -> list[dict]:
    """Where outside data enters: write routes first. Steps are the handler and its first callees."""
    flows = []
    for sym, r in sorted(cm["routes"].items()):
        writes = [u for m, u in r["urls"] if m in ("POST", "PUT", "PATCH", "DELETE", "ANY")]
        if not writes:
            continue
        callees = [b for _, b in g.out.get(sym, []) if b in cm["symbols"] and b not in g.hubs][:3]
        flows.append({"id": _slug("in-" + sym.split(":", 1)[1]), "source": f"Request to {writes[0]} (TODO: what the client sends)",
                      "sink": "TODO: where it ends up (table, file, another system)",
                      "steps": [{"symbol": s, "guard": "TODO: what is checked, escaped or rejected here"} for s in [sym] + callees]})
        if len(flows) >= n:
            break
    return flows


def propose_entities(cm: dict, n: int) -> list[dict]:
    writers = defaultdict(lambda: defaultdict(list))
    for e in cm["sql"]:
        for op in ("insert", "update", "delete", "read"):
            for t in e.get(op, []):
                if e["symbol"] not in writers[t][op]:
                    writers[t][op].append(e["symbol"])
    for t, users in cm.get("orm_uses", {}).items():
        writers[t]["uses"] += users
    ranked = sorted(writers, key=lambda t: (-(len(writers[t]["insert"]) + len(writers[t]["update"]) + len(writers[t]["delete"])) * 3 - len(writers[t]["read"]) - len(writers[t]["uses"]), t))
    out = []
    stage = {"insert": "born", "update": "update", "delete": "delete", "read": "read", "uses": "read"}
    for t in ranked[:n]:
        events = []
        for op in ("insert", "update", "delete", "read", "uses"):
            for s in writers[t][op][:2]:
                if s in cm["symbols"]:
                    events.append({"stage": stage[op], "symbol": s, "text": f"TODO: {op} — {_first_sentence(cm['symbols'][s].get('doc', '')) or s.split(':', 1)[1]}"})
        if events:
            out.append({"id": _slug(t), "name": t, "table": t, "summary": "TODO: what one row of this means", "events": events})
    return out


def propose_module_notes(cm: dict) -> dict:
    """A place for every module. Never prefilled from the docstring — a copied first sentence says
    too little to follow the flow; the writer reads the module (`codeflow.py module <name>`)."""
    return {m: {"purpose": "TODO: why this module exists — what would not work without it",
                "does": "TODO: what it does, grouped into 2–5 capabilities (not a function list)",
                "flow": "TODO: who calls it and when → what it goes through → where it writes (tables, files, services)"}
            for m in sorted(cm["modules"])}


def draft(cm: dict, cfg: dict, depth: str = "quick") -> dict:
    lim = DEPTH.get(depth, DEPTH["quick"])
    g = Graph(cm)
    layers = auto_layers(cm["modules"])
    for l in layers:
        l["owns"] = "TODO: what this layer owns"
    return {
        "meta": {"title": cfg["project"].get("name") or "Code flow",
                 "lede": "TODO: two sentences — what this system does and how the main parts connect",
                 "audience": cfg["project"].get("audience") or ("Python 은 알지만 이 코드는 처음 보는 사람" if cfg["project"].get("language") == "ko" else "someone who knows Python but not this code")},
        "module_notes": propose_module_notes(cm),
        "layers": layers,
        "layer_rules": [],
        "journeys": propose_journeys(cm, g, lim["journeys"], cfg["conventions"].get("noisy_services", [])),
        "roles": propose_roles(cm, lim["roles"]),
        "input_flows": propose_input_flows(cm, g),
        "entities": propose_entities(cm, lim["entities"]),
        "decisions": [],
        "findings": [],
    }


HEADER = """# Narrative for the code-flow report — the only hand-written input.
#
# Structure (modules, functions, call edges, routes, SQL access, boundaries) comes from code_map.json.
# This file adds the explanation around it. Every `symbol` / `module` / `table` named here is checked
# against the code on every build; a name that no longer exists fails the build and the staleness test.
# Never write line numbers — the builder adds file:line from the code map.
#
# Proposed by `codeflow.py draft`. Replace every "TODO: …" (the report shows how many are left).
# Severities: high | medium | low | info.  Stages: born | transform | update | store | archive | restore | read | delete.
# A finding with a `check` retires itself: once the code no longer shows it, it moves to the page's Fixed list.
# Layer `modules` may use "pkg.*" patterns. With [[layers]] present, every module must match one.
# [module_notes."pkg.mod"]: purpose / does / flow (+ optional note) per module — written from the code, never a copied docstring.
"""
