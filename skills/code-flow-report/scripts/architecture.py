"""The shape of any Python repo, read from its own structure: roles for modules, groups for the map.

Nothing here knows a framework or a project. A module's role comes from what the code shows:

* entry    owns something a user or another system starts: a route, a UI page, a background job,
           a cloud function, an infrastructure handler
* script   a runnable file (`if __name__ == "__main__"`) that people start by hand
* data     reads or writes a stored table (SQL text or an ORM model)
* logic    reached from an entry point, none of the above
* support  reached from no entry point: tools, leftovers, one-off helpers

A library has no entry point of its own; then its roots (modules nothing else in the repo imports)
play that part. Modules are grouped into map nodes by package, split again by role, so one node
never mixes an entry page with the logic it calls.
"""
from __future__ import annotations

import posixpath
import re
from collections import defaultdict, deque

ROLES = ("entry", "script", "logic", "data", "support")
ENTRY_PROFILES = ("ui", "jobs", "cloudfn")

# Layer wording for the map. Plain and role-based: no framework names, so any repo reads the same way.
ROLE_TEXT = {
    "en": {
        "entry": ("Entry points", "Where users and other systems start the code: pages, routes, jobs, handlers."),
        "script": ("Scripts", "Runnable files started by hand: command-line tools and experiments."),
        "logic": ("Core logic", "Code reached from an entry point that does the work, not tied to a stored table."),
        "data": ("Data access", "Code that reads or writes stored tables."),
        "support": ("Support", "Not reached from any entry point: tools, leftovers and one-off helpers."),
        "external": ("External services", "Outside systems the code calls over the network or through a library."),
    },
    "ko": {
        "entry": ("진입점", "사용자나 다른 시스템이 코드를 시작하는 곳: 화면, 경로, 작업, 핸들러."),
        "script": ("스크립트", "사람이 직접 실행하는 파일: 명령줄 도구와 실험."),
        "logic": ("핵심 로직", "진입점에서 호출되어 실제 일을 하는 코드. 저장 테이블에 묶이지 않은 부분."),
        "data": ("데이터 접근", "저장된 테이블을 읽거나 쓰는 코드."),
        "support": ("지원", "어떤 진입점에서도 도달하지 않는 코드: 도구, 남은 코드, 일회성 도우미."),
        "external": ("외부 서비스", "네트워크나 라이브러리를 통해 코드가 호출하는 외부 시스템."),
    },
}


def module_graph(code_map: dict) -> dict[str, set[str]]:
    """Caller module -> callee modules (calls and imports, inside the repo only)."""
    mods = set(code_map["modules"])
    graph: dict[str, set[str]] = defaultdict(set)
    for caller, callee, _line in code_map.get("calls", []):
        a, b = caller.split(":")[0], callee.split(":")[0]
        if a != b and a in mods and b in mods:
            graph[a].add(b)
    for m, info in code_map["modules"].items():
        for imported in info.get("imports", []):
            if imported in mods and imported != m:
                graph[m].add(imported)
    return graph


def _page_module(code_map: dict, caller: str, page: str) -> str | None:
    """A page registered as `page` (e.g. "views/home.py") from `caller`'s file is the module whose
    file that path resolves to, relative to the registering file's folder."""
    mods = code_map["modules"]
    base = posixpath.dirname(mods[caller]["file"]) if caller in mods else ""
    target = posixpath.normpath(posixpath.join(base, page))
    for m, info in mods.items():
        if info["file"] == target:
            return m
    return None


def entry_and_script(code_map: dict) -> tuple[set[str], set[str]]:
    mods = code_map["modules"]
    entries: set[str] = set()
    for symbol in code_map.get("routes", {}):
        entries.add(symbol.split(":")[0])
    for name in ENTRY_PROFILES:
        for rec in code_map.get("profiles", {}).get(name, []):
            caller = rec["symbol"].split(":")[0]
            if rec.get("kind") == "page" and rec.get("page"):
                # a registered page is its own module; the module that registers it is the app's
                # launcher (the file people run), so it is an entry point too
                target = _page_module(code_map, caller, rec["page"])
                if target:
                    entries.add(target)
            entries.add(caller)
    entries = {m for m in entries if m in mods}
    scripts = {m for m, info in mods.items() if info.get("cli")} - entries
    return entries, scripts


def roles(code_map: dict) -> dict[str, str]:
    """Role of every repo module (see the module docstring)."""
    mods = code_map["modules"]
    graph = module_graph(code_map)
    entries, scripts = entry_and_script(code_map)
    if not entries and not scripts:  # a library: its roots play the entry points
        imported = {b for targets in graph.values() for b in targets}
        entries = {m for m in mods if m not in imported}
    # reachability from every entry point along calls and imports
    reach: set[str] = set()
    queue = deque(entries | scripts)
    while queue:
        m = queue.popleft()
        if m in reach:
            continue
        reach.add(m)
        queue.extend(graph.get(m, ()))
        # importing a module runs its parent packages, so they are reached with it
        parts = m.split(".")
        for i in range(1, len(parts)):
            queue.append(".".join(parts[:i]))
    touches = {s["symbol"].split(":")[0] for s in code_map.get("sql", []) if "symbol" in s}
    for symbols in code_map.get("orm_uses", {}).values():
        touches |= {s.split(":")[0] for s in symbols}
    out = {}
    for m in mods:
        if m in entries:
            out[m] = "entry"
        elif m in scripts:
            out[m] = "script"
        elif m not in reach:
            out[m] = "support"
        elif m in touches:
            out[m] = "data"
        else:
            out[m] = "logic"
    return out


def node_roles(role: dict[str, str], package_modules: list[str]) -> dict[str, str]:
    """Node role of each module within one package. Only the logic modules of a package share one
    node; entry, script, support and data modules each keep their own, so a page never hides the
    logic it calls and the storage code stays visible."""
    core = [m for m in package_modules if role[m] == "logic"]
    return {m: ("logic" if m in core else role[m]) for m in package_modules}


def group_key(module: str) -> str:
    """Package-level grouping: `app.views.home` -> `app.views`, `interview_app.llm.client` -> `interview_app.llm`,
    `interview_app.db` -> `interview_app`, a top-level module stands alone."""
    parts = module.split(".")
    if len(parts) >= 3:
        return ".".join(parts[:2])
    if len(parts) == 2:
        return parts[0]
    return module


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


MIN_CALLS = 3  # connections with fewer calls are left out of the overview: they are noise at map scale
NAME_MAX = 20  # a map box is 150 px wide; longer names are cut, the full one stays in `package`


def _fit(name: str, limit: int = NAME_MAX) -> str:
    """Cut a name to fit a box. A dotted name keeps its tail, where the part's own name is."""
    if len(name) <= limit:
        return name
    return "…" + name[-(limit - 1):] if "." in name else name[:limit - 1] + "…"


def short_names(packages: list[str]) -> dict[str, str]:
    """Box name of each package: its last segment, or, when another package ends the same way,
    the shortest dotted suffix no other package shares (`app.lab` vs `interview_app.lab`)."""
    split = {p: p.split(".") for p in set(packages)}
    out = {}
    for p, parts in split.items():
        others = [o for q, o in split.items() if q != p]
        for k in range(1, len(parts) + 1):
            tail = parts[-k:]
            if all(o[-k:] != tail for o in others):
                break
        out[p] = _fit(".".join(parts[-k:]))
    return out


JOB_SENTENCES = 3   # a part's job combines at most this many module purposes
JOB_CHARS = 320     # ... and stops adding them past this length: the job sits in a box panel
FACTS_MAX = 4       # capability lines per part


def _items(does) -> list[str]:
    """A narrative `does` as a list of capabilities: a list as is, a string split at `;`."""
    raw = does if isinstance(does, list) else str(does or "").split(";")
    return [s.strip().rstrip(".").strip() for s in raw if str(s).strip() and not str(s).strip().startswith("TODO")]


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?", "。")) else text + "."


def part_job(modules: list[str], purposes: dict[str, str], capabilities: dict, lang: str = "en") -> str:
    """One part's job, from its modules' purposes (largest module first; `does` when a module has
    no purpose), deduplicated and kept short. Says plainly when no module is described."""
    out: list[str] = []
    seen: set[str] = set()
    for m in modules:
        s = purposes.get(m) or next(iter(_items(capabilities.get(m))), "")
        if not s or s.strip().startswith("TODO"):
            continue
        s = _sentence(s)
        key = re.sub(r"\W+", " ", s.lower()).strip()
        if key in seen:
            continue
        if out and (len(out) >= JOB_SENTENCES or len(" ".join(out)) + len(s) > JOB_CHARS):
            break
        seen.add(key)
        out.append(s)
    if out:
        return " ".join(out)
    n = len(modules)
    return f"Not described yet: {n} module{'s' if n != 1 else ''}." if lang == "en" else f"아직 설명 없음: 모듈 {n}개."


def part_facts(modules: list[str], capabilities: dict) -> list[str]:
    """Up to FACTS_MAX things the part does: the first `does` item of each module, largest first."""
    out: list[str] = []
    for m in modules:
        first = next(iter(_items(capabilities.get(m))), "")
        if first and first not in out:
            out.append(first)
        if len(out) >= FACTS_MAX:
            break
    return out


# what follows a call on its result is plumbing, not what the code uses the service for
_RESULT_ACCESS = {"json", "raise_for_status", "headers.get", "text", "content", "status_code", "read", "close"}


def _main_calls(calls: list[dict]) -> list[str]:
    """The service calls that say what the code does with it, most used first: a constructor that is
    only followed by its methods, and accessors on a call's result, are left out."""
    count: dict[str, int] = defaultdict(int)
    for c in calls:
        count[c["call"]] += 1
    names = set(count)

    def plumbing(x: str) -> bool:
        # `x` is only a constructor when a method is called on what it returns
        if any(o.startswith(x + "().") and o[len(x) + 3:] not in _RESULT_ACCESS for o in names):
            return True
        return any(x.startswith(o + "().") and x[len(o) + 3:] in _RESULT_ACCESS for o in names)

    keep = [x for x in names if not plumbing(x)] or sorted(names)
    return sorted(keep, key=lambda x: (-count[x], x))


def service_job(calls: list[dict], lang: str = "en", limit: int = 3) -> str:
    """An external service's job: which modules call it and the calls they make, from the code map."""
    users: dict[str, int] = defaultdict(int)
    for c in calls:
        users[c["symbol"].split(":")[0]] += 1
    where = sorted(users, key=lambda m: (-users[m], m))
    shown = ", ".join(where[:limit]) + (f" (+{len(where) - limit})" if len(where) > limit else "")
    main = _main_calls(calls)
    what = ", ".join(main[:limit]) + (f" (+{len(main) - limit})" if len(main) > limit else "")
    if lang == "en":
        return f"Called from {shown}: {what}."
    return f"{shown}에서 호출: {what}."


def calls_label(n: int, lang: str) -> str:
    if lang == "ko":
        return f"{n}회"
    return f"{n} call" if n == 1 else f"{n} calls"


INSIDE_TEXT = {
    "en": {"callers": "Called from", "modules": "Modules", "callees": "Calls out to"},
    "ko": {"callers": "호출하는 부품", "modules": "모듈", "callees": "호출하는 대상"},
}


def part_inside(part: dict, modules: list[str], mods: dict, node_of: dict[str, str],
                module_calls: dict[tuple[str, str], int], module_services: dict[tuple[str, str], int],
                parts: dict[str, dict], purposes: dict[str, str], capabilities: dict, lang: str) -> dict:
    """What a part looks like opened: its modules in the middle, the parts that call into it above and
    the parts (and services) it calls below, with call counts. The map shows it on a drill-down."""
    text = INSIDE_TEXT[lang]
    inside = set(modules)
    edges: dict[tuple[str, str], int] = defaultdict(int)
    callers: set[str] = set()
    callees: set[str] = set()
    for (a, b), n in module_calls.items():
        if a in inside and b in inside:
            edges[("m:" + a, "m:" + b)] += n
        elif b in inside:
            callers.add(node_of[a])
            edges[(node_of[a], "m:" + b)] += n
        elif a in inside:
            callees.add(node_of[b])
            edges[("m:" + a, node_of[b])] += n
    for (m, sid), n in module_services.items():
        if m in inside:
            callees.add(sid)
            edges[("m:" + m, sid)] += n
    callees -= callers  # a part both calls in and is called stays in one row, above
    # one package can be two parts (logic and data); say which, or the row shows the same name twice
    shown = [parts[pid]["name"] for pid in callers | callees]
    def neighbour(pid: str, row: str) -> dict:
        p = parts[pid]
        role = p["layer"] if lang == "en" else ROLE_TEXT[lang].get(p["layer"], (p["layer"],))[0]
        name = p["name"] if shown.count(p["name"]) == 1 else f"{p['name']} · {role}"
        return {"id": pid, "layer": row, "name": name if len(name) <= NAME_MAX + 8 else _fit(p["name"]) + f" · {role}",
                "package": p.get("package", p["name"]), "sub": p.get("sub", "")}
    nodes = []
    for pid in sorted(callers):
        nodes.append(neighbour(pid, "callers"))
    for m in sorted(modules, key=lambda m: (-mods[m]["lines"], m)):
        n = {"id": "m:" + m, "layer": "modules", "name": _fit(m.split(".")[-1]), "package": m,
             "sub": (f"{mods[m]['lines']} lines" if lang == "en" else f"{mods[m]['lines']}줄"),
             "files": [mods[m]["file"]], "facts": _items(capabilities.get(m))[:4]}
        job = purposes.get(m) or next(iter(_items(capabilities.get(m))), "")
        if job:
            n["job"] = job
        nodes.append(n)
    for pid in sorted(callees):
        nodes.append(neighbour(pid, "callees"))
    present = {n["layer"] for n in nodes}
    layers = [{"id": lid, "label": text[lid], "color": {"callers": "any", "modules": "core", "callees": "any"}[lid]}
              for lid in ("callers", "modules", "callees") if lid in present]
    return {"title": part.get("package", part["name"]), "lang": lang, "layers": layers, "nodes": nodes,
            "edges": [[a, b, calls_label(n, lang)] for (a, b), n in sorted(edges.items())]}


def map_spec(code_map: dict, lang: str = "en", title: str = "", purposes: dict[str, str] | None = None,
             min_calls: int = MIN_CALLS, capabilities: dict | None = None) -> dict:
    """The system map of a repo, as a spec for system_map.load. `purposes` (module -> one sentence)
    and `capabilities` (module -> the narrative's `does`, a string split at `;` or a list) give each
    part its job and facts; a part the narrative does not describe says so."""
    lang = lang if lang in ROLE_TEXT else "en"
    text = ROLE_TEXT[lang]
    purposes = purposes or {}
    capabilities = capabilities or {}
    mods = code_map["modules"]
    role = roles(code_map)

    by_package: dict[str, list[str]] = defaultdict(list)
    for m in mods:
        by_package[group_key(m)].append(m)
    node_role: dict[str, str] = {}
    for ms in by_package.values():
        node_role.update(node_roles(role, ms))
    members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for m in mods:
        members[(group_key(m), node_role[m])].append(m)

    def node_id(key: tuple[str, str]) -> str:
        return f"{_slug(key[0])}--{key[1]}"

    nodes = []
    for key, ms in sorted(members.items(), key=lambda kv: (ROLES.index(kv[0][1]), kv[0][0])):
        ms = sorted(ms)
        lines = sum(mods[m]["lines"] for m in ms)
        files = sorted({mods[m]["file"] for m in ms})
        biggest = sorted(ms, key=lambda m: (-mods[m]["lines"], m))
        job = part_job(biggest, purposes, capabilities, lang)
        # the last part of the package name fits in a box; the full name is kept in `package`
        n = {"id": node_id(key), "layer": key[1], "name": key[0].split(".")[-1], "package": key[0],
             "sub": (f"{len(ms)} modules · {lines} lines" if lang == "en" else f"모듈 {len(ms)}개 · {lines}줄"),
             "files": files[:6], "facts": part_facts(biggest, capabilities) or ms[:8], "job": job}
        nodes.append(n)

    # one short name per package, unique across the map (one package may still sit on several layers)
    names = short_names([n["package"] for n in nodes])
    for n in nodes:
        n["name"] = names[n["package"]]

    edges: dict[tuple[str, str], int] = defaultdict(int)
    for caller, callee, _line in code_map.get("calls", []):
        a, b = caller.split(":")[0], callee.split(":")[0]
        if a in mods and b in mods and a != b:
            ka, kb = (group_key(a), node_role[a]), (group_key(b), node_role[b])
            if ka != kb:
                edges[(node_id(ka), node_id(kb))] += 1

    services: dict[str, list[dict]] = defaultdict(list)
    for ext in code_map.get("external", []):
        services[ext["service"]].append(ext)
    external_layer = "external"
    svc_ids = {}
    for name in sorted(services):
        sid = "ext-" + _slug(name)
        svc_ids[name] = sid
        calls = services[name]
        nodes.append({"id": sid, "layer": external_layer, "name": _fit(name), "package": name,
                      "sub": (f"{len(calls)} call sites" if lang == "en" else f"호출 지점 {len(calls)}곳"),
                      "facts": sorted({c["call"] for c in calls})[:4], "job": service_job(calls, lang)})
    for name, calls in services.items():
        for c in calls:
            m = c["symbol"].split(":")[0]
            if m in mods:
                edges[(node_id((group_key(m), node_role[m])), svc_ids[name])] += 1

    node_of = {m: node_id((group_key(m), node_role[m])) for m in mods}
    module_calls: dict[tuple[str, str], int] = defaultdict(int)
    for caller, callee, _line in code_map.get("calls", []):
        a, b = caller.split(":")[0], callee.split(":")[0]
        if a in mods and b in mods and a != b:
            module_calls[(a, b)] += 1
    module_services: dict[tuple[str, str], int] = defaultdict(int)
    for name, calls in services.items():
        for c in calls:
            m = c["symbol"].split(":")[0]
            if m in mods:
                module_services[(m, svc_ids[name])] += 1
    by_id = {n["id"]: n for n in nodes}
    for key, ms in members.items():
        part = by_id[node_id(key)]
        part["children"] = part_inside(part, ms, mods, node_of, module_calls, module_services, by_id,
                                       purposes, capabilities, lang)

    present = {n["layer"] for n in nodes}
    layers = []
    for r in ROLES + (external_layer,):
        if r in present:
            label, owns = text[r]
            layers.append({"id": r, "label": label, "owns": owns, "color": {"entry": "ui", "script": "lab", "logic": "core", "data": "data", "support": "any", "external": "svc"}[r]})
    # a small repo keeps every connection; a large one drops the one-off calls that only add clutter
    threshold = min_calls if len(edges) > 40 else 1
    out_edges = [[a, b, calls_label(n, lang)] for (a, b), n in sorted(edges.items()) if n >= threshold]
    return {"title": title or ("System map" if lang == "en" else "시스템 맵"), "lang": lang,
            "layers": layers, "nodes": nodes, "edges": out_edges}
