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
import os
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
# Value types: what a literal / builtin call produces, and what a builtin method returns.
BUILTIN_TYPES = {"str": str, "bytes": bytes, "list": list, "dict": dict, "set": set, "tuple": tuple, "frozenset": frozenset,
                 "int": int, "float": float}
BUILTIN_METHODS = {name: {m for m in dir(t) if not m.startswith("_")} for name, t in BUILTIN_TYPES.items()}
VALUE_METHOD_NAMES = set().union(*BUILTIN_METHODS.values())
_STR_TO_STR = {"capitalize", "casefold", "center", "expandtabs", "format", "format_map", "join", "ljust", "lower", "lstrip",
               "removeprefix", "removesuffix", "replace", "rjust", "rstrip", "strip", "swapcase", "title", "translate", "upper", "zfill"}
BUILTIN_RETURNS = {**{f"str.{m}": "str" for m in _STR_TO_STR}, "str.split": "list", "str.rsplit": "list", "str.splitlines": "list",
                   "str.partition": "tuple", "str.rpartition": "tuple", "str.encode": "bytes", "bytes.decode": "str",
                   "dict.copy": "dict", "list.copy": "list", "set.copy": "set", "set.union": "set", "set.intersection": "set",
                   "set.difference": "set", "frozenset.union": "frozenset"}
BUILTIN_CALL_RETURNS = {"str": "str", "repr": "str", "format": "str", "bytes": "bytes", "list": "list", "sorted": "list",
                        "dict": "dict", "set": "set", "frozenset": "frozenset", "tuple": "tuple", "int": "int", "float": "float",
                        "len": "int", "sum": None}
LITERALS = {ast.List: "list", ast.ListComp: "list", ast.Dict: "dict", ast.DictComp: "dict", ast.Set: "set", ast.SetComp: "set",
            ast.Tuple: "tuple", ast.JoinedStr: "str"}
# ORM session calls: the table is not in the call, so it is taken from the model classes the same function names
ORM_SESSION_TYPES = {"Session", "AsyncSession", "scoped_session", "sessionmaker"}
# a model class names its table in one of these (SQLAlchemy, active-record bases, document stores)
TABLE_ATTRS = {"__tablename__", "table_name", "_table_name", "__table_name__", "collection_name", "__collection__", "_table"}
# methods on a model class or instance that touch its table: notebook.save(), Note.get(id), Model.objects.filter(...)
ACTIVE_RECORD_OPS = {"save": "insert", "create": "insert", "insert": "insert", "bulk_create": "insert", "update": "update",
                     "upsert": "update", "update_or_create": "update", "get_or_create": "insert", "delete": "delete",
                     "remove": "delete", "get": "read", "get_all": "read", "all": "read", "filter": "read", "find": "read",
                     "first": "read", "exclude": "read", "count": "read", "exists": "read", "search": "read", "values": "read"}
ORM_SESSION_OPS = {"add": "insert", "add_all": "insert", "merge": "update", "delete": "delete", "bulk_save_objects": "insert",
                   "bulk_insert_mappings": "insert", "bulk_update_mappings": "update",
                   "exec": "read", "execute": "read", "get": "read", "query": "read", "scalars": "read", "scalar": "read"}
YIELDING = {"Iterator", "Generator", "AsyncIterator", "AsyncGenerator", "ContextManager", "AbstractContextManager",
            "AsyncContextManager", "AbstractAsyncContextManager"}

SQL_SHAPE = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WITH)\b", re.IGNORECASE)
SQL_WRITE = {
    "insert": re.compile(r"\bINSERT\s+INTO\s+([A-Za-z_][\w.]*)", re.IGNORECASE),
    "update": re.compile(r"\bUPDATE\s+([A-Za-z_][\w.]*)\s+(?:AS\s+\w+\s+|\w+\s+)?SET\b", re.IGNORECASE),
    "delete": re.compile(r"\bDELETE\s+FROM\s+([A-Za-z_][\w.]*)", re.IGNORECASE),
}
SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
CREATE_RE = re.compile(
    r"^\s*(?:CREATE\s+(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?(?:TABLE(?:\s+IF\s+NOT\s+EXISTS)?|(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW(?:\s+IF\s+NOT\s+EXISTS)?)"
    r"|DEFINE\s+TABLE(?:\s+(?:IF\s+NOT\s+EXISTS|OVERWRITE))?)\s+([A-Za-z_][\w.\"]*)",  # SQL, and SurrealQL's DEFINE TABLE
    re.MULTILINE | re.IGNORECASE,
)
SCHEMA_GLOBS = ["**/*.sql", "**/*.surql", "**/*.surrealql"]


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


def exports_of(tree: ast.Module) -> list[str]:
    """A module's public API as it declares it: the names in a literal `__all__`."""
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets) and isinstance(n.value, (ast.List, ast.Tuple)):
            return [e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def console_scripts(root: Path) -> dict[str, str]:
    """`[project.scripts]` in pyproject.toml: command name → "pkg.mod:function" (an entry point with no __main__)."""
    try:
        import tomllib
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return {}
    scripts = data.get("project", {}).get("scripts", {}) or data.get("tool", {}).get("poetry", {}).get("scripts", {})
    return {k: v for k, v in sorted(scripts.items()) if isinstance(v, str)}


TEST_DIRS = ("tests", "test", "testing")


def test_callers(root: Path, cfg: dict, res: "Resolver", strip: list[str]) -> tuple[set[str], int]:
    """Internal symbols that test code calls or references. Tests are read for this only: they add no
    edges, no symbols and no numbers, but they let the report tell "only tests call this" from "nothing does"."""
    called: set[str] = set()
    files = [f for d in TEST_DIRS if (root / d).is_dir() for f in sorted((root / d).rglob("*.py")) if "__pycache__" not in f.parts]
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        mod = module_name(root, f, strip)
        imports, _ = import_table(tree, mod, res, f.name == "__init__.py")
        c = Calls(mod, f.relative_to(root).as_posix(), imports, res, set(), {}, cfg)
        try:
            c.visit(tree)
        except (KeyError, AttributeError, IndexError, TypeError):
            continue  # a test file shaped in a way the visitor does not expect: skip it, it only adds callers
        called |= {b for _, b, _ in c.calls + c.refs}
    return called, len(files)


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


def walk_files(root: Path, exclude: set[str]):
    """Every file under root, never entering an excluded or hidden folder (a .venv or node_modules can hold
    hundreds of thousands of files: `root.glob("**/…")` walks them all before filtering)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude and not d.startswith("."))
        for name in sorted(filenames):
            yield Path(dirpath, name)


def known_tables(root: Path, cfg: dict) -> set[str]:
    names = set()
    exclude = set(cfg["scan"].get("exclude", DEFAULT_EXCLUDE)) - {"migrations"}
    globs = cfg["scan"].get("schema_globs", SCHEMA_GLOBS)
    for f in walk_files(root, exclude | {"node_modules", "site-packages"}):
        rel = f.relative_to(root).as_posix()
        if not any(fnmatch.fnmatch(rel, g) or (g.startswith("**/") and fnmatch.fnmatch(rel, g[3:])) for g in globs):
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
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and t.id in TABLE_ATTRS for t in targets) and getattr(stmt, "value", None) is not None:
                table = literal_str(stmt.value) or table  # __tablename__, or an active-record `table_name: ClassVar[str] = "note"`
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
        self.return_types: dict[str, tuple[str, str]] = {}                  # function key → type of what it returns
        self.inferred_params: dict[str, dict[str, tuple[str, str]]] = {}    # function key → param → type seen at every call site
        self.gateways: dict[str, set[str]] = {}
        self.binds: dict[str, list[str]] = {}
        self.models: dict[str, str] = {}  # class key → table, for active-record calls  # "pkg.mod:Class.field" → functions passed for that Callable field at construction  # profile name → the repo's own functions that wrap that stack (e.g. an LLM client)
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

    def base_keys(self, class_key: str):
        """The internal classes a class inherits from (same module, or imported by name)."""
        mod = class_key.split(":", 1)[0]
        for base in self.symbols.get(class_key, {}).get("bases", []):
            head, _, rest = base.partition(".")
            local = f"{mod}:{base}"
            if local in self.symbols and self.symbols[local]["kind"] == "class":
                yield local
                continue
            kind, target = self.all_imports.get(mod, {}).get(head, (None, None))
            if kind == "symbol" and not rest and self.symbols.get(target, {}).get("kind") == "class":
                yield target
            elif kind == "module" and rest and self.symbols.get(f"{target}:{rest}", {}).get("kind") == "class":
                yield f"{target}:{rest}"

    def attr_type(self, class_key: str, attr: str, depth: int = 0):
        """The type of `self.attr` as the class or one of its bases sets it (CodeAgent inherits self.model: Model)."""
        t = self.class_attr_types.get(class_key, {}).get(attr)
        if t or depth > 6:
            return t
        for b in self.base_keys(class_key):
            t = self.attr_type(b, attr, depth + 1)
            if t:
                return t
        return None

    def method_of_bases(self, class_key: str, method: str):
        """`super().method` — look in the bases only (an external base resolves to the library)."""
        sym = self.symbols.get(class_key)
        if not sym:
            return None
        mod = class_key.split(":", 1)[0]
        for base in sym.get("bases", []):
            head, _, rest = base.partition(".")
            local = f"{mod}:{base}"
            if local in self.symbols and self.symbols[local]["kind"] == "class":
                r = self.method_of(local, method)
            else:
                kind, target = self.all_imports.get(mod, {}).get(head, (None, None))
                if kind == "symbol" and not rest:
                    r = self.method_of(target, method)
                elif kind == "module" and rest:
                    r = self.method_of(f"{target}:{rest}", method)
                elif kind == "external":
                    r = ("external", f"{target}{'.' + rest if rest else ''}().{method}")
                else:
                    r = None
            if r:
                return r
        return ("builtin", f"object.{method}") if method in ("__init__", "__new__", "__init_subclass__") and not sym.get("bases") else None

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
                    if internal and internal != a.name and internal.endswith("." + a.name):
                        # `import ui_common` in app/views/x.py found as app.ui_common (the script folder is on
                        # sys.path): the local name means the mapped module, not the raw one
                        mapped = internal[: len(internal) - len(a.name)] + top
                        table[top] = ("module", mapped) if mapped in res.modules else ("pkg", mapped)
                    elif internal:
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
        self.orm_ops: list[list] = []
        self.binds_found: list[list] = []  # [class field, function, line]: Deps(make_llm=make_llm)
        # an unresolved `x.get_secret_value()` is AWS only in a module that imports boto3 (pydantic's SecretStr has it too)
        self.uses_aws = any(str(t).split(".")[0] in ("boto3", "botocore", "aioboto3", "aiobotocore")
                            for t in (imports.values() if isinstance(imports, dict) else imports))  # [symbol, line, op] for Session.add / delete / exec …
        self.django_routes: list[tuple[str, str]] = []
        self.unresolved_names = Counter()
        self.param_votes: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        self.unresolved_attr_calls: list[list] = []
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
        inferred = self.res.inferred_params.get(self.here(), {})
        for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            if a.arg in self.param_types:
                frame[a.arg] = ("convention", self.param_types[a.arg])
            elif a.annotation is not None and self.annotation_type(a.annotation):
                frame[a.arg] = self.annotation_type(a.annotation)
            elif a.arg in inferred:
                frame[a.arg] = inferred[a.arg]
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
            return self.res.return_types.get(target)
        if kind in ("external", "convention"):
            return (kind, target + "()")
        if kind == "builtin":
            t = BUILTIN_RETURNS.get(target) if "." in target else BUILTIN_CALL_RETURNS.get(target)
            return ("builtin", t) if t else None
        return None

    def value_type(self, node):
        """Type of any expression we can tell statically: literals, typed names, calls."""
        if isinstance(node, ast.Constant):
            return ("builtin", type(node.value).__name__) if type(node.value).__name__ in BUILTIN_TYPES else None
        for k, t in LITERALS.items():
            if isinstance(node, k):
                return ("builtin", t)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            left = self.value_type(node.left)
            if left and left[0] == "builtin" and left[1] in ("str", "list", "tuple", "bytes"):
                return left
        if isinstance(node, ast.Name):
            return self.type_of(node.id) or self.typed_import(node.id)
        if isinstance(node, ast.Call):
            return self.type_of_call(node)
        if isinstance(node, (ast.BoolOp, ast.IfExp)):
            options = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
            types = {t for t in (self.value_type(o) for o in options) if t}
            return types.pop() if len(types) == 1 else None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" and self.class_stack:
            return self.res.attr_type(f"{self.mod}:{self.class_stack[-1]}", node.attr)
        if isinstance(node, ast.Attribute):
            r = self.resolve_expr(node)  # e.g. request.form → the library object flask.request.form
            if r and r[0] in ("external", "convention"):
                return r
        return None

    def annotation_type(self, ann):
        """`Foo`, `"Foo"`, `Optional[Foo]`, `Foo | None`, `list[Foo]` (→ list), library classes."""
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                ann = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                return None
        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            parts = [x for x in (ann.left, ann.right) if not (isinstance(x, ast.Constant) and x.value is None)]
            return self.annotation_type(parts[0]) if len(parts) == 1 else None
        if isinstance(ann, ast.Subscript):
            head = (dotted(ann.value) or "").split(".")[-1]
            if head == "Optional":
                return self.annotation_type(ann.slice)
            if head in ("list", "List", "Sequence", "Iterable"):
                return ("builtin", "list")
            if head in ("dict", "Dict", "Mapping"):
                return ("builtin", "dict")
            if head == "Callable":
                return ("callable", "")  # resolved through the functions bound to it (Resolver.binds)
            if head in YIELDING:  # a @contextmanager's `Iterator[Session]`: `with f() as s` binds the Session
                first = ann.slice.elts[0] if isinstance(ann.slice, ast.Tuple) else ann.slice
                return self.annotation_type(first)
            return None
        if isinstance(ann, ast.Name) and ann.id in BUILTIN_TYPES:
            return ("builtin", ann.id)
        r = self.resolve_expr(ann)
        if r and r[0] == "internal" and self.res.symbols[r[1]]["kind"] == "class":
            return r
        if r and r[0] == "external" and r[1].split(".")[-1][:1].isupper() and r[1].split(".")[-1] not in ("Any", "Self", "TypeVar", "Protocol"):
            return ("external", r[1] + "()")
        return None

    def resolve_expr(self, node):
        if isinstance(node, ast.Name):
            return self.resolve_name(node.id)
        if isinstance(node, ast.Attribute):
            chain = dotted(node)
            if chain is None:
                if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "super"
                        and self.class_stack):
                    return self.res.method_of_bases(f"{self.mod}:{self.class_stack[-1]}", node.attr)
                t = self.value_type(node.value)
                if t and t[0] == "builtin":
                    return ("builtin", f"{t[1]}.{node.attr}") if node.attr in BUILTIN_METHODS.get(t[1], ()) else None
                if t and t[0] in ("external", "convention"):
                    return (t[0], f"{t[1]}.{node.attr}")
                if t and t[0] == "internal" and f"{t[1]}.{node.attr}" in self.res.symbols:
                    return ("internal", f"{t[1]}.{node.attr}")
                return None
            head, *rest = chain.split(".")
            if head in ("self", "cls") and self.class_stack and len(rest) >= 2:
                cls_key = f"{self.mod}:{self.class_stack[-1]}"
                typed_attr = self.res.attr_type(cls_key, rest[0])
                if typed_attr:
                    tk, tt = typed_attr
                    if tk == "internal" and len(rest) == 2:
                        return self.res.method_of(tt, rest[1])
                    if tk == "builtin" and len(rest) == 2:
                        return ("builtin", f"{tt}.{rest[1]}") if rest[1] in BUILTIN_METHODS.get(tt, ()) else None
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
                if tkind == "builtin":
                    return ("builtin", f"{ttarget}.{rest[0]}") if len(rest) == 1 and rest[0] in BUILTIN_METHODS.get(ttarget, ()) else None
                if tkind == "internal" and len(rest) == 1:
                    r = self.res.method_of(ttarget, rest[0])
                    bound = self.res.binds.get(f"{ttarget}.{rest[0]}")
                    if bound and not (r and r[0] in ("internal", "external")):
                        return ("internal", bound[0])  # deps.make_llm(...) → the function passed as make_llm
                    return r
                if tkind == "internal" and len(rest) == 2:
                    attr_t = self.res.attr_type(ttarget, rest[0])
                    if attr_t and attr_t[0] == "internal":
                        return self.res.method_of(attr_t[1], rest[1])
                    if attr_t and attr_t[0] in ("external", "convention"):
                        return (attr_t[0], f"{attr_t[1]}.{rest[1]}")
                    if attr_t and attr_t[0] == "builtin" and rest[1] in BUILTIN_METHODS.get(attr_t[1], ()):
                        return ("builtin", f"{attr_t[1]}.{rest[1]}")
                    return None
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
                if key in self.res.symbols:
                    return ("internal", key)
                if len(rest) == 1 and self.res.symbols[target]["kind"] == "class":
                    return self.res.method_of(target, rest[0])  # Note.get_all() defined on a base class
                return None
            if kind == "external":
                return ("external", ".".join([target] + rest))
            if kind == "builtin":
                return ("builtin", chain)
        return None

    # -- visits
    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            t = self.value_type(node.value)
            if t:
                self.local_types[-1][node.targets[0].id] = t
            m = self._queried_class(node.value)
            if m:
                self.local_types[-1]["orm:" + node.targets[0].id] = ("internal", m)
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
        if isinstance(node.target, ast.Name):
            t = self.annotation_type(node.annotation) or (self.value_type(node.value) if node.value is not None else None)
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

    def visit_For(self, node):
        if isinstance(node.target, ast.Name):
            it = self.value_type(node.iter)
            if it and it[0] in ("external", "convention"):
                self.local_types[-1][node.target.id] = (it[0], it[1] + "[]")   # an element of a library iterable
            elif it and it[0] == "builtin" and it[1] == "str":
                self.local_types[-1][node.target.id] = ("builtin", "str")
        self.generic_visit(node)

    visit_AsyncFor = visit_For

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

    def _queried_class(self, expr):
        """The class in `select(M)…` / `s.get(M, id)` / `s.query(M)…` inside an expression, if any."""
        for n in ast.walk(expr):
            if isinstance(n, ast.Call) and n.args and (dotted(n.func) or "").split(".")[-1] in ("select", "get", "query"):
                r = self.resolve_expr(n.args[0])
                if r and r[0] == "internal" and self.res.symbols[r[1]]["kind"] == "class":
                    return r[1]
        return None

    def _orm_target(self, node, meth):
        """The model class an ORM session call acts on, when the code says it: `s.add(M(...))`, a variable typed or
        assigned from `select(M)` / `s.get(M, …)`, or the queried class itself. None → the function's models."""
        if not node.args:
            return None
        arg = node.args[0]
        if meth in ("exec", "execute", "get", "query", "scalars", "scalar"):
            return self._queried_class(arg) if meth != "get" else self._queried_class(node)
        if isinstance(arg, ast.Name):
            for frame in reversed(self.local_types):
                if "orm:" + arg.id in frame:
                    return frame["orm:" + arg.id][1]
        t = self.value_type(arg)
        if t and t[0] == "internal" and self.res.symbols.get(t[1], {}).get("kind") == "class":
            return t[1]
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
            if isinstance(node.func, ast.Attribute) and not name.startswith("__"):
                self.unresolved_attr_calls.append([caller, name, node.lineno])
            if (isinstance(node.func, ast.Attribute) and node.func.attr in SERVICE_METHODS
                    and (not SERVICE_METHODS[node.func.attr].startswith("AWS") or self.uses_aws)):
                self.external.append({"symbol": caller, "line": node.lineno, "service": SERVICE_METHODS[node.func.attr],
                                      "call": chain or node.func.attr, "inferred": True})
        else:
            kind, target = r
            self.counts[kind] += 1
            if kind == "internal":
                if self.res.symbols[target]["kind"] == "class":
                    self.constructs.append([caller, target, node.lineno])
                    fields = self.res.class_attr_types.get(target, {})
                    for kw in node.keywords:
                        if kw.arg and fields.get(kw.arg, ("",))[0] == "callable":
                            fn = self.resolve_expr(kw.value)
                            if fn and fn[0] == "internal" and self.res.symbols[fn[1]]["kind"] in ("function", "nested", "method"):
                                self.binds_found.append([f"{target}.{kw.arg}", fn[1], node.lineno])
                self.calls.append([caller, target, node.lineno])
                self._vote(target, node)
                if isinstance(node.func, ast.Attribute):
                    owner = self.value_type(node.func.value)
                    for other in self.res.binds.get(f"{owner[1]}.{node.func.attr}", [])[1:] if owner and owner[0] == "internal" else []:
                        self.calls.append([caller, other, node.lineno])
            elif kind == "external":
                head, _, meth = target.rpartition(".")
                if meth in ORM_SESSION_OPS and head.split(".")[-1].rstrip("()") in ORM_SESSION_TYPES:
                    self.orm_ops.append([caller, node.lineno, ORM_SESSION_OPS[meth], self._orm_target(node, meth)])
                elif meth == "select" and target.split(".")[0] in ("sqlmodel", "sqlalchemy"):
                    # a query built here and run elsewhere is still this function's read
                    cls = self._queried_class(node)
                    if cls:
                        self.orm_ops.append([caller, node.lineno, "read", cls])
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
        if isinstance(node.func, ast.Attribute) and node.func.attr in ACTIVE_RECORD_OPS and self.res.models:
            recv = node.func.value.value if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "objects" else node.func.value
            owner = self.value_type(recv)
            if not (owner and owner[0] == "internal"):
                owner = self.resolve_expr(recv)
            if owner and owner[0] == "internal" and owner[1] in self.res.models:
                self.orm_ops.append([caller, node.lineno, ACTIVE_RECORD_OPS[node.func.attr], owner[1]])
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

    def _vote(self, target, node):
        """Record the argument types this call passes, for call-site parameter inference."""
        sym = self.res.symbols[target]
        if sym["kind"] == "class":
            target = f"{target}.__init__"
            sym = self.res.symbols.get(target)
            if not sym:
                return
        params = [p for p in sym.get("params", []) if not p.startswith("*")]
        if sym["kind"] == "method" and params and params[0] in ("self", "cls"):
            params = params[1:]
        for i, arg in enumerate(node.args):
            if isinstance(arg, ast.Starred) or i >= len(params):
                break
            self.param_votes[target][params[i]].append(self.value_type(arg))
        for kw in node.keywords:
            if kw.arg and kw.arg in params:
                self.param_votes[target][kw.arg].append(self.value_type(kw.value))

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
        modules[mod] = {"file": rel, "lines": len(text.splitlines()), "doc": first_paragraph(ast.get_docstring(tree)), "cli": has_main,
                        "exports": exports_of(tree)}
        strings = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                txt = string_text(n.value)
                if txt:
                    strings[n.targets[0].id] = txt
        mod_strings[mod] = strings

    # route to stack profiles by what the repo really imports (external top-level names only)
    own_tops = {m.split(".")[0] for m in modules}
    imported = set()
    for mod, tree in trees.items():
        pkgs = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                pkgs.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
                pkgs.add(n.module.split(".")[0])
        modules[mod]["packages"] = sorted(pkgs - own_tops)  # third-party and stdlib top-level names, for layer rules
        imported |= pkgs
    imported -= own_tops
    active_profiles = profile_registry.active(imported, cfg)
    profile_records: dict[str, list] = defaultdict(list)

    res = Resolver(set(modules), symbols)
    tables_by_mod = {m: import_table(trees[m], m, res, is_pkg[m]) for m in sorted(trees)}
    res.all_imports = {m: t[0] for m, t in tables_by_mod.items()}
    # `class X(Model)` names a table only when Model is the ORM's (django, peewee…), not a class of this repo
    for key in [k for k, t in models.items() if t == k.rsplit(":", 1)[-1].split(".")[-1].lower()]:
        mod = key.split(":", 1)[0]
        for b in symbols[key].get("bases", []):
            if b != "Model":
                continue
            imported = res.all_imports.get(mod, {}).get("Model", (None, None))
            if f"{mod}:Model" in symbols or (imported[0] == "symbol" and imported[1] in symbols):
                del models[key]
                break
    res.models = models
    tables = known_tables(root, cfg) | set(models.values())
    def class_key(m, cls):
        return next((k for k, sd in symbols.items() if k.startswith(m + ":") and sd["kind"] == "class" and sd["line"] == cls.lineno), None)

    def prepass():
        """Types that later calls depend on, in an order where each round can use the last."""
        for m in sorted(trees):
            probe = Calls(m, rels[m], tables_by_mod[m][0], res, tables, mod_strings[m], cfg)
            mv = {}
            for n in trees[m].body:
                if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                    t = probe.value_type(n.value)
                    if t:
                        mv[n.targets[0].id] = t
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    t = probe.annotation_type(n.annotation)
                    if t:
                        mv[n.target.id] = t
            res.module_var_types[m] = mv
            for cls in [n for n in ast.walk(trees[m]) if isinstance(n, ast.ClassDef)]:
                key = class_key(m, cls)
                if not key:
                    continue
                attrs = dict(res.class_attr_types.get(key, {}))
                for n in cls.body:  # dataclass / pydantic / annotated class fields
                    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                        t = probe.annotation_type(n.annotation)
                        if t:
                            attrs.setdefault(n.target.id, t)
                for meth in [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                    params = {a.arg: a.annotation for a in meth.args.args + meth.args.kwonlyargs if a.annotation is not None}
                    for n in ast.walk(meth):
                        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Attribute)
                                and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id == "self"):
                            v = n.value.values[0] if isinstance(n.value, ast.BoolOp) else n.value  # `http or httpx.Client()`
                            if isinstance(v, ast.Name) and v.id in params:
                                t = probe.annotation_type(params[v.id])
                                if t:
                                    attrs.setdefault(n.targets[0].attr, t)
                for n in ast.walk(cls):
                    target = value = ann = None
                    if isinstance(n, ast.Assign) and len(n.targets) == 1:
                        target, value = n.targets[0], n.value
                    elif isinstance(n, ast.AnnAssign):
                        target, value, ann = n.target, n.value, n.annotation
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        t = (probe.annotation_type(ann) if ann is not None else None) or (probe.value_type(value) if value is not None else None)
                        if t:
                            attrs.setdefault(target.attr, t)
                if attrs:
                    res.class_attr_types[key] = attrs
            # return types: the annotation, else what every `return` agrees on
            for fn in [n for n in ast.walk(trees[m]) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                key = next((k for k, sd in symbols.items() if k.startswith(m + ":") and sd["kind"] in ("function", "method", "nested")
                            and sd["line"] == fn.lineno and k.rsplit(".", 1)[-1].split(":")[-1] == fn.name), None)
                if not key or key in res.return_types:
                    continue
                t = probe.annotation_type(fn.returns) if fn.returns is not None else None
                if not t:
                    rets = [r.value for r in ast.walk(fn) if isinstance(r, ast.Return) and r.value is not None]
                    types = {probe.value_type(v) for v in rets}
                    if rets and len(types) == 1 and None not in types:
                        t = types.pop()
                if t:
                    res.return_types[key] = t

    prepass()
    prepass()  # a second round lets types found in the first flow into the second

    binds_found: list[list] = []

    def main_pass():
        profile_records.clear()  # this pass may run twice; keep only the last pass's records
        calls, refs, constructs, external, sql, gateways = [], [], [], [], [], []
        orm_ops = []
        binds_found.clear()
        templates, own_prefix, mount_prefix, django = {}, {}, {}, []
        totals, unresolved_names = Counter(), Counter()
        votes, unresolved_attr = defaultdict(lambda: defaultdict(list)), []
        for mod in sorted(trees):
            imports, imp_list = tables_by_mod[mod]
            eager = {i["target"] for i in imp_list if i["target"] != mod and not i["lazy"]}
            modules[mod]["imports"] = sorted(eager)
            modules[mod]["lazy_imports"] = sorted({i["target"] for i in imp_list if i["target"] != mod and i["lazy"]} - eager)
            c = Calls(mod, rels[mod], imports, res, tables, mod_strings[mod], cfg, active_profiles)
            c.visit(trees[mod])
            for prof in active_profiles:
                if hasattr(prof, "on_module"):
                    c.profile_records[prof.NAME] += prof.on_module(c, trees[mod])
            calls += c.calls
            refs += c.refs
            constructs += c.constructs
            external += c.external
            sql += c.sql
            orm_ops += c.orm_ops
            binds_found.extend(c.binds_found)
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
            for fk, params in c.param_votes.items():
                for pn, ts in params.items():
                    votes[fk][pn] += ts
            unresolved_attr += c.unresolved_attr_calls
            modules[mod]["call_sites"] = c.counts["call_sites"]
            modules[mod]["unresolved"] = c.counts["unresolved"]

        # ORM session calls (s.add(row), s.delete(row), s.exec(select(Model))): the call does not name the table,
        # so it is taken from the model classes the same function references or constructs
        model_refs, model_new = defaultdict(set), defaultdict(set)
        for x, y, _ in refs + constructs:
            if y in models:
                model_refs[x].add(models[y])
        for x, y, _ in constructs:
            if y in models:
                model_new[x].add(models[y])
        by_fn = defaultdict(lambda: defaultdict(set))
        first_line = {}
        for sym, line, op, cls in orm_ops:
            named = ({models[cls]} if cls in models else None) or (model_new.get(sym) if op == "insert" else None) \
                or model_refs.get(sym)
            if named:
                by_fn[sym][op] |= named
                first_line[sym] = min(first_line.get(sym, line), line)
        for sym, ops in sorted(by_fn.items()):
            sql.append({"symbol": sym, "line": first_line[sym], "via": "ORM session",
                        **{op: sorted(v) for op, v in sorted(ops.items())}})
        return (calls, refs, constructs, external, sql, gateways, templates, own_prefix, mount_prefix, django, totals,
                unresolved_names, votes, unresolved_attr)

    (calls, refs, constructs, external, sql, gateways, templates, own_prefix, mount_prefix, django, totals,
     unresolved_names, votes, unresolved_attr) = main_pass()
    # parameters that receive the same known type at every call site get that type, then one more pass
    for fk, params in votes.items():
        for pn, ts in params.items():
            if ts and None not in ts and len(set(ts)) == 1:
                res.inferred_params.setdefault(fk, {})[pn] = ts[0]
    if res.inferred_params:
        prepass()
        (calls, refs, constructs, external, sql, gateways, templates, own_prefix, mount_prefix, django, totals,
         unresolved_names, votes, unresolved_attr) = main_pass()
    # a profile can name the repo's own wrappers around its stack (an LLM client class); one more pass then
    # records every call *to* those wrappers, which is where the roles, prompts and schemas are written
    found = {p.NAME: p.find_gateways(profile_records.get(p.NAME, []), calls, symbols)
             for p in active_profiles if hasattr(p, "find_gateways")}
    binds = defaultdict(set)
    for field, fn, _ in binds_found:
        binds[field].add(fn)
    if any(found.values()) or binds:
        res.gateways = found
        res.binds = {k: sorted(v) for k, v in binds.items()}
        (calls, refs, constructs, external, sql, gateways, templates, own_prefix, mount_prefix, django, totals,
         unresolved_names, votes, unresolved_attr) = main_pass()

    # a method name defined by exactly one class in the repo: an inferred (not resolved) edge
    by_name = defaultdict(list)
    for k, sd in symbols.items():
        if sd["kind"] == "method":
            by_name[k.rsplit(".", 1)[-1]].append(k)
    inferred = sorted({(a, by_name[n][0], ln) for a, n, ln in unresolved_attr
                       if len(by_name.get(n, ())) == 1 and n not in VALUE_METHOD_NAMES and a != by_name[n][0]})
    inferred = [list(x) for x in inferred]

    def uniq(rows):
        return [list(r) for r in sorted({tuple(r) for r in rows})]

    calls, refs, constructs = uniq(calls), uniq(refs), uniq(constructs)
    call_keys = {(a, b, ln) for a, b, ln in calls}
    refs = [r for r in refs if (r[0], r[1], r[2]) not in call_keys and r[0] != r[1]]

    # top-level code that does real work (a training script, a Streamlit page) is a symbol of its own, so the graph shows
    # it and a journey can start there; a module that only defines things keeps its pseudo-caller out of the symbols
    top = Counter(a for a, b, _ in calls if a.endswith(":<module>"))
    for key, n in top.items():
        mod = key.split(":", 1)[0]
        if n >= 3 and key not in symbols and mod in modules:
            symbols[key] = {"kind": "module", "file": modules[mod]["file"], "line": 1, "end": modules[mod]["lines"],
                            "doc": modules[mod]["doc"], "params": [], "decorators": [], "async": False}

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
    test_called, test_files = test_callers(root, cfg, res, strip)
    # a method can be dead too, unless its name is called somewhere we could not resolve (obj.name(...))
    maybe_called = set(unresolved_names) | {c[1] for c in unresolved_attr}
    dead, test_only = [], []
    for key, s in sorted(symbols.items()):
        mod, qual = key.split(":", 1)
        name = qual.rsplit(".", 1)[-1]
        if s["decorators"] or name.startswith("__"):
            continue
        if s["kind"] == "method":
            cls = symbols.get(f"{mod}:{qual.rsplit('.', 1)[0]}", {})
            if name.startswith("_") or name in maybe_called or any("." in b or b[:1].isupper() and f"{mod}:{b}" not in symbols
                                                                    for b in cls.get("bases", [])):
                continue  # private, possibly called on an untyped object, or overriding a library base
        elif s["kind"] != "function":
            continue
        if incoming[key] or key in routes or qual in entry_names:
            continue
        (test_only if key in test_called else dead).append(key)

    names = defaultdict(list)
    for key, s in symbols.items():
        if s["kind"] == "function":
            names[key.split(":", 1)[1]].append(key)
    dup = {n: sorted(v) for n, v in sorted(names.items())
           if len(v) > 1 and n not in entry_names | {"parse_args", "connect", "_connect", "run"} and not n.startswith("__")}

    resolved = totals["internal"] + totals["external"] + totals["builtin"] + totals["convention"]
    relevant = totals["call_sites"] - totals["builtin"]
    value_like = sum(c for n, c in unresolved_names.items() if n in VALUE_METHOD_NAMES and n not in by_name)
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
        # of the calls that are not builtin functions or methods on builtin values, how many have a known target
        "graph_coverage": round((totals["internal"] + totals["external"] + totals["convention"]) / (relevant - value_like), 4)
        if relevant - value_like > 0 else 0,
        "inferred_edges": len(inferred), "unresolved_value_like": value_like,
        "internal_edges": len(calls), "reference_edges": len(refs), "sql_sites": len(sql),
        "gateway_sites": len(gateways), "external_sites": len(external),
        "tables": len(tables), "orm_models": len(models), "import_cycles": len(cycles),
        "lazy_import_cycles": len(lazy_cycles), "parse_errors": len(parse_errors),
        "profiles": {p.NAME: len(profile_records.get(p.NAME, [])) for p in active_profiles},
        "top_unresolved_names": [[n, c] for n, c in unresolved_names.most_common(15)],
    }
    return {
        "schema": 2,
        "scope": cfg["scan"].get("include") or ["."],
        "summary": summary,
        "tables": sorted(tables),
        "orm_models": dict(sorted(models.items())),
        "orm_uses": {t: sorted(v) for t, v in sorted(orm_uses.items())},
        "modules": dict(sorted(modules.items())),
        "symbols": dict(sorted(symbols.items())),
        "routes": dict(sorted(routes.items())),
        "calls": calls, "refs": refs, "constructs": constructs, "inferred_calls": inferred, "binds": sorted(binds_found),
        "sql": sorted(sql, key=lambda e: (e["symbol"], e["line"])),
        "gateways": sorted(gateways, key=lambda e: (e["symbol"], e["line"])),
        "external": sorted(external, key=lambda e: (e["symbol"], e["line"], e["call"])),
        "import_cycles": cycles, "lazy_import_cycles": lazy_cycles,
        "dead_candidates": dead, "test_only": test_only, "test_files": test_files, "duplicate_names": dup, "parse_errors": parse_errors,
        "profiles": {p.NAME: sorted(profile_records.get(p.NAME, []), key=lambda e: (e["symbol"], e["line"])) for p in active_profiles},
        "console_scripts": console_scripts(root),
    }


def render(data: dict) -> str:
    import json
    text = json.dumps(data, ensure_ascii=False, indent=1)
    item = r"(\"[^\"\n]*\"|-?\d+)"
    text = re.sub(r"\[\n\s+" + item + r",\n\s+" + item + r",\n\s+" + item + r"\n\s+\]", r"[\1, \2, \3]", text)
    text = re.sub(r"\[\n\s+" + item + r",\n\s+" + item + r"\n\s+\]", r"[\1, \2]", text)
    return text + "\n"
