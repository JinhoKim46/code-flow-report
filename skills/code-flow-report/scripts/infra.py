"""Infrastructure as code: AWS CDK apps in TypeScript or Python, read for what wires the Python code together.

The application code says what a handler does; the infrastructure says what runs it and what it may touch:
an API route or a queue invokes a Lambda, the Lambda runs `index.lambda_handler` from an asset folder, a
grant lets it read a table, an environment variable tells it the table's name. This module reads those
facts from CDK code — TypeScript (`new lambda.Function(this, "Id", {...})`) and Python
(`_lambda.Function(self, "Id", ...)`) share one shape — and links every Lambda to the Python function it
runs, so a journey can start at "SQS ingestionQueue → Lambda UploadHandler → handler(...)".

It is a scanner, not a TypeScript parser: comments and strings are respected and brackets are matched,
but types and control flow are not followed. What it cannot pin down it leaves as text.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# construct class name (last part) → (service, category)
CLASSES = {
    "Function": ("Lambda", "compute"), "SingletonFunction": ("Lambda", "compute"), "PythonFunction": ("Lambda", "compute"),
    "NodejsFunction": ("Lambda", "compute"), "DockerImageFunction": ("Lambda", "compute"), "Alias": ("Lambda alias", "compute"),
    "Table": ("DynamoDB", "data"), "TableV2": ("DynamoDB", "data"), "Bucket": ("S3", "data"),
    "DatabaseCluster": ("RDS / Aurora", "data"), "DatabaseInstance": ("RDS", "data"), "ServerlessCluster": ("Aurora Serverless", "data"),
    "Domain": ("OpenSearch", "data"), "CfnCollection": ("OpenSearch Serverless", "data"), "CfnIndex": ("Kendra index", "data"),
    "Queue": ("SQS", "messaging"), "Topic": ("SNS", "messaging"), "Rule": ("EventBridge rule", "messaging"),
    "EventBus": ("EventBridge bus", "messaging"), "Stream": ("Kinesis", "messaging"),
    "StateMachine": ("Step Functions", "workflow"), "LambdaInvoke": ("Step Functions task", "workflow"),
    "RestApi": ("API Gateway", "api"), "LambdaRestApi": ("API Gateway", "api"), "SpecRestApi": ("API Gateway", "api"),
    "HttpApi": ("API Gateway (HTTP)", "api"), "WebSocketApi": ("API Gateway (WebSocket)", "api"), "GraphqlApi": ("AppSync", "api"),
    "EventApi": ("AppSync Events", "api"), "UserPool": ("Cognito user pool", "auth"), "UserPoolClient": ("Cognito client", "auth"),
    "Role": ("IAM role", "security"), "JobDefinition": ("Batch job", "compute"), "EcsJobDefinition": ("Batch job", "compute"),
    "Secret": ("Secrets Manager", "config"), "StringParameter": ("SSM parameter", "config"), "Key": ("KMS key", "security"),
    "Distribution": ("CloudFront", "edge"), "OriginAccessIdentity": ("CloudFront access identity", "security"),
    "Project": ("CodeBuild project", "compute"), "Vpc": ("VPC", "network"),
    "FargateService": ("ECS Fargate", "compute"), "ApplicationLoadBalancedFargateService": ("ECS Fargate + ALB", "compute"),
    "Cluster": ("ECS cluster", "compute"), "Endpoint": ("SageMaker endpoint", "compute"), "CfnEndpoint": ("SageMaker endpoint", "compute"),
}
CONSTRUCT_BASES = ("Construct", "Stack", "NestedStack", "cdk.Stack", "cdk.NestedStack", "core.Construct", "core.Stack")
REF = r"([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)"  # a dotted reference, TypeScript optional chaining allowed
HEAD = re.compile(
    r"(?:(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*|(?:this|self)\.([A-Za-z_]\w*)\s*(?::[^=\n]+)?=\s*|\b([A-Za-z_]\w*)\s*=\s*)?"
    r"(?:new\s+)?([A-Za-z_][\w.]*)\(\s*(?:this|self|scope)\s*,\s*[\"'`]([^\"'`]+)[\"'`]")
CLASS_RE = re.compile(r"\bclass\s+(\w+)\s*(?:extends\s+([\w.]+)|\(([^)]*)\))")
WIRING = [  # (regex, kind, groups → (from, to, label))
    (re.compile(r"\b" + REF + r"\.(grant\w*)\(\s*" + REF), "grant"),
    (re.compile(r"\b" + REF + r"\.(?:addEventSource|add_event_source)\(\s*(?:new\s+)?[\w.]*?(\w+?)EventSource\(\s*" + REF), "trigger"),
    (re.compile(r"\b" + REF + r"\.(?:addEventNotification|add_event_notification)\([^,]+,\s*(?:new\s+)?[\w.]*?(?:Lambda|Sqs|Sns)Destination\(\s*" + REF), "notify"),
    (re.compile(r"\b" + REF + r"\.(?:addSubscription|add_subscription)\(\s*(?:new\s+)?[\w.]*(Lambda|Sqs)Subscription\(\s*" + REF), "subscribe"),
    (re.compile(r"\b" + REF + r"\.(?:addTarget|add_target)\(\s*(?:new\s+)?[\w.]*(LambdaFunction|SqsQueue|SfnStateMachine)\(\s*" + REF), "target"),
    (re.compile(r"\b" + REF + r"\.(?:addLambdaDataSource|add_lambda_data_source)\(\s*[\"'`]([^\"'`]+)[\"'`]\s*,\s*" + REF), "datasource"),
    (re.compile(r"\b" + REF + r"\.(?:addMethod|add_method)\(\s*[\"'`](\w+)[\"'`]\s*,\s*(?:new\s+)?[\w.]*LambdaIntegration\(\s*" + REF), "route"),
    (re.compile(r"\b" + REF + r"\.(?:addRoutes|add_routes)\(\s*\{[^}]*?path:\s*[\"'`]([^\"'`]+)[\"'`][^}]*?(?:new\s+)?[\w.]*LambdaIntegration\(\s*[\"'`][^\"'`]*[\"'`]\s*,\s*" + REF, re.S), "route"),
]
ADD_RESOURCE = re.compile(r"(?:(?:const|let|var)\s+|(?:this|self)\.)?([A-Za-z_$][\w$]*)\s*=\s*" + REF + r"\.(?:addResource|add_resource)\(\s*[\"'`]([^\"'`]+)[\"'`]")
ENV_REF = re.compile(r"[\"']?([A-Z][A-Z0-9_]+)[\"']?\s*[:=]\s*" + REF + r"\.(\w+(?:Name|Arn|Url|Endpoint|_name|_arn|_url|Id|_id))\b")
PATH_ATTRS = ("role", "grantPrincipal", "grant_principal", "currentVersion", "current_version")


def _strip_comments(text: str, python: bool) -> str:
    """Blank out comments (keeping offsets and line numbers), leaving strings alone."""
    out, i, n = list(text), 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
            i += 1
            continue
        if python and text.startswith(('"""', "'''"), i):
            quote = text[i:i + 3]
            i += 3
            continue
        if c in "\"'`":
            quote = c
            i += 1
            continue
        if python and c == "#" or not python and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if not python and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _closing(text: str, start: int) -> int:
    """Index just past the bracket that closes the one at `start` (strings respected)."""
    pairs, stack, i, quote = {"(": ")", "{": "}", "[": "]"}, [], start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in pairs:
            stack.append(pairs[c])
        elif c in ")}]":
            if not stack or stack.pop() != c:
                return i + 1
            if not stack:
                return i + 1
        i += 1
    return len(text)


def _last(ref: str) -> str:
    """A reference cleaned for resolution: `props.shared.uploadBucket?.role` → `shared.uploadBucket`."""
    parts = [p for p in ref.replace("?", "").replace("!", "").split(".") if p and p not in ("this", "self", "props", "scope")]
    while len(parts) > 1 and parts[-1] in PATH_ATTRS:
        parts.pop()
    return ".".join(parts) if parts else ref


IMPORT_TS = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"'](?:aws-cdk-lib|@aws-cdk)[^\"']*[\"']")
IMPORT_PY = re.compile(r"from\s+aws_cdk(?:\.[\w.]+)?\s+import\s+\(?([^)\n]+(?:\n[^)\n]+)*)\)?")
INSTANCE = re.compile(r"(?:(?:const|let|var)\s+|(?:this|self)\.)([A-Za-z_$][\w$]*)\s*(?::[^=;]+)?=\s*[^;=]*?\bnew\s+([A-Za-z_][\w.]*)\(\s*this\b")
ALIAS_DOTTED = re.compile(r"(?:this|self)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)\s*[;\n]")
ALIAS_ASSIGN = re.compile(r"(?:this|self)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_$][\w$]*)\s*[;\n]")
FUNC_DEF = re.compile(r"(?:function\s+([A-Za-z_$][\w$]*)|def\s+([A-Za-z_]\w*)|(?:private|public|protected)?\s*([A-Za-z_$][\w$]*))\s*\(([^()]*)\)\s*(?::\s*[\w<>\[\]. |]+)?\s*[{:]")


def _split_args(args: str) -> list[str]:
    out, depth, cur, quote = [], 0, "", None
    for c in args:
        if quote:
            cur += c
            quote = None if c == quote else quote
            continue
        if c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _prop(args: str, name: str):
    """The text of `name: value` (TypeScript) or `name=value` (Python) at the top level of an argument list."""
    m = re.search(r"(?<![\w$])" + name + r"\s*[:=]\s*", args)
    if not m:
        return None
    i = j = m.end()
    while j < len(args):
        c = args[j]
        if c in "([{":
            j = _closing(args, j)
            continue
        if c in "\"'`":
            k = j + 1
            while k < len(args) and args[k] != c:
                k += 2 if args[k] == "\\" else 1
            j = k + 1
            continue
        if c in ",)}]":
            break
        j += 1
    return args[i:j].strip()


def _asset_path(expr: str, file_dir: Path, app_root: Path) -> Path | None:
    """`lambda.Code.fromAsset(path.join(__dirname, "./functions/x"))` / `Code.from_asset("lambda")` → the folder."""
    if not expr:
        return None
    lits = re.findall(r"[\"'`]([^\"'`]+)[\"'`]", expr)
    if not lits:
        return None
    base = file_dir if ("__dirname" in expr or "__file__" in expr) else app_root
    p = base
    for lit in lits:
        p = p / lit
    return Path(os.path.normpath(p))


def scan(root: Path, cfg: dict, modules: dict, symbols: dict, exclude: set[str], walk_files) -> dict:
    files = []
    for f in walk_files(root, exclude | {"node_modules", "cdk.out", "site-packages"}):
        if f.suffix == ".ts" and not f.name.endswith(".d.ts") and "test" not in f.name.lower():
            files.append(f)
        elif f.suffix == ".py":
            files.append(f)
    sources = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f.suffix == ".ts" and ("aws-cdk-lib" in text or "@aws-cdk/" in text) or f.suffix == ".py" and "aws_cdk" in text:
            sources[f] = _strip_comments(text, f.suffix == ".py")
    if not sources:
        return {}
    app_root = next((p.parent for p in [root / "cdk.json", *root.glob("*/cdk.json")] if p.exists()), root)
    file_of_module = {info["file"]: m for m, info in modules.items()}
    resources, edges, routes, route_api = [], [], {}, {}
    construct_classes, aliases_of_file = set(), {}
    for f, text in sources.items():
        for m in CLASS_RE.finditer(text):
            base = (m.group(2) or m.group(3) or "")
            if any(b.strip() in CONSTRUCT_BASES or b.strip().endswith((".Construct", ".Stack")) for b in base.split(",")):
                construct_classes.add(m.group(1))
        al = {}
        for block in IMPORT_TS.findall(text) + IMPORT_PY.findall(text):
            for item in block.replace("\n", ",").split(","):
                m = re.match(r"\s*(\w+)\s+as\s+(\w+)", item)
                if m:
                    al[m.group(2)] = m.group(1)  # import { Function as LambdaFunction }
        aliases_of_file[f] = al
    instances, attr_alias, params, props_in, attr_dotted, class_file, props_spread = {}, {}, {}, {}, {}, {}, {}
    for f, text in sorted(sources.items()):
        rel = f.relative_to(root).as_posix()
        for m in CLASS_RE.finditer(text):
            if m.group(1) in construct_classes:
                class_file.setdefault(m.group(1), rel)
        for m in ALIAS_DOTTED.finditer(text):
            attr_dotted[(rel, m.group(1))] = _last(m.group(2))  # this.createWorkflow = createWorkflow.stateMachine
        for m in ALIAS_ASSIGN.finditer(text):
            attr_alias.setdefault((rel, m.group(2)), set()).add(m.group(1))  # this.ingestionQueue = queue
        defs = {}
        for m in FUNC_DEF.finditer(text):
            name = m.group(1) or m.group(2) or m.group(3)
            if name and name not in ("if", "for", "while", "switch", "catch", "constructor", "super", "function"):
                names_ = [re.split(r"[:=]", a)[0].strip().lstrip("*") for a in _split_args(m.group(4))]
                defs[name] = [n for n in names_ if n not in ("self", "cls")]
        for name, plist in defs.items():  # a helper's parameter means the argument it is called with in this file
            for call in re.finditer(r"(?<![\w$.])" + re.escape(name) + r"\(", text):
                if text[max(0, call.start() - 9):call.start()].strip().endswith(("function", "def")):
                    continue
                args = _split_args(text[call.end():_closing(text, call.end() - 1) - 1])
                for pname, arg in zip(plist, args):
                    if re.fullmatch(REF, arg.strip()):
                        params.setdefault((rel, pname), set()).add(_last(arg.strip()))
        classes = []  # (start, end, name) of construct classes, to say which construct owns a resource
        for m in CLASS_RE.finditer(text):
            base = (m.group(2) or m.group(3) or "")
            if any(b.strip() in CONSTRUCT_BASES or b.strip().endswith((".Construct", ".Stack")) for b in base.split(",")):
                brace = text.find("{", m.end()) if f.suffix == ".ts" else m.end()
                end = _closing(text, brace) if f.suffix == ".ts" and brace >= 0 else len(text)
                classes.append((m.start(), end, m.group(1)))
        for m in INSTANCE.finditer(text):  # `const x = enabled ? new AuroraPgVector(this, ...) : null`
            cls = aliases_of_file.get(f, {}).get(m.group(2).rsplit(".", 1)[-1], m.group(2).rsplit(".", 1)[-1])
            if cls in construct_classes:
                instances.setdefault((rel, m.group(1)), cls)
        for m in HEAD.finditer(text):
            cls_name = m.group(4).rsplit(".", 1)[-1]
            cls_name = aliases_of_file.get(f, {}).get(cls_name, cls_name)
            var = m.group(1) or m.group(2) or m.group(3) or ""
            if cls_name in construct_classes:
                if var:
                    instances[(rel, var)] = cls_name  # langchainInterface = new LangChainInterface(this, ...)
                open_paren = text.find("(", m.start(4))
                body = _split_args(text[open_paren + 1:_closing(text, open_paren) - 1])
                obj = body[2] if len(body) > 2 else ""
                here = next((c[2] for c in reversed(classes) if c[0] <= m.start() < c[1]), None)
                if obj.startswith("{") and re.search(r"(?:^|[{,])\s*\.\.\.props\b", obj):
                    props_spread.setdefault(cls_name, set()).add((rel, here))  # { ...props, x: y }: the parent's props pass through
                if obj.startswith("{"):  # TypeScript props object
                    pairs = [(k, v) for k, v in (re.match(r"\s*([A-Za-z_$][\w$]*)\s*:\s*(.+)$", a, re.S).groups()
                             for a in _split_args(obj[1:-1]) if re.match(r"\s*[A-Za-z_$][\w$]*\s*:", a))]
                    pairs += [(a.strip(), a.strip()) for a in _split_args(obj[1:-1]) if re.fullmatch(r"\s*[A-Za-z_$][\w$]*\s*", a)]
                else:  # Python keyword arguments
                    pairs = [tuple(a.split("=", 1)) for a in body[2:] if re.match(r"\s*\w+\s*=[^=]", a)]
                for k, v in pairs:
                    v = v.strip().split(" ?? ")[0].split(" or ")[0].strip()
                    if re.fullmatch(REF, v):
                        props_in.setdefault((cls_name, k.strip()), set()).add((rel, _last(v), next((c[2] for c in reversed(classes) if c[0] <= m.start() < c[1]), None)))
            if cls_name not in CLASSES:
                continue
            service, category = CLASSES[cls_name]
            open_paren = text.find("(", m.start(4))
            args = text[open_paren + 1:_closing(text, open_paren) - 1]
            owner = next((c[2] for c in reversed(classes) if c[0] <= m.start() < c[1]), None)
            r = {"id": m.group(5), "var": m.group(1) or m.group(2) or m.group(3) or "", "cls": cls_name, "service": service,
                 "category": category, "file": rel, "line": _line(text, m.start()), "owner": owner}
            if category == "compute" and service == "Lambda":
                handler = _prop(args, "handler")
                r["handler"] = (re.findall(r"[\"'`]([^\"'`]+)[\"'`]", handler or "") or [None])[0]
                if "FROM_IMAGE" in (handler or "") or cls_name == "DockerImageFunction":
                    r["handler"] = "container image"  # the handler is inside the image, not in this code
                runtime = _prop(args, "runtime") or ""
                r["runtime"] = "python" if "python" in runtime.lower() else ("node" if "node" in runtime.lower() else "")
                code = _prop(args, "entry") if cls_name == "PythonFunction" else _prop(args, "code")
                asset = _asset_path(code or "", f.parent, app_root)
                if cls_name == "PythonFunction":
                    index = (re.findall(r"[\"'`]([^\"'`]+)[\"'`]", _prop(args, "index") or "") or ["index.py"])[0]
                    r["handler"] = r["handler"] or "handler"
                    py = asset / index if asset else None
                    fn = r["handler"]
                elif r["handler"] and "." in r["handler"]:
                    mod, fn = r["handler"].rsplit(".", 1)
                    py = asset / (mod.replace(".", "/") + ".py") if asset else None
                else:
                    py, fn = None, None
                if py is not None:
                    try:
                        prel = py.relative_to(root).as_posix()
                    except ValueError:
                        prel = None
                    r["asset"] = asset.relative_to(root).as_posix() if asset and asset.is_relative_to(root) else ""
                    mod_name = file_of_module.get(prel or "")
                    if mod_name and f"{mod_name}:{fn}" in symbols:
                        r["handler_symbol"] = f"{mod_name}:{fn}"
                        r["runtime"] = r["runtime"] or "python"
                env = _prop(args, "environment")
                if env:
                    r["env"] = {k: _last(ref) for k, ref, _ in ENV_REF.findall(env)}
            elif cls_name == "LambdaInvoke":
                fn = _prop(args, "lambdaFunction") or _prop(args, "lambda_function")
                if fn:
                    edges.append({"from": m.group(5), "to": _last(fn), "kind": "invoke", "label": "Step Functions task",
                                  "file": rel, "line": r["line"], "_from_id": True})
            elif cls_name == "Rule":  # targets: [new targets.LambdaFunction(fn)], schedule: Schedule.rate(...)
                schedule = _prop(args, "schedule")
                label = re.sub(r"\b(?:events|cdk|core)\.", "", " ".join(schedule.split()))[:60] if schedule else "event pattern"
                for t in re.finditer(r"(?:new\s+)?[\w.]*?(?:LambdaFunction|SqsQueue|SfnStateMachine)\(\s*" + REF, _prop(args, "targets") or ""):
                    edges.append({"from": m.group(5), "to": _last(t.group(1)), "kind": "target", "label": label,
                                  "file": rel, "line": r["line"], "_from_id": True})
            resources.append(r)
        for m in ADD_RESOURCE.finditer(text):
            base = _last(m.group(2))
            parent = routes.get((rel, base), "")
            routes[(rel, m.group(1))] = parent.rstrip("/") + "/" + m.group(3).strip("/")
            head = base.split(".")[0]  # api.root.addResource("orders") → the route belongs to `api`
            route_api[(rel, m.group(1))] = route_api.get((rel, base), route_api.get((rel, head), head))
        for rx, kind in WIRING:
            for m in rx.finditer(text):
                g = m.groups()
                line = _line(text, m.start())
                owner_here = next((c[2] for c in reversed(classes) if c[0] <= m.start() < c[1]), None)
                if kind == "grant":
                    edges.append({"from": _last(g[2]), "to": _last(g[0]), "kind": "grant", "label": g[1], "file": rel, "line": line, "owner": owner_here})
                elif kind in ("trigger", "subscribe", "target"):
                    edges.append({"from": _last(g[2]), "to": _last(g[0]), "kind": kind, "label": g[1], "file": rel, "line": line, "owner": owner_here}
                                 if kind == "trigger" else
                                 {"from": _last(g[0]), "to": _last(g[2]), "kind": kind, "label": g[1], "file": rel, "line": line, "owner": owner_here})
                elif kind == "notify":
                    edges.append({"from": _last(g[0]), "to": _last(g[1]), "kind": "notify", "label": "S3 event", "file": rel, "line": line, "owner": owner_here})
                elif kind == "datasource":
                    edges.append({"from": _last(g[0]), "to": _last(g[2]), "kind": "datasource", "label": f"data source {g[1]}", "file": rel, "line": line, "owner": owner_here})
                elif kind == "route":
                    path = routes.get((rel, _last(g[0])), "/") if "addMethod" in m.group(0) or "add_method" in m.group(0) else g[1]
                    verb = g[1].upper() if "addMethod" in m.group(0) or "add_method" in m.group(0) else "ANY"
                    api = route_api.get((rel, _last(g[0])), _last(g[0]))  # a path resource stands for the API it was added to
                    edges.append({"from": api, "to": _last(g[2]), "kind": "route", "label": f"{verb} {path}", "file": rel, "line": line, "owner": owner_here})
    # resolve references to resources: the same file first, then a variable name or construct id unique in the repo
    for (file, var), attrs in list(attr_alias.items()):  # this.auroraPgVector = auroraPgVector
        if (file, var) in instances:
            for a in attrs:
                instances.setdefault((file, a), instances[(file, var)])

    def names_of(i):
        r = resources[i]
        out = {r["var"], r["id"], r["id"][:1].lower() + r["id"][1:]} | attr_alias.get((r["file"], r["var"]), set())
        return {k for k in out if k}

    by_file, names = {}, {}
    for i, r in enumerate(resources):
        for k in names_of(i):
            by_file.setdefault((r["file"], k), i)
            names.setdefault(k, []).append(i)
    instance_any = {}
    for (file, var), cls in instances.items():
        instance_any.setdefault(var, set()).add(cls)

    def resolve(ref, file, depth=0, owner=None):
        parts = ref.split(".") if isinstance(ref, str) else []
        if not parts or depth > 14:
            return None
        found = _resolve_here(parts, file, depth)
        if found is not None:
            return found
        for src_file, src_ref, src_owner in props_in.get((owner, parts[0]), ()) if owner else ():
            hit = resolve(".".join([src_ref] + parts[1:]), src_file, depth + 1, src_owner)
            if hit is not None:
                return hit
        if owner and not any(k == (owner, parts[0]) for k in props_in):
            for src_file, src_owner in props_spread.get(owner, ()):
                hit = resolve(".".join(parts), src_file, depth + 1, src_owner)
                if hit is not None:
                    return hit
        return None

    def resolve_in_class(parts, cls, depth):
        """`auroraPgVector.createAuroraWorkspaceWorkflow` seen from class `RagEngines`: descend construct by construct."""
        f = class_file.get(cls)
        if not f or depth > 14 or not parts:
            return None
        head = parts[0]
        if len(parts) == 1:
            hits = [i for i, r in enumerate(resources) if r["owner"] == cls and head in names_of(i)]
            if len(hits) == 1:
                return hits[0]
            if (f, head) in attr_dotted:
                return resolve(attr_dotted[(f, head)], f, depth + 1, cls)
            return None
        sub = instances.get((f, head))
        if sub:
            return resolve_in_class(parts[1:], sub, depth + 1)
        if (f, head) in attr_dotted:
            return resolve(".".join([attr_dotted[(f, head)]] + parts[1:]), f, depth + 1, cls)
        return None

    def _resolve_here(parts, file, depth):
        last = parts[-1]
        if len(parts) >= 2:  # langchainInterface.ingestionQueue → the resource LangChainInterface calls ingestionQueue
            cls = instances.get((file, parts[-2])) or (next(iter(instance_any[parts[-2]])) if len(instance_any.get(parts[-2], ())) == 1 else None)
            if cls:
                hits = [i for i, r in enumerate(resources) if r["owner"] == cls and last in names_of(i)]
                if len(hits) == 1:
                    return hits[0]
        if (file, last) in by_file:
            return by_file[(file, last)]
        if len(params.get((file, last), ())) == 1:
            return resolve(next(iter(params[(file, last)])), file, depth + 1)
        if len(parts) >= 2 and (file, parts[0]) in instances:  # ragEngines.auroraPgVector.workflow: walk the constructs
            hit = resolve_in_class(parts[1:], instances[(file, parts[0])], depth + 1)
            if hit is not None:
                return hit
        if len(parts) >= 2:  # chatBotApi.filesBucket: an attribute of an instance whose class sets this.filesBucket
            cls = instances.get((file, parts[-2]))
            hits = [i for i, r in enumerate(resources) if cls and r["owner"] == cls and last in names_of(i)]
            if len(hits) == 1:
                return hits[0]
        hits = names.get(last, [])
        return hits[0] if len(set(hits)) == 1 else None

    out_edges = []
    for e in edges:
        a = next((i for i, r in enumerate(resources) if r["id"] == e["from"] and r["file"] == e["file"]), None) if e.pop("_from_id", False) \
            else resolve(e["from"], e["file"], 0, e.get("owner"))
        b = resolve(e["to"], e["file"], 0, e.get("owner"))
        if a is None and b is None:
            continue
        e.pop("owner", None)
        out_edges.append({**e, "from": a if a is not None else e["from"], "to": b if b is not None else e["to"]})
    for i, r in enumerate(resources):
        for key, ref in (r.get("env") or {}).items():
            j = resolve(ref, r["file"], 0, r["owner"])
            if j is not None:  # an env var that names a resource (TABLE_NAME → the table); index names etc. are left out
                out_edges.append({"from": i, "to": j, "kind": "env", "label": key, "file": r["file"], "line": r["line"]})
    lambdas = [r for r in resources if r["service"] == "Lambda"]
    return {"resources": resources, "edges": out_edges, "files": sorted(f.relative_to(root).as_posix() for f in sources),
            "languages": sorted({"TypeScript" if f.suffix == ".ts" else "Python" for f in sources}),
            "lambdas": len(lambdas), "lambdas_linked": sum(1 for r in lambdas if r.get("handler_symbol"))}


def describe(infra: dict, i) -> str:
    """A resource as text: "Lambda UploadHandler", or the raw reference when it is not a known resource."""
    if isinstance(i, int):
        r = infra["resources"][i]
        return f"{r['service']} {r['id']}"
    return str(i)


def triggers(infra: dict) -> list[tuple[str, str]]:
    """(handler symbol, trigger text) for each Lambda whose Python handler is known: what invokes it, from the wiring."""
    out = []
    for i, r in enumerate(infra.get("resources", [])):
        if not r.get("handler_symbol"):
            continue
        kinds = ("trigger", "notify", "subscribe", "target", "datasource", "route", "invoke")
        inbound = [e for e in infra["edges"] if e["to"] == i and (e["kind"] in kinds or e["label"] in ("grantInvoke", "grant_invoke"))]
        inbound = [e for k, e in enumerate(inbound) if (e["from"], e["label"]) not in {(x["from"], x["label"]) for x in inbound[:k]}]

        def upstream(e):  # one hop further up: S3 UploadBucket → SQS IngestionQueue → Lambda
            feed = next((f for f in infra["edges"] if f["to"] == e["from"] and f["kind"] in kinds and f["from"] != i), None)
            return f"{describe(infra, feed['from'])} ({feed['label']}) → " if feed else ""

        how = "; ".join(f"{upstream(e)}{describe(infra, e['from'])} ({'invokes it' if e['kind'] == 'grant' else e['label']})"
                        for e in inbound[:3])
        out.append((r["handler_symbol"], f"{how} → Lambda {r['id']}" if how else f"Lambda {r['id']}"))
    return out


def section(infra: dict, lang: str) -> dict:
    rows = []
    order = {"api": 0, "messaging": 1, "workflow": 2, "compute": 3, "data": 4, "auth": 5, "config": 6, "security": 7, "edge": 8, "network": 9}
    for i, r in sorted(enumerate(infra["resources"]), key=lambda x: (order.get(x[1]["category"], 9), x[1]["service"], x[1]["id"])):
        if r["category"] in ("network", "security") and not any(e["to"] == i or e["from"] == i for e in infra["edges"] if e["kind"] != "env"):
            continue
        inbound = [f"← {describe(infra, e['from'])} ({e['label']})" for e in infra["edges"] if e["to"] == i and e["kind"] != "env"]
        outbound = [f"→ {describe(infra, e['to'])} ({e['label']})" for e in infra["edges"] if e["from"] == i]
        wiring = "; ".join((inbound + outbound)[:6]) + (" …" if len(inbound + outbound) > 6 else "") or "–"
        runs = {"sym": r["handler_symbol"], "line": 0} if r.get("handler_symbol") else (r.get("handler") or "–")
        rows.append([f"{r['service']} · {r['id']}", f"{r['file']}:{r['line']}", wiring, runs])
    cols = {"en": ["Resource", "Defined in", "Wiring (← invoked by · → may use)", "Runs"],
            "ko": ["리소스", "정의 위치", "연결 (← 호출하는 쪽 · → 사용하는 것)", "실행 코드"]}
    return {"columns": cols.get(lang, cols["en"]), "rows": rows}
