"""Containers as infrastructure: Docker Compose, Kubernetes manifests and Helm charts (standard library only).

Each service or workload becomes a resource, with the Python code it runs linked from its `command`, or from the
Dockerfile's `ENTRYPOINT`/`CMD` (and the entrypoint script those name). The wiring is what the files say:
`depends_on`, environment values that name another service (`postgresql://…@db:5432`), Ingress → Service →
workload through the selector, ConfigMap/Secret references, mounted volume claims, CronJob schedules.

YAML is read by a small reader below (block and flow collections, quoted and block scalars, anchors and merge
keys, several documents per file), not a full YAML implementation. Helm templates are rendered only as far as
`{{ .Values.x }}`, `.Release.Name`, `.Chart.Name` and `default`; control lines (`{{- if }}`, `{{ include }}`,
`toYaml`) are dropped, so a field that a template builds that way is not seen.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

COMPOSE_NAME = re.compile(r"^(?:docker-)?compose(?:[.-][\w.-]+)?\.ya?ml$")

# image name fragment → (service label, category); the first match wins, so put the specific names first
IMAGES = [
    (("pgvector", "postgis", "timescale", "postgres", "supabase/postgres"), ("PostgreSQL", "data")),
    (("mysql", "mariadb"), ("MySQL", "data")),
    (("mongo",), ("MongoDB", "data")),
    (("redis", "valkey", "dragonfly", "keydb"), ("Redis", "data")),
    (("memcached",), ("Memcached", "data")),
    (("elasticsearch", "opensearch"), ("Search", "data")),
    (("qdrant", "weaviate", "chroma", "milvus", "pinecone"), ("Vector DB", "data")),
    (("surrealdb",), ("SurrealDB", "data")),
    (("neo4j",), ("Neo4j", "data")),
    (("clickhouse",), ("ClickHouse", "data")),
    (("minio",), ("MinIO (S3)", "data")),
    (("dynamodb-local",), ("DynamoDB local", "data")),
    (("rabbitmq",), ("RabbitMQ", "messaging")),
    (("kafka", "redpanda"), ("Kafka", "messaging")),
    (("nats",), ("NATS", "messaging")),
    (("localstack",), ("LocalStack", "edge")),
    (("keycloak",), ("Keycloak", "auth")),
    (("ollama", "vllm", "text-generation-inference", "tei", "litellm"), ("Model server", "compute")),
    (("nginx", "traefik", "caddy", "haproxy", "envoy"), ("Proxy", "edge")),
    (("prometheus", "grafana", "jaeger", "otel-collector", "opentelemetry-collector", "loki", "tempo", "otel"), ("Monitoring", "edge")),
    (("mailhog", "mailpit"), ("Mail", "edge")),
]

K8S_KINDS = {
    "Deployment": ("K8s Deployment", "compute"), "StatefulSet": ("K8s StatefulSet", "compute"),
    "DaemonSet": ("K8s DaemonSet", "compute"), "Job": ("K8s Job", "compute"), "CronJob": ("K8s CronJob", "compute"),
    "Pod": ("K8s Pod", "compute"), "Service": ("K8s Service", "network"), "Ingress": ("K8s Ingress", "api"),
    "HTTPRoute": ("K8s HTTPRoute", "api"), "ConfigMap": ("K8s ConfigMap", "config"), "Secret": ("K8s Secret", "config"),
    "PersistentVolumeClaim": ("K8s volume claim", "data"),
}
ASIDE = {"examples", "example", "samples", "sample", "demo", "demos", "scripts", "docs", "test", "tests", "e2e",
         "integration", "fixtures", "release-test", "testdata", "hack", "extras", "extra", "contrib", "addons",
         "tutorials", "tutorial", "benchmarks", "benchmark", "notebooks"}
HOSTISH = re.compile(r"HOST|ADDR|URL|URI|ENDPOINT|SERVER|SERVICE|DSN|BROKER|BACKEND|UPSTREAM", re.I)
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}

# long-running processes: linked, but not journey entries (their routes and tasks already are)
SERVERS = {"uvicorn", "gunicorn", "hypercorn", "daphne", "granian", "waitress-serve", "streamlit", "chainlit",
           "gradio", "flask", "fastapi", "panel", "uwsgi", "functions-framework"}
WORKERS = {"celery", "rq", "dramatiq", "arq", "huey_consumer", "huey_consumer.py", "faust"}
WRAPPERS = {"uv", "poetry", "pipenv", "pdm", "hatch", "exec", "env", "/usr/bin/env", "opentelemetry-instrument",
            "ddtrace-run", "newrelic-admin", "run-program", "tini", "--", "dumb-init", "gosu", "su-exec", "run"}


# ---------------------------------------------------------------- YAML

class YMap(dict):
    """A mapping that remembers the line of each key."""
    lines: dict


def _strip_comment(s: str) -> str:
    q = None
    for i, c in enumerate(s):
        if q:
            if c == q:
                q = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " \t:-[{,"):
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _split_flow(s: str) -> list[str]:
    out, depth, q, cur = [], 0, None, ""
    for c in s:
        if q:
            cur += c
            if c == q:
                q = None
            continue
        if c in "\"'":
            q = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def _scalar(s: str, anchors: dict):
    s = s.strip()
    if s.startswith("*"):
        return anchors.get(s[1:].strip())
    if s.startswith("!") and " " in s:      # a tag (!!str, !Ref): keep the value
        s = s.split(" ", 1)[1].strip()
    if s.startswith("[") and s.endswith("]"):
        return [_scalar(x, anchors) for x in _split_flow(s[1:-1])]
    if s.startswith("{") and s.endswith("}"):
        m = YMap()
        m.lines = {}
        for part in _split_flow(s[1:-1]):
            k, _, v = part.partition(":")
            m[_scalar(k, anchors)] = _scalar(v, anchors) if v.strip() else None
        return m
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1].replace("\\n", "\n").replace('\\"', '"') if s[0] == '"' else s[1:-1].replace("''", "'")
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    return s


KEY = re.compile(r"""^("(?:[^"\\]|\\.)*"|'[^']*'|[^\s#'"\-\[\]{}][^#]*?|-[^\s][^#]*?)\s*:(?:\s+(.*))?$""")


def load_yaml(text: str) -> list:
    """Every document in the text, as dicts / lists / strings (numbers stay strings). Lines that cannot be read
    are skipped rather than failing the file."""
    docs, cur = [], []
    for n, raw in enumerate(text.replace("\t", "  ").splitlines(), 1):
        if re.match(r"^---(\s|$)", raw) or raw.startswith("..."):
            docs.append(cur)
            cur = []
            continue
        if raw.startswith("%"):
            continue
        cur.append((n, raw))
    docs.append(cur)
    out = []
    for lines in docs:
        try:
            val = _Doc(lines).parse()
        except (IndexError, ValueError, RecursionError):
            val = None
        if val is not None:
            out.append(val)
    return out


class _Doc:
    def __init__(self, raw_lines):
        self.raw = raw_lines
        self.anchors = {}
        self.items = []  # (indent, content, line, raw index)
        for k, (n, raw) in enumerate(raw_lines):
            content = _strip_comment(raw)
            if content.strip():
                self.items.append((len(content) - len(content.lstrip()), content.strip(), n, k))
        self.i = 0

    def parse(self):
        if not self.items:
            return None
        return self.block(self.items[0][0])

    def block(self, indent):
        if self.i >= len(self.items):
            return None
        ind, content, _, _ = self.items[self.i]
        if content == "-" or content.startswith("- "):
            return self.seq(ind)
        if KEY.match(content):
            return self.map(ind)
        self.i += 1
        return _scalar(self.flow_more(content, ind), self.anchors)

    def flow_more(self, value, ind):
        """A flow collection or a quoted string continued over several lines."""
        def open_(v):
            return (v.count("[") + v.count("{") - v.count("]") - v.count("}")) > 0 or \
                (v[:1] in "\"'" and (len(v) == 1 or not v.rstrip().endswith(v[0])))
        while value and value[0] in "[{\"'" and open_(value) and self.i < len(self.items):
            value += " " + self.items[self.i][1]
            self.i += 1
        return value

    def block_scalar(self, style, ind):
        body = []
        k = self.items[self.i - 1][3] + 1   # the raw line after `key: |`
        while k < len(self.raw):
            raw = self.raw[k][1]
            if raw.strip() and len(raw) - len(raw.lstrip()) <= ind:
                break
            body.append(raw)
            k += 1
        while self.i < len(self.items) and self.items[self.i][3] < k:
            self.i += 1
        pad = min((len(b) - len(b.lstrip()) for b in body if b.strip()), default=0)
        lines = [b[pad:] for b in body]
        return "\n".join(lines).strip("\n") if style.startswith("|") else " ".join(x.strip() for x in lines if x.strip())

    def value(self, rest, ind, child_min):
        """The value after `key:` or `- `: inline, block scalar, or a nested block on the following lines."""
        anchor = None
        if rest.startswith("&"):
            anchor, _, rest = rest.partition(" ")
            anchor, rest = anchor[1:], rest.strip()
        if rest and rest[0] in "|>" and re.fullmatch(r"[|>][-+0-9]*", rest):
            v = self.block_scalar(rest, ind)
        elif rest:
            v = _scalar(self.flow_more(rest, ind), self.anchors)
        elif self.i < len(self.items) and (self.items[self.i][0] > ind or
                                          self.items[self.i][0] == ind and child_min == ind and
                                          (self.items[self.i][1] == "-" or self.items[self.i][1].startswith("- "))):
            v = self.block(self.items[self.i][0])
        else:
            v = None
        if anchor:
            self.anchors[anchor] = v
        return v

    def map(self, ind):
        m = YMap()
        m.lines = {}
        while self.i < len(self.items):
            i_ind, content, line, _ = self.items[self.i]
            if i_ind != ind or content.startswith("- ") or content == "-":
                break
            km = KEY.match(content)
            if not km:
                self.i += 1
                continue
            key = _scalar(km.group(1), {})
            self.i += 1
            v = self.value((km.group(2) or "").strip(), ind, ind)
            if key == "<<":
                for src in (v if isinstance(v, list) else [v]):
                    if isinstance(src, dict):
                        for a, b in src.items():
                            m.setdefault(a, b)
                            m.lines.setdefault(a, line)
                continue
            m[key] = v
            m.lines[key] = line
        return m

    def seq(self, ind):
        out = []
        while self.i < len(self.items):
            i_ind, content, line, k = self.items[self.i]
            if i_ind != ind or not (content == "-" or content.startswith("- ")):
                break
            rest = content[1:].strip()
            if rest and KEY.match(rest) and not rest.startswith(("\"", "'")) or rest.startswith("&") and KEY.match(rest.partition(" ")[2]):
                anchor = None
                if rest.startswith("&"):
                    anchor, _, rest = rest.partition(" ")
                # `- key: v` opens a mapping whose keys sit two columns in
                self.items[self.i] = (ind + 2, rest, line, k)
                v = self.map(ind + 2)
                if anchor:
                    self.anchors[anchor[1:]] = v
            else:
                self.i += 1
                v = self.value(rest, ind, ind + 1)
            out.append(v)
        return out


# ---------------------------------------------------------------- Helm

def _render_helm(text: str, values: dict, chart: str) -> str:
    def lookup(path):
        v = values
        for p in path.split("."):
            if not isinstance(v, dict) or p not in v:
                return None
            v = v[p]
        return v

    def expr(e):
        e = e.strip().lstrip("-").rstrip("-").strip()
        parts = [p.strip() for p in e.split("|")]
        head, val = parts[0], None
        if head.startswith("$."):   # the root context inside a range: $.Values.x, $.Release.Name
            head = head[1:]
        m = re.match(r"^\.Values\.([\w.]+)$", head)
        if m:
            val = lookup(m.group(1))
        elif head in (".Release.Name", ".Release.Namespace"):
            val = "release"
        elif head == ".Chart.Name" or re.match(r'^include\s+"[\w.-]*(?:fullname|name)"', head) or \
                re.match(r'^template\s+"[\w.-]*(?:fullname|name)"', head):
            val = chart
        elif head.startswith('"') and head.endswith('"'):
            val = head[1:-1]
        for p in parts[1:]:
            d = re.match(r'^default\s+(".*?"|\S+)$', p)
            if d and val in (None, ""):
                val = d.group(1).strip('"')
        if isinstance(val, (dict, list)):
            return None
        if val is None and re.fullmatch(r"\$?[\w]*(\.[\w]+)+|\$\w+", head):   # a range variable: shown as <name>
            return "<" + head.split(".")[-1].lstrip("$") + ">"
        return "" if val is None else str(val)

    out = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"\{\{-?\s*(if|else|end|range|with|define|include|template|toYaml|tpl|/\*|\$|-).*?\}\}", s) or \
                re.fullmatch(r"(\{\{.*?\}\}\s*)+", s) and not re.search(r"\.Values\.[\w.]+\s*(\||\}\})", s):
            continue
        if "{{" in line:
            bad = False

            def sub(m):
                nonlocal bad
                r = expr(m.group(1))
                if r is None:
                    bad = True
                    return ""
                return r
            line = re.sub(r"\{\{(.*?)\}\}", sub, line)
            if bad and re.match(r"^\s*[\w.-]+:\s*$", line):
                continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- commands → Python

def _tokens(cmd) -> list[str]:
    if cmd is None:
        return []
    if isinstance(cmd, list):
        toks = [str(x) for x in cmd if x is not None]
    else:
        try:
            toks = shlex.split(str(cmd))
        except ValueError:
            toks = str(cmd).split()
    if len(toks) >= 3 and toks[0].split("/")[-1] in ("sh", "bash", "ash", "zsh") and toks[1] in ("-c", "-lc", "-ec"):
        return _tokens(toks[2])
    # `a && b ; exec c` → the last segment that starts something Python-ish, else the last segment
    segs, cur = [], []
    for t in toks:
        if t in ("&&", ";", "||", "&"):
            segs.append(cur)
            cur = []
        elif t.endswith(";") and len(t) > 1:
            cur.append(t[:-1])
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    segs = [s for s in segs if s]
    for s in reversed(segs):
        if _python_head(s) is not None:
            return s
    return segs[-1] if segs else []


def _python_head(toks):
    """Index of the program after wrappers (`uv run`, `exec`, `opentelemetry-instrument` …), or None."""
    k = 0
    while k < len(toks) and (toks[k] in WRAPPERS or "=" in toks[k] and not toks[k].startswith("-") or
                             k > 0 and toks[k - 1] in WRAPPERS and toks[k].startswith("-") or
                             k > 0 and toks[k].startswith("--") and toks[k - 1].startswith("--")):
        k += 1
    if k >= len(toks):
        return None
    prog = toks[k].split("/")[-1]
    if prog in SCRIPTS:
        return k
    if re.fullmatch(r"python[\d.]*", prog) or prog in SERVERS or prog in WORKERS or prog == "locust" or prog.endswith(".py") or \
            re.fullmatch(r"[A-Za-z_][\w]*(\.[A-Za-z_]\w*)+", toks[k]) and len(toks) == k + 1:
        return k
    return None


SCRIPTS: dict = {}   # console scripts of the repository being scanned (pyproject), set by scan_containers


def python_entry(cmd, env: dict | None = None):
    """What a container command runs → (kind, target, how) or None. kind: server | worker | script | function |
    console (one of the repository's own console scripts). target: "pkg.mod", "pkg.mod:attr", or a path ending in .py."""
    toks = _tokens(cmd)
    k = _python_head(toks)
    if k is None:
        return None
    toks = toks[k:]
    prog = toks[0].split("/")[-1]
    how = " ".join(toks)[:120]
    args = toks[1:]
    if prog in SCRIPTS:
        return ("console", SCRIPTS[prog], how)
    if re.fullmatch(r"python[\d.]*", prog):
        opts = [a for a in args]
        while opts and opts[0].startswith("-") and opts[0] != "-m":
            opts.pop(0)
        if opts[:1] == ["-m"] and len(opts) > 1:
            mod = opts[1]
            if mod.split(".")[0] in SERVERS | WORKERS:
                return python_entry([mod.split(".")[0], *opts[2:]], env)
            if "runserver" in opts or "manage" == mod:
                return ("server", mod, how)
            return ("script", mod, how)
        if opts and opts[0].endswith(".py"):
            return ("server" if any(a in ("runserver", "run") for a in opts[1:]) else "script", opts[0], how)
        return None
    if prog.endswith(".py"):
        return ("script", toks[0], how)
    if prog in ("streamlit", "chainlit", "panel", "fastapi"):
        f = next((a for a in args if a.endswith(".py")), None)
        return ("server", f, how) if f else None
    if prog == "gradio":
        f = next((a for a in args if a.endswith(".py")), None)
        return ("server", f, how) if f else None
    if prog == "flask":
        app = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("--app", "-A")), None) or \
            next((a.split("=", 1)[1] for a in args if a.startswith("--app=")), None) or (env or {}).get("FLASK_APP")
        return ("server", app or "app.py", how)
    if prog == "functions-framework":
        target = next((a.split("=", 1)[1] for a in args if a.startswith("--target=")), None) or \
            next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--target"), None)
        src = next((a.split("=", 1)[1] for a in args if a.startswith("--source=")), None) or "main.py"
        return ("function", f"{src}:{target}", how) if target else None
    if prog in SERVERS:
        skip_next = {"-b", "--bind", "-k", "--worker-class", "-w", "--workers", "-c", "--config", "-t", "--timeout",
                     "--host", "--port", "--log-level", "--root-path", "--app-dir", "--env-file", "--log-config",
                     "--threads", "--chdir", "--access-logfile", "--error-logfile", "--forwarded-allow-ips",
                     "--proxy-headers", "--interface", "-p", "--ws", "--http", "--lifespan", "--limit-concurrency",
                     "--keep-alive", "--timeout-keep-alive", "-e", "--name", "--graceful-timeout", "--max-requests"}
        no_value = {"--proxy-headers", "--reload", "--factory", "--preload", "--no-access-log", "--access-log"}
        i = 0
        while i < len(args):
            a = args[i]
            if a.startswith("-"):
                i += 2 if a in skip_next and a not in no_value and "=" not in a else 1
                continue
            if re.fullmatch(r"[\w.]+:[A-Za-z_][\w.]*(\(.*\))?", a):
                return ("server", a, how)
            if a.endswith(".py") or re.fullmatch(r"[A-Za-z_][\w.]*", a) and prog in ("uvicorn", "hypercorn", "granian"):
                return ("server", a, how)
            i += 1
        return None
    if prog == "locust":   # a load generator: its task methods are what runs
        f = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-f", "--locustfile")), None) or \
            next((a.split("=", 1)[1] for a in args if a.startswith("--locustfile=")), None) or "locustfile.py"
        return ("worker", f, how)
    if prog in WORKERS:
        app = next((a.split("=", 1)[1] for a in args if a.startswith(("--app=", "-A="))), None) or \
            next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-A", "--app")), None)
        if prog in ("dramatiq", "arq", "huey_consumer", "huey_consumer.py", "faust") and not app:
            app = next((a for a in args if not a.startswith("-") and a not in ("worker",)), None)
        if prog == "faust" and app is None:
            return None
        if prog == "rq" and not app:
            return ("worker", None, how)
        return ("worker", app, how) if app else None
    if re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+", toks[0]) and len(toks) == 1:
        mod, fn = toks[0].rsplit(".", 1)
        return ("function", f"{mod}:{fn}", how)   # a Lambda-style image: CMD ["pkg.module.handler"]
    return None


def supervisord_programs(cmd, base: Path | None) -> list[tuple[str, str]]:
    """`supervisord -c conf` → [(program, command)] from the conf file found under base (by its name)."""
    toks = _tokens(cmd)
    if not toks or not any(t.split("/")[-1] in ("supervisord", "supervisor") for t in toks[:3]) or base is None:
        return []
    conf = next((toks[i + 1] for i, t in enumerate(toks[:-1]) if t in ("-c", "--configuration")), "supervisord.conf")
    name = Path(conf).name
    cands = [base / conf.lstrip("/"), base / name] + sorted(base.rglob(name))[:3]
    for c in cands:
        if c.is_file():
            text = c.read_text(encoding="utf-8", errors="replace")
            out, prog = [], None
            for ln in text.splitlines():
                m = re.match(r"^\s*\[program:([^\]]+)\]", ln)
                if m:
                    prog = m.group(1).strip()
                    continue
                m = re.match(r"^\s*command\s*=\s*(.+)$", ln)
                if m and prog:
                    out.append((prog, re.sub(r"%\(\w+\)s", "x", m.group(1).strip())))
            return out
    return []


def _dockerfile_cmd(df: Path):
    """(command, workdir, env) from a Dockerfile: ENTRYPOINT + CMD as Docker joins them; an entrypoint script in
    the build context is read for the line that starts Python."""
    try:
        text = df.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, {}
    text = re.sub(r"\\\n", " ", text)
    entry = cmd = None
    workdir, env, stages, current = None, {}, {}, None
    for m in re.finditer(r"(?im)^\s*(ENTRYPOINT|CMD|WORKDIR|ENV|FROM)\s+(.+)$", text):
        word, val = m.group(1).upper(), m.group(2).strip()
        if word == "FROM":   # a new stage starts over, unless it is built FROM an earlier stage
            parts = val.split()
            src = next((x for x in parts if not x.startswith("--")), "").lower()
            entry, cmd, workdir = stages.get(src, (None, None, None))
            alias = parts[-1].lower() if len(parts) >= 3 and parts[-2].lower() == "as" else None
            if alias:
                stages[alias] = (entry, cmd, workdir)
                current = alias
            else:
                current = None
            continue
        if word == "WORKDIR":
            workdir = val
            if current:
                stages[current] = (entry, cmd, workdir)
            continue
        if word == "ENV":
            for k, v in re.findall(r'(\w+)[= ]"?([^"\s]+)"?', val):
                env[k] = v
            continue
        parsed = None
        if val.startswith("["):
            parsed = re.findall(r'"((?:[^"\\]|\\.)*)"', val)
        else:
            try:
                parsed = shlex.split(val)
            except ValueError:
                parsed = val.split()
        if word == "ENTRYPOINT":
            entry, cmd = parsed, None
        else:
            cmd = parsed
        if current:
            stages[current] = (entry, cmd, workdir)
    full = (entry or []) + (cmd or [])
    script = next((t for t in (entry or full)[:2] if t.endswith(".sh")), None)
    if script and python_entry(full, env) is None:
        cand = [df.parent / script.lstrip("./"), df.parent / Path(script).name]
        cand += list(df.parent.rglob(Path(script).name))[:3]
        for c in cand:
            if c.is_file():
                lines = [ln.strip() for ln in c.read_text(encoding="utf-8", errors="replace").splitlines()
                         if ln.strip() and not ln.strip().startswith("#")]
                for ln in reversed(lines):
                    if python_entry(ln, env):
                        return ln, workdir, env
                break
    return full or None, workdir, env


# ---------------------------------------------------------------- scan

def scan_containers(root: Path, yaml_files: list[Path], dockerfiles: list[Path], modules: dict, symbols: dict):
    """(resources, edges, languages) for Compose files, Kubernetes manifests and Helm charts under root."""
    file_of_module = {info["file"]: m for m, info in modules.items()}
    resources, edges, languages = [], [], set()
    SCRIPTS.clear()
    SCRIPTS.update(_console_scripts(root))

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    def resolve(entry, base: Path | None):
        """(kind, target) → symbol id, preferring modules under the build context."""
        kind, target, how = entry
        if not target:
            return None
        attr = None
        if ":" in target:
            target, attr = target.split(":", 1)
            attr = re.sub(r"\(.*\)$", "", attr).split(".")[0] or None
        cands = []
        if target.endswith(".py"):
            t = target.lstrip("./")
            for m, info in modules.items():
                f = info["file"]
                if f == t or f.endswith("/" + t):
                    cands.append(m)
            if not cands and "/" in t:
                name = t.rsplit("/", 1)[-1]
                cands = [m for m, info in modules.items() if info["file"].endswith("/" + name) or info["file"] == name]
        else:
            t = target.replace("/", ".")
            cands = [m for m in modules if m == t or m.endswith("." + t)]
            cands += [m for m in modules if m.endswith("." + t + ".__init__") or m == t + ".__init__"]
        if not cands:
            return None
        if base is not None and len(cands) > 1:
            b = rel(base) if base != root else ""
            inside = [m for m in cands if modules[m]["file"].startswith(b + "/" if b else "")]
            cands = inside or cands
        cands.sort(key=lambda m: (attr is not None and f"{m}:{attr}" not in symbols, len(modules[m]["file"]), m))
        mod = cands[0]
        if attr and f"{mod}:{attr}" in symbols and symbols[f"{mod}:{attr}"].get("kind") in ("function", "class", "method"):
            return f"{mod}:{attr}"
        if kind == "function" and attr and f"{mod}:{attr}" in symbols:
            return f"{mod}:{attr}"
        key = f"{mod}:<module>"
        if key not in symbols:   # a module a container runs is an entry point even when its top level is short
            info = modules[mod]
            symbols[key] = {"kind": "module", "file": info["file"], "line": 1, "end": info.get("lines", 1),
                            "doc": info.get("doc", ""), "params": [], "decorators": [], "async": False}
        return key

    def external(entry) -> bool:
        """The target lives in an installed package (vllm, lmcache), not in this repository."""
        target = (entry[1] or "").split(":")[0]
        if not target or target.endswith(".py"):
            return False
        top = target.replace("/", ".").split(".")[0]
        return not any(m == top or m.startswith(top + ".") or ("." + top + ".") in ("." + m + ".") or m.endswith("." + top)
                       for m in modules)

    def link(r: dict, cmd, base: Path | None, env: dict | None = None, dockerfile: Path | None = None,
             command_is_args: bool = False):
        """Fill handler / handler_symbol / entry on a compute resource from its command or its Dockerfile."""
        entry = python_entry(cmd, env) if cmd else None
        progs = supervisord_programs(cmd, base) if cmd and entry is None else []
        own_command = bool(cmd) and not command_is_args
        if entry is None and not progs and dockerfile is not None and not own_command:   # a command replaces the image's
            dcmd, _, denv = _dockerfile_cmd(dockerfile)
            env = {**denv, **(env or {})}
            entry = python_entry(dcmd, env) if dcmd else None
            base = dockerfile.parent if base is None else base
            progs = supervisord_programs(dcmd, base) if dcmd and entry is None else []
        if entry is None and progs:   # supervisord: each Python program becomes its own resource
            found = [(p, python_entry(c, env)) for p, c in progs]
            found = [(p, e) for p, e in found if e]
            if found:
                prog, entry = found[0]
                r["id"] = f"{r['id']}:{prog}" if len(found) > 1 else r["id"]
                r["_extra"] = [(p, e, resolve(e, base)) for p, e in found[1:]]
        if entry is None:   # not Python (a shell script, a JVM image, a database): shown, not counted as unlinked
            r["runs"] = " ".join(_tokens(cmd))[:80] if cmd else "container image"
            return
        if entry[0] != "console" and external(entry):   # `python -m vllm.entrypoints…`: shown, not counted
            r["runs"] = entry[2]
            return
        r["handler"] = entry[2]
        r["entry"] = entry[0] in ("script", "function") or entry[0] == "console" and r.get("cls") in ("k8s:Job", "k8s:CronJob")
        sym = resolve(entry, base)
        if sym:
            r["handler_symbol"] = sym

    def image_kind(image: str):
        name = (image or "").lower().rsplit("/", 1)[-1].split(":")[0].split("@")[0]
        full = (image or "").lower()
        for keys, kind in IMAGES:
            if any(k == name or name.startswith(k) or name.endswith("-" + k) or f"/{k}" in full or len(k) >= 6 and k in name
                   for k in keys):
                return kind
        return None

    def env_items(env) -> list[tuple[str, str]]:
        if isinstance(env, dict):
            return [(str(k), "" if v is None else str(v)) for k, v in env.items()]
        if isinstance(env, list):
            out = []
            for e in env:
                if isinstance(e, str):
                    k, _, v = e.partition("=")
                    out.append((k, v))
            return out
        return []

    def defaults(v: str) -> str:
        return re.sub(r"\$\{\w+:?-([^}]*)\}", r"\1", v)

    def hosts_in(key: str, value: str, names: dict) -> list:
        """Services an environment value points at: `redis://cache:6379`, `db:5432`, or a bare `postgres` when the
        variable is named like a host (DB_HOST, API_ADDR) — `POSTGRES_DB=accounts-db` is a database name."""
        value = defaults(value)
        out = []
        for name, idx in names.items():
            pat = r"(?:^|[/@=,\s])" + re.escape(name) + r"(?:\.[\w-]+)*(?=$|[:/,\s?])"
            m = re.search(pat, value)
            if not m:
                continue
            bare = value.strip() == name or re.fullmatch(re.escape(name) + r"(\.[\w-]+)*", value.strip())
            if bare and not HOSTISH.search(key):
                continue
            out.append(idx)
        return out

    def edge(a, b, kind, label, f, line):
        if a is not None and b is not None and a != b:
            e = {"from": a, "to": b, "kind": kind, "label": label, "file": f, "line": line}
            if e not in edges:
                edges.append(e)

    dockerfile_dirs = {}
    for df in dockerfiles:
        dockerfile_dirs.setdefault(df.parent.name.lower(), []).append(df)

    # ---------------- Compose
    compose = [f for f in yaml_files if COMPOSE_NAME.match(f.name)]
    main = [f for f in compose if not set(rel(f).lower().split("/")[:-1]) & ASIDE]
    compose = main or compose   # examples/, scripts/, docs/ … repeat the main stack; read them only when alone
    compose.sort(key=lambda f: (len(rel(f).split("/")), "override" in f.name, len(f.name), rel(f)))
    by_service, pending = {}, []
    for f in compose:
        try:
            docs = load_yaml(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        doc = docs[0] if docs else None
        services = doc.get("services") if isinstance(doc, dict) else None
        if not isinstance(services, dict):
            continue
        languages.add("Docker Compose")
        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            key = (f.parent, name)
            line = services.lines.get(name, 1) if hasattr(services, "lines") else 1
            if key in by_service:   # an override file: fill what the base left out
                base_svc = by_service[key][1]
                for k, v in svc.items():
                    if k not in base_svc or k in ("command", "entrypoint"):
                        base_svc[k] = v
                continue
            by_service[key] = (f, dict(svc), line)
            pending.append(key)
    names_by_dir = {}
    repeated = {n for n in {k[1] for k in pending} if sum(k[1] == n for k in pending) > 1}
    for key in pending:
        f, svc, line = by_service[key]
        name = key[1]
        shown = f"{f.parent.name}/{name}" if name in repeated and f.parent != root else name
        image = str(svc.get("image") or "")
        build = svc.get("build")
        ctx = dockerfile = None
        if build is not None:
            ctx_s = build if isinstance(build, str) else str((build or {}).get("context") or ".")
            ctx = Path(os.path.normpath(f.parent / ctx_s))
            df_name = (build or {}).get("dockerfile") if isinstance(build, dict) else None
            dockerfile = ctx / (df_name or "Dockerfile")
            if not dockerfile.is_file():
                dockerfile = Path(os.path.normpath(f.parent / df_name)) if df_name else None
                if dockerfile is not None and not dockerfile.is_file():
                    dockerfile = None
        kind = image_kind(image) if build is None else None
        if build is None and kind is None:   # a prebuilt image of this very repository (`org/<repo>:tag`)
            dockerfile = _own_image(image, root, dockerfile_dirs)
            here = f.parent / "Dockerfile"   # `image: scribe-web` beside web/Dockerfile: built from this folder
            if dockerfile is None and here.is_file() and f.parent != root and _norm(f.parent.name) in _norm(image):
                dockerfile = here
            ctx = dockerfile.parent if dockerfile is not None else None
        service, category = kind or ("Container", "compute")
        r = {"id": shown, "var": f"compose:{rel(f)}:{name}", "cls": "compose:" + (image or "build"), "service": service,
             "category": category, "file": rel(f), "line": line, "owner": None}
        if image:
            r["image"] = image
        ports = svc.get("ports") or []
        if isinstance(ports, list):
            r["ports"] = [str(p) for p in ports if p is not None][:6]
        env = dict(env_items(svc.get("environment")))
        if kind is None:
            cmd = svc.get("command")
            ep = svc.get("entrypoint")
            full = (_tokens(ep) + _tokens(cmd)) if ep and cmd else (ep or cmd)
            if build is not None or dockerfile is not None or full:
                link(r, full, ctx, env, dockerfile)
            if ctx is not None:
                r["asset"] = rel(ctx) if ctx != root else "."
        names_by_dir.setdefault(f.parent, {})[name] = len(resources)
        for alias in (svc.get("container_name"), svc.get("hostname")):
            if isinstance(alias, str) and alias and not alias.startswith("$"):
                names_by_dir[f.parent].setdefault(alias, len(resources))
        resources.append(r)
    for key in pending:
        f, svc, line = by_service[key]
        names = names_by_dir.get(f.parent, {})
        i = names[key[1]]
        r = resources[i]
        dep = svc.get("depends_on") or []
        for d in (list(dep) if isinstance(dep, (list, dict)) else []):
            edge(i, names.get(str(d)), "depends", "depends_on", r["file"], line)
        for d in (svc.get("links") or []) if isinstance(svc.get("links"), list) else []:
            edge(i, names.get(str(d).split(":")[0]), "depends", "links", r["file"], line)
        for k, v in env_items(svc.get("environment")):
            for j in hosts_in(k, v, {n: x for n, x in names.items() if x != i}):
                edge(i, j, "env", k, r["file"], line)
        if r["category"] == "compute" and r.get("ports") and "handler" in r:
            for p in r["ports"][:2]:
                p = defaults(p)
                container = p.rsplit(":", 1)[-1]
                host = p.rsplit(":", 1)[0].split(":")[-1] if ":" in p else p
                if "$" in host:
                    host = container
                edge(f"host port {host}", i, "route", f"port {host}:{container}" if "$" in p else f"port {p}", r["file"], line)

    # ---------------- Kubernetes (plain manifests and Helm templates)
    charts = {}
    for f in yaml_files:
        if f.name == "Chart.yaml":
            charts[f.parent] = f
    objects = []   # (kind, name, doc, file, line)
    k8s_files = [f for f in yaml_files if not set(rel(f).lower().split("/")[:-1]) & ASIDE] or list(yaml_files)
    # the first definition of an object stands: kustomize bases before overlays and components, shallow before deep
    k8s_files.sort(key=lambda f: (sum(d in ("overlays", "components", "patches") for d in rel(f).split("/")[:-1]),
                                  len(rel(f).split("/")), rel(f)))
    for f in k8s_files:
        if COMPOSE_NAME.match(f.name) or f.name in ("Chart.yaml", "values.yaml") or f.name.startswith("values"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "kind:" not in text or "apiVersion" not in text:
            continue
        chart = next((c for c in charts if c in f.parents and (c / "templates") in [f.parent, *f.parent.parents]), None)
        if chart is not None:
            if "{{" in text:
                vals = {}
                vf = chart / "values.yaml"
                if vf.is_file():
                    vd = load_yaml(vf.read_text(encoding="utf-8", errors="replace"))
                    vals = vd[0] if vd and isinstance(vd[0], dict) else {}
                cname = load_yaml(charts[chart].read_text(encoding="utf-8", errors="replace"))
                cname = (cname[0] or {}).get("name") if cname and isinstance(cname[0], dict) else chart.name
                text = _render_helm(text, vals, str(cname or chart.name))
            languages.add("Helm")
        elif "{{" in text:
            continue
        for doc in load_yaml(text):
            if not isinstance(doc, dict):
                continue
            items = doc.get("items") if doc.get("kind") == "List" and isinstance(doc.get("items"), list) else [doc]
            for d in items:
                if not isinstance(d, dict) or d.get("kind") not in K8S_KINDS or not isinstance(d.get("metadata"), dict):
                    continue
                name = d["metadata"].get("name")
                if not name or not isinstance(name, str):
                    continue
                kind = d["kind"]
                if kind == "Service" and "serving.knative.dev" in str(d.get("apiVersion", "")):
                    kind = "Knative"
                line = 1
                m = re.search(r"(?m)^\s*name:\s*['\"]?" + re.escape(name) + r"['\"]?\s*$", text)
                if m and chart is None:
                    line = text.count("\n", 0, m.start()) + 1
                objects.append((kind, name, d, f, line))
    seen = {}
    k8s_index = {}
    for kind, name, d, f, line in objects:
        if (kind, name) in seen:   # the same object in a base and an overlay: the first one stands
            continue
        seen[(kind, name)] = True
        languages.add("Kubernetes")
        service, category = K8S_KINDS.get(kind, ("Knative service", "compute"))
        r = {"id": name, "var": f"k8s:{kind}:{name}", "cls": "k8s:" + kind, "service": service, "category": category,
             "file": rel(f), "line": line, "owner": None}
        if kind in WORKLOADS or kind == "Knative":
            pod = _pod_spec(d, kind)
            containers = [c for c in (pod.get("containers") or []) if isinstance(c, dict)] if pod else []
            main = containers[0] if containers else {}
            image = str(main.get("image") or "")
            r["image"] = image
            ik = image_kind(image)
            if ik and not main.get("command") and not main.get("args"):
                r["service"] = f"{service} ({ik[0]})"
                r["category"] = "data" if ik[1] == "data" else category
            else:
                df = _dockerfile_for(image, dockerfile_dirs, dockerfiles)
                base_kind = image_kind(_base_image(df)) if df is not None else None
                if base_kind and base_kind[1] == "data" and not main.get("command"):   # FROM postgres, built here
                    r["service"] = f"{service} ({base_kind[0]})"
                    r["category"] = "data"
                    df = None
                env = {k: v for k, v in ((e.get("name"), e.get("value")) for e in (main.get("env") or [])
                                         if isinstance(e, dict)) if k and isinstance(v, str)}
                cmd = main.get("command")
                args = main.get("args")
                full = (_tokens(cmd) + _tokens(args)) if cmd and args else (cmd or None)
                as_args = False
                if args and not cmd and df is not None:   # args replace the image's CMD, not its ENTRYPOINT
                    ent = _entrypoint_only(df)
                    full = (ent + _tokens(args)) if ent else _tokens(args)
                    as_args = True
                base = df.parent if df is not None else None
                link(r, full, base, env, df, command_is_args=as_args)
                if df is not None:
                    r["asset"] = rel(df.parent) if df.parent != root else "."
            r["_pod"] = pod or {}
            r["_containers"] = containers
            r["_pod_labels"] = d.get("_labels") or (d.get("metadata") or {}).get("labels") or {}
            if kind == "CronJob":
                r["schedule"] = str((d.get("spec") or {}).get("schedule") or "")
        elif kind == "Service":
            r["_selector"] = ((d.get("spec") or {}).get("selector") or {})
            ports = (d.get("spec") or {}).get("ports") or []
            r["ports"] = [str(p.get("port")) for p in ports if isinstance(p, dict) and p.get("port")][:4]
        elif kind in ("Ingress", "HTTPRoute"):
            r["_spec"] = d.get("spec") or {}
        k8s_index[(kind, name)] = len(resources)
        resources.append(r)

    svc_names = {name: i for (kind, name), i in k8s_index.items() if kind in ("Service", "Knative")}
    for (kind, name), i in k8s_index.items():
        r = resources[i]
        if kind == "Service":
            sel = r.pop("_selector", {})
            labels_known = isinstance(sel, dict) and sel and all(v is not None for v in sel.values()) and \
                not ("matchLabels" in sel and not sel.get("matchLabels"))
            if not labels_known:   # a Helm selector built with `include`: pair by the words the names share
                stop = {"release", "deployment", "service", "svc", "statefulset", "", "<name>", "name"}
                mine = set(re.split(r"[^a-z0-9<>]+", name.lower())) - stop
                hits = [j for (wk, wn), j in k8s_index.items() if wk in WORKLOADS and resources[j]["file"].split("/")[0] ==
                        r["file"].split("/")[0] and mine & (set(re.split(r"[^a-z0-9<>]+", wn.lower())) - stop)]
                if len(hits) == 1:
                    edge(i, hits[0], "route", ("port " + ",".join(r["ports"])) if r.get("ports") else "by name",
                         r["file"], r["line"])
                sel = {}
            if isinstance(sel, dict) and sel:
                for (wk, wn), j in k8s_index.items():
                    if wk not in WORKLOADS:
                        continue
                    labels = resources[j].get("_pod_labels") or {}
                    if isinstance(labels, dict) and all(str(labels.get(a)) == str(b) for a, b in sel.items()):
                        edge(i, j, "route", "port " + ",".join(r.get("ports") or []) if r.get("ports") else "selector",
                             r["file"], r["line"])
        elif kind in ("Ingress", "HTTPRoute"):
            spec = r.pop("_spec", {})
            if kind == "Ingress":
                rules = spec.get("rules") or []
                default = ((spec.get("defaultBackend") or spec.get("backend") or {}).get("service") or {}).get("name")
                if default:
                    edge(i, svc_names.get(default), "route", "/ (default)", r["file"], r["line"])
                for rule in rules if isinstance(rules, list) else []:
                    if not isinstance(rule, dict):
                        continue
                    host = rule.get("host") or ""
                    for p in ((rule.get("http") or {}).get("paths") or []):
                        if not isinstance(p, dict):
                            continue
                        b = p.get("backend") or {}
                        target = (b.get("service") or {}).get("name") if isinstance(b.get("service"), dict) else b.get("serviceName")
                        edge(i, svc_names.get(str(target)), "route", f"{host}{p.get('path') or '/'}", r["file"], r["line"])
            else:
                for rule in spec.get("rules") or []:
                    if not isinstance(rule, dict):
                        continue
                    paths = [((m.get("path") or {}).get("value") or "/") for m in (rule.get("matches") or []) if isinstance(m, dict)]
                    for b in rule.get("backendRefs") or []:
                        if isinstance(b, dict):
                            edge(i, svc_names.get(str(b.get("name"))), "route", ", ".join(paths) or "/", r["file"], r["line"])
        elif kind in WORKLOADS or kind == "Knative":
            pod = r.pop("_pod", {})
            containers = r.pop("_containers", [])
            if r.get("schedule"):
                edge("Schedule", i, "trigger", r["schedule"], r["file"], r["line"])
            for c in containers:
                for e in c.get("env") or []:
                    if not isinstance(e, dict):
                        continue
                    vf = e.get("valueFrom") or {}
                    for ref_kind, key in (("ConfigMap", "configMapKeyRef"), ("Secret", "secretKeyRef")):
                        ref = vf.get(key) if isinstance(vf, dict) else None
                        if isinstance(ref, dict):
                            edge(i, k8s_index.get((ref_kind, ref.get("name"))), "env", str(e.get("name")), r["file"], r["line"])
                    if isinstance(e.get("value"), str):
                        for j in hosts_in(str(e.get("name")), e["value"], svc_names):
                            edge(i, j, "env", str(e.get("name")), r["file"], r["line"])
                for e in c.get("envFrom") or []:
                    if isinstance(e, dict):
                        for ref_kind, key in (("ConfigMap", "configMapRef"), ("Secret", "secretRef")):
                            if isinstance(e.get(key), dict):
                                edge(i, k8s_index.get((ref_kind, e[key].get("name"))), "env", "envFrom", r["file"], r["line"])
            for v in (pod.get("volumes") or []) if isinstance(pod, dict) else []:
                if not isinstance(v, dict):
                    continue
                if isinstance(v.get("persistentVolumeClaim"), dict):
                    edge(i, k8s_index.get(("PersistentVolumeClaim", v["persistentVolumeClaim"].get("claimName"))),
                         "mount", "volume", r["file"], r["line"])
                if isinstance(v.get("configMap"), dict):
                    edge(i, k8s_index.get(("ConfigMap", v["configMap"].get("name"))), "mount", "volume", r["file"], r["line"])
                if isinstance(v.get("secret"), dict):
                    edge(i, k8s_index.get(("Secret", v["secret"].get("secretName"))), "mount", "volume", r["file"], r["line"])
    for i in range(len(resources)):
        extra = resources[i].pop("_extra", None)
        for prog, entry, sym in extra or []:
            base_id = resources[i]["id"].split(":")[0]
            clone = {k: v for k, v in resources[i].items() if not k.startswith("_")}
            clone.update({"id": f"{base_id}:{prog}", "handler": entry[2], "entry": entry[0] in ("script", "function")})
            clone.pop("handler_symbol", None)
            if sym:
                clone["handler_symbol"] = sym
            j = len(resources)
            resources.append(clone)
            for e in [e for e in edges if e["from"] == i or e["to"] == i]:
                edge(j if e["from"] == i else e["from"], j if e["to"] == i else e["to"], e["kind"], e["label"], e["file"], e["line"])
    for r in resources:
        for k in ("_pod", "_containers", "_selector", "_spec", "_pod_labels", "_labels", "_extra"):
            r.pop(k, None)
    return resources, edges, languages


def _pod_spec(d: dict, kind: str) -> dict:
    spec = d.get("spec") or {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        spec = ((spec.get("jobTemplate") or {}).get("spec") or {})
    tmpl = spec.get("template") or {}
    if isinstance(tmpl, dict):
        labels = ((tmpl.get("metadata") or {}).get("labels") or {})
        d.setdefault("_labels", labels)
        return tmpl.get("spec") or {}
    return {}


def _base_image(df: Path) -> str:
    """The image the last stage of a Dockerfile starts FROM."""
    try:
        text = df.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    froms = re.findall(r"(?im)^\s*FROM\s+(?:--\S+\s+)*(\S+)", text)
    return froms[-1] if froms else ""


def _entrypoint_only(df: Path):
    try:
        text = df.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = None
    for m in re.finditer(r"(?im)^\s*ENTRYPOINT\s+(.+)$", text):
        pass
    if not m:
        return None
    val = m.group(1).strip()
    return re.findall(r'"([^"]+)"', val) if val.startswith("[") else val.split()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _own_image(image: str, root: Path, by_dir: dict) -> Path | None:
    """The Dockerfile behind an image this repository publishes: named like the repository (`org/open_notebook`
    for open-notebook) or like a folder holding a Dockerfile. Third-party images match neither."""
    name = (image or "").lower().rsplit("/", 1)[-1].split(":")[0].split("@")[0]
    if not name or "$" in name:
        return None
    hits = by_dir.get(name) or by_dir.get(name.replace("_", "-")) or by_dir.get(name.replace("-", "_"))
    if hits and len(hits) == 1:
        return hits[0]
    if _norm(name) == _norm(root.name) or _norm(name) in (_norm(root.name) + "app", _norm(root.name) + "api"):
        df = root / "Dockerfile"
        return df if df.is_file() else None
    return None


def _dockerfile_for(image: str, by_dir: dict, all_dfs: list) -> Path | None:
    """The Dockerfile that builds an image named in a manifest: one in a folder named like the image
    (`ghcr.io/org/api:1.2` → `api/Dockerfile`), else the only Dockerfile in the repository."""
    name = (image or "").lower().rsplit("/", 1)[-1].split(":")[0].split("@")[0]
    if not name:
        return all_dfs[0] if len(all_dfs) == 1 else None
    for cand in (name, name.split("-")[-1], name.removesuffix("-service"), name.removesuffix("-server")):
        hits = by_dir.get(cand)
        if hits and len(hits) == 1:
            return hits[0]
    if len(all_dfs) == 1:
        return all_dfs[0]
    # several Dockerfiles: the one whose name or start command shares a word with the image
    # (`lmstack-router` → docker/Dockerfile, ENTRYPOINT vllm-router)
    words = set(re.split(r"[^a-z0-9]+", name)) - {"", "app", "image", "docker", "latest"}
    scored = []
    for df in all_dfs:
        cmd, _, _ = _dockerfile_cmd(df)
        text = " ".join([df.name.lower(), df.parent.name.lower()] + [str(t).lower() for t in (cmd or [])[:3]])
        score = len(words & set(re.split(r"[^a-z0-9]+", text)))
        scored.append((score, len(df.name), df, tuple(cmd or [])))
    best = max((x[0] for x in scored), default=0)
    top = [x for x in scored if x[0] == best]
    if best > 0 and len({x[3] for x in top}) == 1:   # tied Dockerfiles that start the same command: same answer
        return min(top, key=lambda x: x[1])[2]
    return None


def _console_scripts(root: Path) -> dict:
    """`[project.scripts]` / `[tool.poetry.scripts]` of the repository: name → "module:function"."""
    try:
        import tomllib
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return {}
    out = {}
    for table in ((data.get("project") or {}).get("scripts") or {},
                  ((data.get("tool") or {}).get("poetry") or {}).get("scripts") or {}):
        for k, v in table.items():
            if isinstance(v, str) and ":" in v:
                out[k] = v
    return out
