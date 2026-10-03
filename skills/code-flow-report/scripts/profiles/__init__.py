"""Stack profiles: optional, stack-specific detail on top of the stack-agnostic core.

The core extractor knows nothing about any particular framework beyond generic shapes (calls,
imports, routes, SQL, ORM classes, external boundaries). A profile adds detail for one stack and
is switched on only when the repo actually uses that stack ("routing"):

    NAME        short id, also the key in codeflow.toml's [profiles] enable/disable
    PACKAGES    top-level import names that switch it on (any one is enough)
    TITLE       {"en": ..., "ko": ...} section title in the report
    INTRO       {"en": ..., "ko": ...} one-paragraph explanation under the title
    on_call(ctx, node, resolved, chain) -> dict | None
                called for every ast.Call; return a record to keep, None to ignore.
                `ctx` is the extractor's Calls visitor (ctx.here(), ctx.const_text(node), …),
                `resolved` its (kind, target) resolution or None, `chain` the dotted call text.
    section(records, code_map) -> {"columns": {"en": [...], "ko": [...]}, "rows": [[cell, ...], ...]}
                cell = str, or {"sym": "pkg.mod:fn", "line": n} for a source link
    card_extras(records) -> {symbol: [[label, value], ...]}   (optional)
                shown on any boundary card whose symbols include that symbol
    draft_roles(records, code_map) -> [role dict, ...]         (optional)
                role cards the draft step proposes for this stack
    on_module(ctx, tree) -> [record, ...]                      (optional)
                called once per module after its calls are visited, for shapes one call cannot show
    triggers(records, code_map) -> [(symbol, trigger text), ...]   (optional)
                extra journey entry points (e.g. UI widgets), offered by `draft` and `candidates`
    SINK = False                                               (optional, default True)
                the records mark where work starts, so the draft does not treat them as a sink

To add a stack: drop a module in this package that defines those names and list it in ALL.
"""
from __future__ import annotations

from . import cloudfn, jobs, llm, ui

ALL = [llm, jobs, ui, cloudfn]


def active(imported: set[str], cfg: dict) -> list:
    """Profiles to run for this repo: detected from imports, then config enable/disable."""
    pc = cfg.get("profiles", {})
    enable, disable = set(pc.get("enable", [])), set(pc.get("disable", []))
    out = []
    for p in ALL:
        if p.NAME in disable:
            continue
        if p.NAME in enable or imported & set(p.PACKAGES):
            out.append(p)
    return out
