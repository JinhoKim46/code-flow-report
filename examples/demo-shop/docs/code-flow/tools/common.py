"""Config, paths and narrative validation shared by every codeflow command."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_NAME = "codeflow.toml"
SEVERITIES = {"high", "medium", "low", "info"}
STAGES = {"born", "transform", "update", "store", "archive", "restore", "read", "delete"}
SYMBOL_KEYS = {"symbol", "symbols", "module", "modules"}
TABLE_KEYS = {"table", "tables"}

DEFAULT_CONFIG = {
    "project": {"name": "", "language": "en", "repo_url": "", "store_name": "database", "audience": ""},
    "scan": {},
    "conventions": {"param_types": {}, "returns": {}, "gateways": [], "route_prefixes": {},
                    "noisy_services": ["Template render", "AWS CDK", "Jinja"]},
}


class Paths:
    """Where everything lives for one target repo.

    `out` holds codeflow.toml, code_map.json, narrative.toml, the HTML and (once vendored) tools/.
    The config records `root`, the repo root relative to `out`, so a vendored copy of these
    scripts finds the repo without being told."""

    def __init__(self, out: Path, root: Path | None = None):
        self.out = out.resolve()
        cfg_file = self.out / CONFIG_NAME
        raw = tomllib.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        rel_root = raw.get("paths", {}).get("root")
        self.root = (root or ((self.out / rel_root) if rel_root else Path.cwd())).resolve()
        self.config_file = cfg_file
        self.config = merge(DEFAULT_CONFIG, raw)
        self.code_map = self.out / "code_map.json"
        self.narrative = self.out / "narrative.toml"
        self.html = self.out / "code-flow-report.html"
        self.tools = self.out / "tools"

    @staticmethod
    def find(start: Path | None = None) -> "Paths":
        """From inside a vendored tools/ dir, or from a repo that has docs/code-flow/."""
        here = Path(__file__).resolve().parent
        if (here.parent / CONFIG_NAME).exists():
            return Paths(here.parent)
        start = (start or Path.cwd()).resolve()
        for cand in [start / "docs" / "code-flow", start]:
            if (cand / CONFIG_NAME).exists():
                return Paths(cand)
        return Paths(start / "docs" / "code-flow", root=start)


def merge(base: dict, over: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def load_map(paths: Paths) -> dict:
    return json.loads(paths.code_map.read_text(encoding="utf-8"))


def load_narrative(paths: Paths) -> dict:
    if not paths.narrative.exists():
        return {}
    with paths.narrative.open("rb") as f:
        return tomllib.load(f)


def _walk(node, where):
    if isinstance(node, dict):
        for k, v in node.items():
            yield where, k, v
            yield from _walk(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            label = (v.get("id") or v.get("symbol") or v.get("title") or i) if isinstance(v, dict) else i
            yield from _walk(v, f"{where}[{label}]")


def narrative_problems(narrative: dict, code_map: dict) -> list[str]:
    """Everything the narrative names that the code no longer has. Empty list = consistent."""
    symbols, modules, tables = code_map["symbols"], code_map["modules"], set(code_map["tables"])
    out = []
    for where, key, value in _walk(narrative, "narrative"):
        if key in SYMBOL_KEYS:
            for v in (value if isinstance(value, list) else [value]):
                if not isinstance(v, str):
                    out.append(f"{where}.{key}: expected a string, got {v!r}")
                elif v.endswith(".*"):
                    if not any(m == v[:-2] or m.startswith(v[:-1]) for m in modules):
                        out.append(f"{where}.{key}: no module matches {v}")
                elif ":" in v:
                    if v not in symbols:
                        out.append(f"{where}.{key}: symbol not in code: {v}")
                elif v not in modules:
                    out.append(f"{where}.{key}: module not in code: {v}")
        elif key in TABLE_KEYS:
            for v in (value if isinstance(value, list) else [value]):
                if v not in tables:
                    out.append(f"{where}.{key}: table not in schema or models: {v}")
        elif key == "severity" and value not in SEVERITIES:
            out.append(f"{where}.severity: {value!r} must be one of {sorted(SEVERITIES)}")
        elif key == "stage" and value not in STAGES:
            out.append(f"{where}.stage: {value!r} must be one of {sorted(STAGES)}")
    for mod in narrative.get("module_notes", {}):
        if mod not in modules:
            out.append(f"narrative.module_notes: module not in code: {mod}")
    ids = [j.get("id") for j in narrative.get("journeys", [])]
    if len(ids) != len(set(ids)):
        out.append("journeys: duplicate id")
    return out


def count_todo(narrative) -> int:
    if isinstance(narrative, dict):
        return sum(count_todo(v) for v in narrative.values())
    if isinstance(narrative, list):
        return sum(count_todo(v) for v in narrative)
    return int(isinstance(narrative, str) and narrative.lstrip().startswith("TODO"))
