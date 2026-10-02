"""Extract the structure of a Python codebase with `ast` — nothing here is written by hand.

Produces one deterministic JSON document (same source → byte-identical output) with:

* modules, functions, classes, methods (file:line, params, decorators, first docstring paragraph)
* internal imports, split into module-level and function-level ("lazy") imports
* call edges caller → callee, resolved to `package.module:qualname` where possible
* reference edges (a function passed as a value, e.g. a callback)
* object constructions (calls to internal classes)
* HTTP routes (Flask / FastAPI decorators, Django `path()`), with blueprint/router prefixes
* SQL strings and the tables they insert / update / delete / read
* ORM models (`__tablename__`, SQLAlchemy `Table(...)`, Django `models.Model`)
* "gateway" calls named in the config (a shared write/audit wrapper and its action label)
* stack profiles (scripts/profiles/): extra detail for a stack the repo actually imports, e.g. model
  calls for `llm`, task queues and schedules for `jobs` — routed by import, never assumed
* external-boundary call sites: anything that leaves the process (HTTP clients, cloud SDKs, databases,
  queues, email, file formats, subprocesses, model APIs, …), from one generic catalog

The config (`codeflow.toml`, optional) only adds repo-specific knowledge; see `load_config`.
"""
from __future__ import annotations

import ast
import builtins
import fnmatch
import re
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

try:  # package import (tests) or script import (CLI)
    from . import profiles as profile_registry
except ImportError:  # pragma: no cover
    import profiles as profile_registry

BUILTINS = set(dir(builtins))
ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "route", "api_route", "websocket", "head", "options"}
DEFAULT_EXCLUDE = ["tests", "test", "testing", ".venv", "venv", "env", ".env", "node_modules", "__pycache__",
                   "build", "dist", ".git", ".tox", ".nox", "site-packages", "migrations", "cdk.out", ".mypy_cache",
                   ".pytest_cache", ".claude", "docs"]

# dotted-prefix → service label. First match wins, so specific prefixes come first.
EXTERNAL_SERVICES = [
    ("boto3", "AWS (boto3)"), ("botocore", "AWS (boto3)"), ("aioboto3", "AWS (boto3)"),
    ("google.cloud", "Google Cloud"), ("azure", "Azure"),
    ("firebase_admin.messaging", "FCM push"), ("firebase_admin", "Firebase"),
    ("requests", "HTTP (requests)"), ("httpx", "HTTP (httpx)"), ("aiohttp", "HTTP (aiohttp)"),
    ("urllib.request", "HTTP (urllib)"), ("http.client", "HTTP (http.client)"),
    ("psycopg2", "PostgreSQL"), ("psycopg", "PostgreSQL"), ("asyncpg", "PostgreSQL"),
    ("sqlite3", "SQLite"), ("pymysql", "MySQL"), ("MySQLdb", "MySQL"),
    ("pymongo", "MongoDB"), ("motor", "MongoDB"), ("redis", "Redis"),
    ("sqlalchemy.create_engine", "SQL engine"), ("sqlalchemy", "SQLAlchemy"),
    ("celery", "Celery"), ("kombu", "Message queue"), ("pika", "RabbitMQ"), ("kafka", "Kafka"),
    ("smtplib", "SMTP email"), ("sendgrid", "SendGrid"), ("twilio", "Twilio"), ("stripe", "Stripe"),
    ("slack_sdk", "Slack"), ("telegram", "Telegram"),
    ("openai", "OpenAI API"), ("anthropic", "Anthropic API"), ("google.generativeai", "Gemini API"),
    ("google.genai", "Gemini API"), ("litellm", "LiteLLM"), ("langchain", "LangChain"), ("ollama", "Ollama"),
    ("grpc", "gRPC"), ("paramiko", "SSH"), ("ftplib", "FTP"), ("socket", "Socket"), ("websockets", "WebSocket"),
    ("elasticsearch", "Elasticsearch"), ("pyspark", "Spark"), ("torch.distributed", "Distributed (torch)"),
    ("subprocess", "Subprocess"), ("openpyxl", "Excel (openpyxl)"), ("pandas.read_", "File/DB read (pandas)"),
    ("flask.render_template", "Template render"), ("jinja2", "Jinja"), ("aws_cdk", "AWS CDK"),
]
# Method names that identify a service even when the receiver's type is unknown.
SERVICE_METHODS = {
    "put_object": "AWS S3", "get_object": "AWS S3", "head_object": "AWS S3", "delete_object": "AWS S3",
    "list_objects_v2": "AWS S3", "generate_presigned_url": "AWS S3", "generate_presigned_post": "AWS S3",
    "upload_file": "AWS S3", "download_file": "AWS S3", "upload_fileobj": "AWS S3", "download_fileobj": "AWS S3",
    "send_raw_email": "AWS SES", "send_email": "Email", "send_message": "Message send",
    "get_secret_value": "AWS Secrets Manager", "publish": "Publish (SNS/queue)",
    "send_each": "FCM push", "send_each_for_multicast": "FCM push", "sendmail": "SMTP email",
}
SQL_SHAPE = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WITH)\b", re.IGNORECASE)
SQL_WRITE = {
    "insert": re.compile(r"\bINSERT\s+INTO\s+([A-Za-z_][\w.]*)", re.IGNORECASE),
    "update": re.compile(r"\bUPDATE\s+([A-Za-z_][\w.]*)\s+(?:AS\s+\w+\s+|\w+\s+)?SET\b", re.IGNORECASE),
    "delete": re.compile(r"\bDELETE\s+FROM\s+([A-Za-z_][\w.]*)", re.IGNORECASE),
}
SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
CREATE_RE = re.compile(
    r"^\s*CREATE\s+(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?(?:TABLE(?:\s+IF\s+NOT\s+EXISTS)?|(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW(?:\s+IF\s+NOT\s+EXISTS)?)\s+([A-Za-z_][\w.\"]*)",
    re.MULTILINE | re.IGNORECASE,
)


# --------------------------------------------------------------------------- small helpers

def first_paragraph(doc: str | None, limit: int = 300) -> str:
    if not doc:
        return ""
    para = []
    for line in doc.strip().splitlines():
        line = line.strip()
        if not line:
            break
        para.append(line)
    text = " ".join(para)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def literal_str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def string_text(node) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return " ".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def short_expr(node, limit: int = 80) -> str:
    try:
        text = ast.unparse(node)
    except Exception:  # pragma: no cover - unparse handles every node ast produces
        text = type(node).__name__
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- files

def source_files(root: Path, cfg: dict) -> list[Path]:
    include = cfg["scan"].get("include") or ["."]
    exclude = set(cfg["scan"].get("exclude", DEFAULT_EXCLUDE))
    patterns = cfg["scan"].get("exclude_globs", [])
    files = set()
    for d in include:
        base = (root / d).resolve()
        if base.is_file() and base.suffix == ".py":
            files.add(base)
            continue
        for p in base.rglob("*.py"):
            rel = p.relative_to(root)
            if exclude & set(rel.parts[:-1]) or any(fnmatch.fnmatch(rel.as_posix(), g) for g in patterns):
                continue
            if rel.name.startswith("test_") or rel.name.endswith("_test.py") or rel.name == "conftest.py":
                continue
            files.add(p)
    return sorted(files)


def module_name(root: Path, path: Path, strip: list[str]) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    for s in strip:
        sp = s.strip("/").split("/")
        if parts[: len(sp)] == sp:
            parts = parts[len(sp):]
            break
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or path.stem


def known_tables(root: Path, cfg: dict) -> set[str]:
    names = set()
    exclude = set(cfg["scan"].get("exclude", DEFAULT_EXCLUDE)) - {"migrations"}
    for g in cfg["scan"].get("schema_globs", ["**/*.sql"]):
        for f in sorted(root.glob(g)):
            rel = f.relative_to(root)
            if exclude & set(rel.parts[:-1]):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
            names.update(n.replace('"', "") for n in CREATE_RE.findall(text))
    return names


# --------------------------------------------------------------------------- pass 1: definitions

class Definitions(ast.NodeVisitor):
    def __init__(self, mod: str, rel: str):
        self.mod, self.rel = mod, rel
        self.stack: list[str] = []
        self.class_stack: list[str] = []
        self.symbols: dict[str, dict] = {}
        self.models: dict[str, str] = {}  # class key → table name

    def _decorators(self, node) -> list[str]:
        out = []
        for d in node.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            out.append(dotted(target) or short_expr(target, 60))
        return out

    def visit_ClassDef(self, node):
        qual = ".".join(self.stack + [node.name])
        key = f"{self.mod}:{qual}"
        bases = [dotted(b) or short_expr(b, 60) for b in node.bases]
        self.symbols[key] = {
            "kind": "class", "file": self.rel, "line": node.lineno, "end": node.end_lineno,
            "doc": first_paragraph(ast.get_docstring(node)), "bases": bases, "decorators": self._decorators(node),
        }
        table = None
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets):
                table = literal_str(stmt.value)
            if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                for m in stmt.body:
                    if isinstance(m, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "db_table" for t in m.targets):
                        table = literal_str(m.value)
        if table is None and any(k.arg == "table" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
            table = node.name.lower()  # SQLModel: class User(UserBase, table=True)
        if table is None and any(b.endswith(("models.Model", "db.Model")) or b == "Model" for b in bases):
            table = node.name.lower()
        if table:
            self.models[key] = table
        self.stack.append(node.name)
        self.class_stack.append(qual)
        self.generic_visit(node)
        self.class_stack.pop()
        self.stack.pop()

    def _func(self, node):
        qual = ".".join(self.stack + [node.name])
        in_class = bool(self.class_stack) and self.stack and self.stack[-1] == self.class_stack[-1].split(".")[-1]
        a = node.args
        params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
        if a.vararg:
            params.append("*" + a.vararg.arg)
        if a.kwarg:
            params.append("**" + a.kwarg.arg)
        self.symbols[f"{self.mod}:{qual}"] = {
            "kind": "method" if in_class else ("nested" if self.stack else "function"),
            "file": self.rel, "line": node.lineno, "end": node.end_lineno,
            "doc": first_paragraph(ast.get_docstring(node)), "params": params,
            "decorators": self._decorators(node), "async": isinstance(node, ast.AsyncFunctionDef),
        }
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _func
    visit_AsyncFunctionDef = _func


# --------------------------------------------------------------------------- import resolution

class Resolver:
    def __init__(self, modules: set[str], symbols: dict[str, dict]):
        self.modules = modules
        self.symbols = symbols
        self.all_imports: dict[str, dict] = {}
        self.module_var_types: dict[str, dict[str, tuple[str, str]]] = {}   # mod → name → (kind, target)
        self.class_attr_types: dict[str, dict[str, tuple[str, str]]] = {}   # class key → attr → (kind, target)
        self.by_suffix: dict[str, list[str]] = defaultdict(list)
        for m in modules:
            parts = m.split(".")
            for i in range(1, len(parts)):
                self.by_suffix[".".join(parts[i:])].append(m)

    def method_of(self, class_key: str, method: str, depth: int = 0):
        """`Class.method` → where it is defined: the class itself, an internal base, or an external base."""
        key = f"{class_key}.{method}"
        if key in self.symbols:
            return ("internal", key)
        if depth > 6 or class_key not in self.symbols:
            return None
        mod = class_key.split(":", 1)[0]
        imports = self.all_imports.get(mod, {})
        for base in self.symbols[class_key].get("bases", []):
            head, _, rest = base.partition(".")
            local = f"{mod}:{base}"
            if local in self.symbols and self.symbols[local]["kind"] == "class":
                r = self.method_of(local, method, depth + 1)
                if r:
                    return r
                continue
            entry = imports.get(head)
            if not entry:
                continue
            kind, target = entry
            if kind == "symbol" and not rest and self.symbols.get(target, {}).get("kind") == "class":
                r = self.method_of(target, method, depth + 1)
                if r:
                    return r
            elif kind == "module" and rest and f"{target}:{rest}" in self.symbols:
                r = self.method_of(f"{target}:{rest}", method, depth + 1)
                if r:
                    return r
            elif kind == "external":
                return ("external", f"{target}{'.' + rest if rest else ''}().{method}")
        return None

    def internal_module(self, name: str, importer: str) -> str | None:
        """Map an imported name to a module in the scanned tree, or None.

        Tries the exact name, then the importer's ancestor packages (a script that puts its own
        directory on sys.path), then a unique suffix match (a sub-tree used as a source root)."""
        if not name:
            return None
        if name in self.modules:
            return name
        parts = importer.split(".")
        for i in range(len(parts) - 1, 0, -1):
            cand = ".".join(parts[:i] + [name])
            if cand in self.modules:
                return cand
        hits = self.by_suffix.get(name, [])
        if len(hits) == 1:
            return hits[0]
        return None

    def is_package_prefix(self, name: str) -> bool:
        return any(m.startswith(name + ".") for m in self.modules)

    def follow(self, target: str, depth: int = 0):
        """`module.name` that module re-exported from elsewhere → where it really lives."""
        mod, _, name = target.rpartition(".")
        entry = self.all_imports.get(mod, {}).get(name)
        if entry is None and name in self.module_var_types.get(mod, {}):
            return ("typed", f"{mod}.{name}")
        if entry is None or depth > 5:
            return ("unresolved", target)
        kind, tgt = entry
        if kind == "symbol":
            return ("internal", tgt)
        if kind in ("module", "external"):
            return (kind, tgt)
        if kind == "modattr":
            return self.follow(tgt, depth + 1)
        return ("unresolved", target)


def import_table(tree: ast.Module, mod: str, res: Resolver, is_pkg: bool):
    table: dict[str, tuple[str, str]] = {}
    imports: list[dict] = []
    top_level: set[int] = set()
    todo = list(tree.body)
    while todo:
        n = todo.pop()
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            top_level.add(id(n))
        elif isinstance(n, (ast.If, ast.Try, ast.With)):
            todo += n.body + getattr(n, "orelse", []) + getattr(n, "finalbody", [])
            for h in getattr(n, "handlers", []):
                todo += h.body
    for node in ast.walk(tree):
        lazy = id(node) not in top_level
        if isinstance(node, ast.Import):
            for a in node.names:
                internal = res.internal_module(a.name, mod)
                if a.asname:
                    table[a.asname] = ("module", internal) if internal else ("external", a.name)
                else:
                    top = a.name.split(".")[0]
                    if internal:
                        table[top] = ("module", top) if top in res.modules else ("pkg", top)
                    else:
                        table[top] = ("external", top)
                if internal:
                    imports.append({"target": internal, "line": node.lineno, "lazy": lazy})
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg_parts = mod.split(".") if is_pkg else mod.split(".")[:-1]
                if node.level > 1:
                    pkg_parts = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                base = ".".join(pkg_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            base_internal = res.internal_module(base, mod) if base else None
            for a in node.names:
                if a.name == "*":
                    continue
                alias = a.asname or a.name
                sub = res.internal_module(f"{base}.{a.name}" if base else a.name, mod)
                if sub and (sub.endswith("." + a.name) or sub == a.name):
                    table[alias] = ("module", sub)
                    imports.append({"target": sub, "line": node.lineno, "lazy": lazy})
                elif base_internal:
                    key = f"{base_internal}:{a.name}"
                    table[alias] = ("symbol", key) if key in res.symbols else ("modattr", f"{base_internal}.{a.name}")
                    imports.append({"target": base_internal, "line": node.lineno, "lazy": lazy})
                else:
                    table[alias] = ("external", f"{base}.{a.name}" if base else a.name)
    return table, imports


# --------------------------------------------------------------------------- pass 2: calls

class Calls(ast.NodeVisitor):
    def __init__(self, mod, rel, imports, res: Resolver, tables: set[str], mod_strings: dict[str, str], cfg: dict, profiles=()):
        self.profiles = list(profiles)
        self.profile_records: dict[str, list] = defaultdict(list)
        self.mod, self.rel, self.imports, self.res = mod, rel, imports, res
        self.tables = tables
        self.tables_lower = {t.lower(): t for t in tables}
        self.mod_strings = mod_strings
        conv = cfg.get("conventions", {})
        self.param_types = conv.get("param_types", {})
        self.returns = conv.get("returns", {})
        self.gateways = set(conv.get("gateways", []))
        self.stack: list[str] = []
        self.class_stack: list[str] = []
        self.local_types: list[dict[str, tuple[str, str]]] = [{}]
        self.calls, self.refs, self.constructs = [], [], []
        self.external, self.sql, self.gateway_calls = [], [], []
        self.templates: dict[str, set[str]] = defaultdict(set)
        self.route_prefix_hints: list[tuple[str, str]] = []
        self.django_routes: list[tuple[str, str]] = []
        self.unresolved_names = Counter()
        self.counts = Counter()
        self.docstring_nodes: set[int] = set()

    def here(self) -> str:
        return f"{self.mod}:{'.'.join(self.stack)}" if self.stack else f"{self.mod}:<module>"

    def _mark_doc(self, node):
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            self.docstring_nodes.add(id(body[0].value))

    def visit_Module(self, node):
        self._mark_doc(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._mark_doc(node)
        self.stack.append(node.name)
        self.class_stack.append(".".join(self.stack))
        for x in node.decorator_list + node.bases:
            self.visit(x)
        for x in node.body:
            self.visit(x)
        self.class_stack.pop()
        self.stack.pop()

    def _func(self, node):
        self._mark_doc(node)
        for d in node.decorator_list:
            self.visit(d)
        for dflt in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(dflt)
        self.stack.append(node.name)
        frame = {}
        for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            if a.arg in self.param_types:
                frame[a.arg] = ("convention", self.param_types[a.arg])
            elif a.annotation is not None:
                ann = self.resolve_expr(a.annotation)
                if ann and ann[0] == "internal" and self.res.symbols[ann[1]]["kind"] == "class":
                    frame[a.arg] = ann
                elif ann and ann[0] == "external" and ann[1].split(".")[-1][:1].isupper():
                    frame[a.arg] = ("external", ann[1] + "()")  # e.g. parser: argparse.ArgumentParser
        self.local_types.append(frame)
        for x in node.body:
            self.visit(x)
        self.local_types.pop()
        self.stack.pop()

    visit_FunctionDef = _func
    visit_AsyncFunctionDef = _func

    # -- name resolution
    def resolve_name(self, name: str):
        for i in range(len(self.stack), -1, -1):
            key = f"{self.mod}:{'.'.join(self.stack[:i] + [name])}"
            if key in self.res.symbols and self.res.symbols[key]["kind"] != "method":
                return ("internal", key)
        if name in self.imports:
            kind, target = self.imports[name]
            if kind == "symbol":
                return ("internal", target)
            if kind == "module":
                return ("module", target)
            if kind == "external":
                return ("external", target)
            if kind == "modattr":
                r = self.res.follow(target)
                return ("unresolved", r[1]) if r[0] == "typed" else r
        if name in BUILTINS:
            return ("builtin", name)
        return None

    def typed_import(self, name: str):
        """An imported name that is another module's module-level object of a known type."""
        entry = self.imports.get(name)
        if not entry or entry[0] != "modattr":
            return None
        r = self.res.follow(entry[1])
        if r[0] != "typed":
            return None
        m, _, n = r[1].rpartition(".")
        return self.res.module_var_types[m][n]

    def type_of(self, name: str):
        for frame in reversed(self.local_types):
            if name in frame:
                return frame[name]
        return None

    def type_of_call(self, call):
        if not isinstance(call, ast.Call):
            return None
        r = self.resolve_expr(call.func)
        if not r:
            return None
        kind, target = r
        if kind == "internal":
            if self.res.symbols[target]["kind"] == "class":
                return ("internal", target)
            if target in self.returns:
                return ("external", self.returns[target])
            return None
        if kind in ("external", "convention"):
            return (kind, target + "()")
        return None

    def resolve_expr(self, node):
        if isinstance(node, ast.Name):
            return self.resolve_name(node.id)
        if isinstance(node, ast.Attribute):
            chain = dotted(node)
            if chain is None:
                t = self.type_of_call(node.value)
                if t and t[0] in ("external", "convention"):
                    return (t[0], f"{t[1]}.{node.attr}")
                if t and t[0] == "internal" and f"{t[1]}.{node.attr}" in self.res.symbols:
                    return ("internal", f"{t[1]}.{node.attr}")
                return None
            head, *rest = chain.split(".")
            if head in ("self", "cls") and self.class_stack and len(rest) >= 2:
                cls_key = f"{self.mod}:{self.class_stack[-1]}"
                typed_attr = self.res.class_attr_types.get(cls_key, {}).get(rest[0])
                if typed_attr:
                    tk, tt = typed_attr
                    if tk == "internal" and len(rest) == 2:
                        return self.res.method_of(tt, rest[1])
                    if tk in ("external", "convention"):
                        return (tk, f"{tt}.{'.'.join(rest[1:])}")
                return None
            if head in ("self", "cls") and self.class_stack and len(rest) == 1:
                return self.res.method_of(f"{self.mod}:{self.class_stack[-1]}", rest[0])
            typed = self.type_of(head)
            if not typed:
                typed = self.typed_import(head)
            if typed:
                tkind, ttarget = typed
                if tkind == "internal" and len(rest) == 1:
                    return self.res.method_of(ttarget, rest[0])
                if tkind in ("external", "convention"):
                    return (tkind, f"{ttarget}.{'.'.join(rest)}")
            base = self.resolve_name(head)
            if base is None:
                return None
            kind, target = base
            if kind == "module" or (head in self.imports and self.imports[head][0] == "pkg"):
                mod = target if kind == "module" else self.imports[head][1]
                parts = list(rest)
                while parts:
                    nxt = self.res.internal_module(f"{mod}.{parts[0]}", self.mod)
                    if nxt and len(parts) > 1:
                        mod, parts = nxt, parts[1:]
                    else:
                        break
                key = f"{mod}:{'.'.join(parts)}"
                if key in self.res.symbols:
                    return ("internal", key)
                if len(parts) == 1:
                    r = self.res.follow(f"{mod}.{parts[0]}")
                    return ("unresolved", r[1]) if r[0] == "typed" else r
                typed_obj = self.res.module_var_types.get(mod, {}).get(parts[0])
                if typed_obj:
                    tk, tt = typed_obj
                    if tk == "internal":
                        return self.res.method_of(tt, parts[1]) if len(parts) == 2 else None
                    return (tk, f"{tt}.{'.'.join(parts[1:])}")
                return ("unresolved", f"{mod}.{'.'.join(parts)}")
            if kind == "internal":
                key = f"{target}.{'.'.join(rest)}"
                return ("internal", key) if key in self.res.symbols else None
            if kind == "external":
                return ("external", ".".join([target] + rest))
            if kind == "builtin":
                return ("builtin", chain)
        return None

    # -- visits
    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            t = self.type_of_call(node.value)
            if t:
                self.local_types[-1][node.targets[0].id] = t
            # Blueprint("x", __name__, url_prefix="/p") / APIRouter(prefix="/p")
            if isinstance(node.value, ast.Call):
                fn = dotted(node.value.func) or ""
                if fn.split(".")[-1] in ("Blueprint", "APIRouter"):
                    for kw in node.value.keywords:
                        if kw.arg in ("url_prefix", "prefix"):
                            p = self.const_text(kw.value)
                            if p is not None:
                                self.route_prefix_hints.append(("own", node.targets[0].id, p))
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name) and node.value is not None:
            t = self.type_of_call(node.value)
            if t:
                self.local_types[-1][node.target.id] = t
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if isinstance(item.optional_vars, ast.Name):
                t = self.type_of_call(item.context_expr)
                if t:
                    self.local_types[-1][item.optional_vars.id] = t
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def const_text(self, node) -> str | None:
        """A string expression built only from literals and module-level string constants."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in self.mod_strings:
            return self.mod_strings[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = self.const_text(node.left), self.const_text(node.right)
            return a + b if a is not None and b is not None else None
        if isinstance(node, ast.JoinedStr):
            out = ""
            for v in node.values:
                if isinstance(v, ast.Constant):
                    out += str(v.value)
                elif isinstance(v, ast.FormattedValue):
                    inner = self.const_text(v.value)
                    if inner is None:
                        return None
                    out += inner
            return out
        return None

    def _kw(self, node, name):
        for kw in node.keywords:
            if kw.arg == name:
                return kw.value
        return None

    def visit_Call(self, node):
        caller = self.here()
        r = self.resolve_expr(node.func)
        self.counts["call_sites"] += 1
        chain = dotted(node.func) or ""
        if r is None or r[0] == "unresolved":
            self.counts["unresolved"] += 1
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (chain or "<expr>")
            self.unresolved_names[name] += 1
            if isinstance(node.func, ast.Attribute) and node.func.attr in SERVICE_METHODS:
                self.external.append({"symbol": caller, "line": node.lineno, "service": SERVICE_METHODS[node.func.attr],
                                      "call": chain or node.func.attr, "inferred": True})
        else:
            kind, target = r
            self.counts[kind] += 1
            if kind == "internal":
                if self.res.symbols[target]["kind"] == "class":
                    self.constructs.append([caller, target, node.lineno])
                self.calls.append([caller, target, node.lineno])
            elif kind == "external":
                for prefix, service in EXTERNAL_SERVICES:
                    if target == prefix or target.startswith(prefix + ".") or target.startswith(prefix + "()"):
                        if service in ("PostgreSQL", "SQLite", "MySQL", "SQLAlchemy") and "()." in target:
                            break  # cursor/connection methods — table access is the "sql" list's job
                        entry = {"symbol": caller, "line": node.lineno, "service": service, "call": target}
                        if target.endswith(("boto3.client", "boto3.resource")) and node.args:
                            arg = literal_str(node.args[0])
                            if arg:
                                entry["service"] = f"AWS {arg}"
                        if target.endswith("render_template") and node.args:
                            tpl = literal_str(node.args[0])
                            if tpl:
                                entry["template"] = tpl
                                self.templates[caller].add(tpl)
                        self.external.append(entry)
                        break
        for prof in self.profiles:
            rec = prof.on_call(self, node, r, chain)
            if rec:
                self.profile_records[prof.NAME].append(rec)
        # templates by name (Jinja env.get_template / TemplateResponse)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("get_template", "TemplateResponse") and node.args:
            tpl = literal_str(node.args[0])
            if tpl:
                self.templates[caller].add(tpl)
        # gateway("action", payload, …)
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if fname in self.gateways and node.args:
            action = literal_str(node.args[0])
            self.gateway_calls.append({"symbol": caller, "line": node.lineno, "gateway": fname,
                                       "action": action if action is not None else "<dynamic>"})
        # app.register_blueprint(bp, url_prefix=…) / app.include_router(r, prefix=…)
        if fname in ("register_blueprint", "include_router") and node.args and isinstance(node.args[0], ast.Name):
            pv = self._kw(node, "url_prefix") or self._kw(node, "prefix")
            p = self.const_text(pv) if pv is not None else None
            if p is not None:
                self.route_prefix_hints.append(("mount", node.args[0].id, p))
        # Django path("x/", view)
        if fname in ("path", "re_path") and len(node.args) >= 2:
            p = literal_str(node.args[0])
            view = node.args[1]
            if isinstance(view, ast.Call) and isinstance(view.func, ast.Attribute) and view.func.attr == "as_view":
                view = view.func.value  # class-based view: the route belongs to the class
            vr = self.resolve_expr(view)
            if p is not None and vr and vr[0] == "internal":
                self.django_routes.append((vr[1], "/" + p.lstrip("^")))
        self.generic_visit(node)

    def _ref(self, node):
        if isinstance(getattr(node, "ctx", None), ast.Load):
            r = self.resolve_expr(node)
            if r and r[0] == "internal" and self.res.symbols[r[1]]["kind"] != "class":
                self.refs.append([self.here(), r[1], node.lineno])
            elif r and r[0] == "internal":
                self.refs.append([self.here(), r[1], node.lineno])
            elif isinstance(node, ast.Name) and node.id in self.mod_strings:
                self._sql(self.mod_strings[node.id], node.lineno, via=node.id)

    def visit_Name(self, node):
        self._ref(node)

    def visit_Attribute(self, node):
        self._ref(node)
        self.generic_visit(node)

    def _sql(self, text: str, line: int, via: str | None = None):
        if not text or not SQL_SHAPE.search(text) or not self.tables:
            return
        ops: dict[str, set[str]] = defaultdict(set)
        for op, rx in SQL_WRITE.items():
            for t in rx.findall(text):
                real = self.tables_lower.get(t.lower())
                if real:
                    ops[op].add(real)
        deleted = ops.get("delete", set())
        for t in SQL_READ.findall(text):
            real = self.tables_lower.get(t.lower())
            if real and real not in deleted:
                ops["read"].add(real)
        if ops:
            entry = {"symbol": self.here(), "line": line, **{op: sorted(v) for op, v in sorted(ops.items())}}
            if via:
                entry["via"] = via
            self.sql.append(entry)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and id(node) not in self.docstring_nodes:
            self._sql(node.value, node.lineno)

    def visit_JoinedStr(self, node):
        self._sql(string_text(node), node.lineno)
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                self.visit(v)


# --------------------------------------------------------------------------- routes

def routes_for(symbols: dict, trees: dict, prefixes: dict[str, str]) -> dict:
    out = {}
    for mod, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_VERBS
                        and isinstance(d.func.value, ast.Name)):
                    continue
                path = literal_str(d.args[0]) if d.args else None
                if path is None:
                    kwp = next((k.value for k in d.keywords if k.arg in ("rule", "path")), None)
                    path = literal_str(kwp) if kwp is not None else None
                if path is None:
                    continue
                if d.func.attr in ("route", "api_route"):
                    methods = ["GET"]
                    for kw in d.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                            methods = [(literal_str(e) or "?").upper() for e in kw.value.elts]
                else:
                    methods = ["WS" if d.func.attr == "websocket" else d.func.attr.upper()]
                key = None
                # find the qualname of this def (top-level or method)
                for k, s in symbols.items():
                    if k.startswith(mod + ":") and s["line"] == node.lineno and k.endswith(":" + node.name) or (
                            k.startswith(mod + ":") and s["line"] == node.lineno and k.endswith("." + node.name)):
                        key = k
                        break
                if key is None:
                    continue
                bp = d.func.value.id
                r = out.setdefault(key, {"blueprint": bp, "routes": set()})
                for m in methods:
                    r["routes"].add((m, path))
    for v in out.values():
        prefix = prefixes.get(v["blueprint"], "")
        v["routes"] = [list(x) for x in sorted(v["routes"])]
        v["urls"] = [[m, (prefix.rstrip("/") + "/" + p.lstrip("/")) if prefix else p] for m, p in v["routes"]]
    return out


def import_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = [0]
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in sorted(graph):
        if v not in index:
            strong(v)
    return sorted(out)


# --------------------------------------------------------------------------- assemble

def build(root: Path, cfg: dict) -> dict:
    strip = cfg["scan"].get("strip_prefixes", [])
    files = source_files(root, cfg)
    trees, rels, mod_strings, is_pkg = {}, {}, {}, {}
    symbols: dict[str, dict] = {}
    models: dict[str, str] = {}
    modules: dict[str, dict] = {}
    parse_errors = []
    for f in files:
        mod = module_name(root, f, strip)
        rel = f.relative_to(root).as_posix()
        try:
            text = f.read_text(encoding="utf-8")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # the analysed code's own SyntaxWarnings are not ours to print
                tree = ast.parse(text, filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError) as error:
            parse_errors.append([rel, f"{type(error).__name__}: {error}"[:200]])
            continue
        if mod in modules:  # two files map to one name (e.g. strip_prefixes overlap) — keep the first
            parse_errors.append([rel, f"duplicate module name {mod}"])
            continue
        trees[mod], rels[mod], is_pkg[mod] = tree, rel, f.name == "__init__.py"
        d = Definitions(mod, rel)
        d.visit(tree)
        symbols.update(d.symbols)
        models.update(d.models)
        has_main = any(isinstance(n, ast.If) and "__main__" in ast.unparse(n.test) for n in tree.body)
        modules[mod] = {"file": rel, "lines": len(text.splitlines()), "doc": first_paragraph(ast.get_docstring(tree)), "cli": has_main}
        strings = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                txt = string_text(n.value)
                if txt:
                    strings[n.targets[0].id] = txt
        mod_strings[mod] = strings

    # route to stack profiles by what the repo really imports (external top-level names only)
    imported = set()
    for tree in trees.values():
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
                imported.add(n.module.split(".")[0])
    imported -= {m.split(".")[0] for m in modules}
    active_profiles = profile_registry.active(imported, cfg)
    profile_records: dict[str, list] = defaultdict(list)

    res = Resolver(set(modules), symbols)
    tables = known_tables(root, cfg) | set(models.values())
    tables_by_mod = {m: import_table(trees[m], m, res, is_pkg[m]) for m in sorted(trees)}
    res.all_imports = {m: t[0] for m, t in tables_by_mod.items()}
    for m in sorted(trees):
        probe = Calls(m, rels[m], tables_by_mod[m][0], res, tables, mod_strings[m], cfg)
        mv = {}
        for n in trees[m].body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                t = probe.type_of_call(n.value)
                if t:
                    mv[n.targets[0].id] = t
        res.module_var_types[m] = mv
        for cls in [n for n in ast.walk(trees[m]) if isinstance(n, ast.ClassDef)]:
            key = next((k for k, sd in symbols.items() if k.startswith(m + ":") and sd["kind"] == "class" and sd["line"] == cls.lineno), None)
            if not key:
                continue
            attrs = {}
            for n in ast.walk(cls):
                if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Attribute) \
                        and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id == "self":
                    t = probe.type_of_call(n.value)
                    if t:
                        attrs.setdefault(n.targets[0].attr, t)
            if attrs:
                res.class_attr_types[key] = attrs

    calls, refs, constructs, external, sql, gateways = [], [], [], [], [], []
    templates, own_prefix, mount_prefix, django = {}, {}, {}, []
    totals, unresolved_names = Counter(), Counter()
    for mod in sorted(trees):
        imports, imp_list = tables_by_mod[mod]
        eager = {i["target"] for i in imp_list if i["target"] != mod and not i["lazy"]}
        modules[mod]["imports"] = sorted(eager)
        modules[mod]["lazy_imports"] = sorted({i["target"] for i in imp_list if i["target"] != mod and i["lazy"]} - eager)
        c = Calls(mod, rels[mod], imports, res, tables, mod_strings[mod], cfg, active_profiles)
        c.visit(trees[mod])
        calls += c.calls
        refs += c.refs
        constructs += c.constructs
        external += c.external
        sql += c.sql
        gateways += c.gateway_calls
        django += c.django_routes
        for name, recs in c.profile_records.items():
            profile_records[name] += recs
        for kind, name, p in c.route_prefix_hints:
            (own_prefix if kind == "own" else mount_prefix)[name] = p
        for k, v in c.templates.items():
            templates[k] = sorted(v)
        totals.update(c.counts)
        unresolved_names.update(c.unresolved_names)
        modules[mod]["call_sites"] = c.counts["call_sites"]
        modules[mod]["unresolved"] = c.counts["unresolved"]

    def uniq(rows):
        return [list(r) for r in sorted({tuple(r) for r in rows})]

    calls, refs, constructs = uniq(calls), uniq(refs), uniq(constructs)
    call_keys = {(a, b, ln) for a, b, ln in calls}
    refs = [r for r in refs if (r[0], r[1], r[2]) not in call_keys and r[0] != r[1]]

    # final prefix = where it is mounted + what the blueprint/router declares itself
    names = set(own_prefix) | set(mount_prefix)
    prefixes = {n: "/" + "/".join(x.strip("/") for x in (mount_prefix.get(n, ""), own_prefix.get(n, "")) if x.strip("/")) for n in names}
    prefixes.update(cfg.get("conventions", {}).get("route_prefixes", {}))
    routes = routes_for(symbols, trees, prefixes)
    for key, path in django:
        r = routes.setdefault(key, {"blueprint": "django", "routes": [], "urls": []})
        r["routes"].append(["ANY", path])
        r["urls"].append(["ANY", path])
    for key, r in routes.items():
        r["guards"] = [d for d in symbols[key]["decorators"] if d.split(".")[-1] not in ROUTE_VERBS]
        r["templates"] = templates.get(key, [])

    cycles = import_cycles({m: set(v["imports"]) for m, v in modules.items()})
    lazy_cycles = [c for c in import_cycles({m: set(v["imports"]) | set(v["lazy_imports"]) for m, v in modules.items()})
                   if c not in cycles]

    # ORM usage: functions that reference or construct a model class
    orm_uses = defaultdict(set)
    for a, b, _ in refs + constructs:
        if b in models:
            orm_uses[models[b]].add(a)

    incoming = Counter(b for _, b, _ in calls) + Counter(b for _, b, _ in refs)
    entry_names = set(cfg.get("conventions", {}).get("entry_names", ["main", "handler", "lambda_handler", "cli", "app", "create_app"]))
    dead = []
    for key, s in sorted(symbols.items()):
        mod, qual = key.split(":", 1)
        if s["kind"] != "function" or qual.startswith("__") or s["decorators"]:
            continue
        if incoming[key] or key in routes or qual in entry_names:
            continue
        dead.append(key)

    names = defaultdict(list)
    for key, s in symbols.items():
        if s["kind"] == "function":
            names[key.split(":", 1)[1]].append(key)
    dup = {n: sorted(v) for n, v in sorted(names.items())
           if len(v) > 1 and n not in entry_names | {"parse_args", "connect", "_connect", "run"} and not n.startswith("__")}

    resolved = totals["internal"] + totals["external"] + totals["builtin"] + totals["convention"]
    summary = {
        "files": len(modules), "lines": sum(m["lines"] for m in modules.values()),
        "functions": sum(1 for s in symbols.values() if s["kind"] in ("function", "nested")),
        "methods": sum(1 for s in symbols.values() if s["kind"] == "method"),
        "classes": sum(1 for s in symbols.values() if s["kind"] == "class"),
        "routes": sum(len(r["routes"]) for r in routes.values()), "route_functions": len(routes),
        "call_sites": totals["call_sites"], "resolved_internal": totals["internal"],
        "resolved_external": totals["external"], "resolved_builtin": totals["builtin"],
        "resolved_by_convention": totals["convention"], "unresolved": totals["unresolved"],
        "resolved_ratio": round(resolved / totals["call_sites"], 4) if totals["call_sites"] else 0,
        "internal_edges": len(calls), "reference_edges": len(refs), "sql_sites": len(sql),
        "gateway_sites": len(gateways), "external_sites": len(external),
        "tables": len(tables), "orm_models": len(models), "import_cycles": len(cycles),
        "lazy_import_cycles": len(lazy_cycles), "parse_errors": len(parse_errors),
        "profiles": {p.NAME: len(profile_records.get(p.NAME, [])) for p in active_profiles},
        "top_unresolved_names": [[n, c] for n, c in unresolved_names.most_common(15)],
    }
    return {
        "schema": 1,
        "scope": cfg["scan"].get("include") or ["."],
        "summary": summary,
        "tables": sorted(tables),
        "orm_models": dict(sorted(models.items())),
        "orm_uses": {t: sorted(v) for t, v in sorted(orm_uses.items())},
        "modules": dict(sorted(modules.items())),
        "symbols": dict(sorted(symbols.items())),
        "routes": dict(sorted(routes.items())),
        "calls": calls, "refs": refs, "constructs": constructs,
        "sql": sorted(sql, key=lambda e: (e["symbol"], e["line"])),
        "gateways": sorted(gateways, key=lambda e: (e["symbol"], e["line"])),
        "external": sorted(external, key=lambda e: (e["symbol"], e["line"], e["call"])),
        "import_cycles": cycles, "lazy_import_cycles": lazy_cycles,
        "dead_candidates": dead, "duplicate_names": dup, "parse_errors": parse_errors,
        "profiles": {p.NAME: sorted(profile_records.get(p.NAME, []), key=lambda e: (e["symbol"], e["line"])) for p in active_profiles},
    }


def render(data: dict) -> str:
    import json
    text = json.dumps(data, ensure_ascii=False, indent=1)
    item = r"(\"[^\"\n]*\"|-?\d+)"
    text = re.sub(r"\[\n\s+" + item + r",\n\s+" + item + r",\n\s+" + item + r"\n\s+\]", r"[\1, \2, \3]", text)
    text = re.sub(r"\[\n\s+" + item + r",\n\s+" + item + r"\n\s+\]", r"[\1, \2]", text)
    return text + "\n"
