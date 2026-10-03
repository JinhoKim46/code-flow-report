"""Terraform (AWS, Google Cloud, Azure): what runs each Python function, what invokes it and what it may touch.

Same output as the CDK scanner in infra.py — resources, wiring edges, and for each function the Python
symbol it runs — read from `.tf` files. HCL is scanned, not evaluated: blocks are cut out by matching
braces (comments, strings and heredocs respected), references are the `TYPE.NAME.attr` / `data.TYPE.NAME.attr`
/ `module.NAME.out` shapes Terraform itself uses, `local.x` and `${path.module}` are substituted, and
`var.x` is read from a variable's default. Connector resources (event source mappings, permissions,
routes, targets, notifications, subscriptions, IAM policies and role bindings) become edges between
the primary resources; they are not listed as resources themselves.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# resource type → (service, category); a type not here is a connector or not shown
TYPES = {
    # AWS
    "aws_lambda_function": ("Lambda", "compute"), "aws_sqs_queue": ("SQS", "messaging"), "aws_sns_topic": ("SNS", "messaging"),
    "aws_dynamodb_table": ("DynamoDB", "data"), "aws_s3_bucket": ("S3", "data"), "aws_sfn_state_machine": ("Step Functions", "workflow"),
    "aws_apigatewayv2_api": ("API Gateway (HTTP)", "api"), "aws_api_gateway_rest_api": ("API Gateway", "api"),
    "aws_appsync_graphql_api": ("AppSync", "api"), "aws_cloudwatch_event_rule": ("EventBridge rule", "messaging"),
    "aws_scheduler_schedule": ("EventBridge Scheduler", "messaging"), "aws_cloudwatch_event_bus": ("EventBridge bus", "messaging"),
    "aws_kinesis_stream": ("Kinesis", "messaging"), "aws_db_instance": ("RDS", "data"), "aws_rds_cluster": ("Aurora", "data"),
    "aws_opensearch_domain": ("OpenSearch", "data"), "aws_opensearchserverless_collection": ("OpenSearch Serverless", "data"),
    "aws_secretsmanager_secret": ("Secrets Manager", "config"), "aws_ssm_parameter": ("SSM parameter", "config"),
    "aws_iam_role": ("IAM role", "security"), "aws_kms_key": ("KMS key", "security"), "aws_cognito_user_pool": ("Cognito user pool", "auth"),
    "aws_ecs_service": ("ECS service", "compute"), "aws_sagemaker_endpoint": ("SageMaker endpoint", "compute"),
    "aws_bedrockagent_knowledge_base": ("Bedrock knowledge base", "data"), "aws_bedrockagent_agent": ("Bedrock agent", "compute"),
    "aws_cloudfront_distribution": ("CloudFront", "edge"), "aws_elasticache_cluster": ("ElastiCache", "data"),
    "aws_appsync_api": ("AppSync Events", "api"), "aws_bedrockagent_data_source": ("Bedrock KB data source", "data"),
    "awscc_bedrock_prompt": ("Bedrock prompt", "config"), "aws_bedrock_guardrail": ("Bedrock guardrail", "config"),
    "aws_lb": ("Load balancer", "api"), "aws_ecs_cluster": ("ECS cluster", "compute"),
    # Google Cloud
    "google_cloudfunctions_function": ("Cloud Function", "compute"), "google_cloudfunctions2_function": ("Cloud Function (2nd gen)", "compute"),
    "google_cloud_run_v2_service": ("Cloud Run", "compute"), "google_cloud_run_service": ("Cloud Run", "compute"),
    "google_cloud_run_v2_job": ("Cloud Run job", "compute"), "google_pubsub_topic": ("Pub/Sub topic", "messaging"),
    "google_pubsub_subscription": ("Pub/Sub subscription", "messaging"), "google_storage_bucket": ("Cloud Storage", "data"),
    "google_bigquery_dataset": ("BigQuery dataset", "data"), "google_bigquery_table": ("BigQuery table", "data"),
    "google_firestore_database": ("Firestore", "data"), "google_sql_database_instance": ("Cloud SQL", "data"),
    "google_alloydb_cluster": ("AlloyDB", "data"), "google_cloud_scheduler_job": ("Cloud Scheduler", "messaging"),
    "google_eventarc_trigger": ("Eventarc trigger", "messaging"), "google_workflows_workflow": ("Workflows", "workflow"),
    "google_secret_manager_secret": ("Secret Manager", "config"), "google_service_account": ("Service account", "security"),
    "google_document_ai_processor": ("Document AI processor", "compute"), "google_vertex_ai_index": ("Vertex AI index", "data"),
    "google_vertex_ai_index_endpoint": ("Vertex AI index endpoint", "compute"), "google_vertex_ai_endpoint": ("Vertex AI endpoint", "compute"),
    "google_redis_instance": ("Memorystore", "data"),
    # Azure
    "azurerm_linux_function_app": ("Function App", "compute"), "azurerm_windows_function_app": ("Function App", "compute"),
    "azurerm_function_app": ("Function App", "compute"), "azurerm_function_app_flex_consumption": ("Function App", "compute"),
    "azurerm_linux_web_app": ("App Service", "compute"), "azurerm_container_app": ("Container App", "compute"),
    "azurerm_storage_account": ("Storage account", "data"), "azurerm_storage_container": ("Blob container", "data"),
    "azurerm_storage_queue": ("Storage queue", "messaging"), "azurerm_servicebus_queue": ("Service Bus queue", "messaging"),
    "azurerm_servicebus_topic": ("Service Bus topic", "messaging"), "azurerm_eventhub": ("Event Hub", "messaging"),
    "azurerm_eventgrid_topic": ("Event Grid topic", "messaging"), "azurerm_eventgrid_system_topic": ("Event Grid system topic", "messaging"),
    "azurerm_cosmosdb_account": ("Cosmos DB", "data"), "azurerm_cosmosdb_sql_container": ("Cosmos DB container", "data"),
    "azurerm_mssql_database": ("Azure SQL", "data"), "azurerm_postgresql_flexible_server": ("PostgreSQL", "data"),
    "azurerm_key_vault": ("Key Vault", "config"), "azurerm_cognitive_account": ("Azure AI / OpenAI", "compute"),
    "azurerm_search_service": ("AI Search", "data"), "azurerm_user_assigned_identity": ("Managed identity", "security"),
}
FUNCTIONS = {"aws_lambda_function", "google_cloudfunctions_function", "google_cloudfunctions2_function"}
LAMBDA_MODULES = ("terraform-aws-modules/lambda/aws", "lambda/aws")
# community modules that stand for one resource (matched on the module source)
MODULE_TYPES = [("rds-aurora", ("Aurora", "data")), ("rds/aws", ("RDS", "data")), ("dynamodb-table", ("DynamoDB", "data")),
                ("s3-bucket", ("S3", "data")), ("sqs/aws", ("SQS", "messaging")), ("sns/aws", ("SNS", "messaging")),
                ("apigateway-v2", ("API Gateway (HTTP)", "api")), ("eventbridge", ("EventBridge", "messaging")),
                ("step-functions", ("Step Functions", "workflow")), ("ecs/aws//modules/service", ("ECS service", "compute")),
                ("ecs/aws", ("ECS cluster", "compute")), ("vpc/aws", ("VPC", "network")), ("alb/aws", ("Load balancer", "api")),
                ("cloud-run", ("Cloud Run", "compute")), ("cloud-storage", ("Cloud Storage", "data")), ("pubsub", ("Pub/Sub topic", "messaging")),
                ("event-function", ("Cloud Function", "compute"))]
BLOCK = re.compile(r'^[ \t]*(resource|data|module|locals|variable|output)\b\s*(?:"([^"]+)")?\s*(?:"([^"]+)")?\s*\{', re.M)
REF = re.compile(r'\b(?:(data)\.)?([a-z][a-z0-9_]*)\.([A-Za-z_][\w-]*)(?:\[[^\]]*\])?\.([A-Za-z_]\w*)')
MOD_REF = re.compile(r'\bmodule\.([A-Za-z_][\w-]*)(?:\[[^\]]*\])?\.(\w+)')
SKIP_REF_HEADS = {"var", "local", "each", "count", "path", "self", "module", "terraform"}


def dockerfile_handler(context: Path, dockerfile: str | None = None, cmd: str | None = None):
    """A container-image Lambda's handler: `CMD ["pkg.module.func"]` (or the given cmd) and the `COPY` that puts
    that module into the image → (python file in the repo, function name), or (None, None)."""
    df = context / (dockerfile or "Dockerfile")
    try:
        text = df.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    if not cmd:
        m = None
        for m in re.finditer(r'(?im)^\s*CMD\s+(\[.*?\]|\S+)', text):
            pass  # the last CMD wins, as in Docker
        if not m:
            return None, None
        cmd = (re.findall(r'"([^"]+)"', m.group(1)) or [m.group(1)])[0]
    if "." not in cmd:
        return None, None
    mod, fn = cmd.rsplit(".", 1)
    rel = mod.replace(".", "/") + ".py"
    for c in re.finditer(r'(?im)^\s*(?:COPY|ADD)\s+(?:--\S+\s+)*(\S+)\s+(\S+)\s*$', text):
        src, dest = c.group(1), c.group(2)
        cand = context / src
        if src.endswith(".py") and src.rstrip("/").endswith(rel.rsplit("/", 1)[-1]) and src.count("/") >= rel.count("/"):
            return Path(os.path.normpath(cand)), fn               # COPY ./events/lambda_function.py .
        if (cand / rel).is_file():
            return Path(os.path.normpath(cand / rel)), fn          # COPY ./src/ ${LAMBDA_TASK_ROOT}
        top = rel.split("/")[0]
        if dest.rstrip("/").endswith("/" + top) and (cand / rel.split("/", 1)[-1]).is_file():
            return Path(os.path.normpath(cand / rel.split("/", 1)[-1])), fn   # COPY ./events/events/ ${ROOT}/events/
    hits = list(context.rglob(rel))
    return (Path(os.path.normpath(hits[0])), fn) if len(hits) == 1 else (None, None)


def _strip(text: str) -> str:
    """Blank out comments and heredoc bodies (offsets and lines kept), leaving quoted strings alone."""
    out, i, n, quote = list(text), 0, len(text), False
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                quote = False
            i += 1
            continue
        if c == '"':
            quote = True
            i += 1
            continue
        m = re.match(r"<<-?\s*([A-Z_]+)\n", text[i:i + 40])
        if m:  # heredoc: keep it as a blank string body (its references still count for policies, so keep text)
            end = re.search(r"\n[ \t]*" + m.group(1) + r"\b", text[i + m.end():])
            i = i + m.end() + (end.end() if end else n)
            continue
        if c == "#" or text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _close(text: str, start: int) -> int:
    depth, i, quote = 0, start, False
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                quote = False
        elif c == '"':
            quote = True
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _attr(body: str, key: str):
    """The text of `key = value` anywhere in a block body (objects and lists kept whole)."""
    m = re.search(r'(?m)^[ \t]*"?' + re.escape(key) + r'"?\s*=\s*', body)
    if not m:
        return None
    i = m.end()
    if i < len(body) and body[i] in "{[(":
        return body[i:_close(body, i)]
    call = re.match(r"[A-Za-z_][\w.]*\(", body[i:])  # jsonencode({ ... }), merge(...), templatefile(...)
    if call:
        return body[i:_close(body, i + call.end() - 1)]
    if body.startswith("<<", i):
        end = body.find("\n", i)
        tag = re.match(r"<<-?\s*([A-Z_]+)", body[i:]).group(1)
        stop = re.search(r"\n[ \t]*" + tag + r"\b", body[end:])
        return body[i:end + (stop.end() if stop else len(body))]
    j = body.find("\n", i)
    return body[i:j if j >= 0 else len(body)].strip()


def _blocks(body: str, name: str) -> list[str]:
    """Nested blocks `name { ... }` (e.g. event_trigger, environment, lambda_function)."""
    out = []
    for m in re.finditer(r'(?m)^[ \t]*' + re.escape(name) + r'\s*\{', body):
        out.append(body[m.end() - 1:_close(body, m.end() - 1)])
    return out


def _map_entries(obj):
    """`{ name = { ... }, other = { ... } }` → [(name, body), ...]."""
    out = []
    if not obj or not obj.startswith("{"):
        return out
    inner = obj[1:-1]
    for m in re.finditer(r'(?m)^[ \t]*"?([\w-]+)"?\s*=\s*\{', inner):
        out.append((m.group(1), inner[m.end() - 1:_close(inner, m.end() - 1)]))
    return out


def _lit(value) -> str | None:
    if not value:
        return None
    m = re.match(r'\s*"((?:[^"\\]|\\.)*)"', value)
    return m.group(1) if m else None


def scan_tf(root: Path, files: list[Path], modules: dict, symbols: dict) -> tuple[list[dict], list[dict]]:
    blocks = []   # (kind, type, name, body, file, line)
    locals_, variables, outputs, locals_raw = {}, {}, {}, {}
    for f in files:
        try:
            text = _strip(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        for m in BLOCK.finditer(text):
            brace = m.end() - 1
            body = text[brace:_close(text, brace)]
            kind, a, b = m.group(1), m.group(2), m.group(3)
            line = text.count("\n", 0, m.start()) + 1
            if kind == "locals":
                for lm in re.finditer(r'(?m)^[ \t]*(\w+)\s*=\s*"([^"\n]*)"', body):
                    locals_[(f.parent, lm.group(1))] = lm.group(2)
                for lm in re.finditer(r'(?m)^[ \t]*(\w+)\s*=\s*[{\[]', body):   # maps and lists, for templatefile()
                    locals_raw.setdefault((f.parent, lm.group(1)), _attr(body, lm.group(1)) or "")
            elif kind == "variable":
                d = _lit(_attr(body, "default"))
                if d is not None:
                    variables[(f.parent, a)] = d
            elif kind == "output":
                outputs[(f.parent, a)] = _attr(body, "value") or ""
            else:
                blocks.append((kind, a, b, body, f, rel, line))
    # a module called with a local source: its folder, and who passes what into it
    module_dir, callers = {}, {}
    for kind, a, b, body, f, rel, line in blocks:
        if kind == "module":
            src = _lit(_attr(body, "source")) or ""
            if src.startswith(("./", "../")):
                d = Path(os.path.normpath(f.parent / src))
                module_dir[(f.parent, a)] = d
                callers.setdefault(d, []).append((f.parent, body))

    def subst(s: str, f: Path) -> str:
        for _ in range(5):  # locals may refer to other locals and to ${path.module}
            before = s
            s = re.sub(r"\$\{local\.(\w+)\}", lambda m: locals_.get((f.parent, m.group(1)), m.group(0)), s)
            s = re.sub(r"\$\{var\.(\w+)\}", lambda m: variables.get((f.parent, m.group(1)), m.group(0)), s)
            s = s.replace("${path.module}", str(f.parent)).replace("${path.root}", str(f.parent)).replace("${path.cwd}", str(f.parent))
            if s == before:
                break
        return s

    def path_value(value, f: Path):
        """A path written as "${path.module}/../src", path.module + "/x", local.x or var.x."""
        if value is None:
            return None
        v = value.strip()
        lit = _lit(v)
        if lit is None:
            m = re.match(r"(local|var)\.(\w+)", v)
            if m:
                lit = (locals_ if m.group(1) == "local" else variables).get((f.parent, m.group(2)))
            m = re.match(r'path\.(?:module|root|cwd)\s*\}?\s*,?\s*"?([^"]*)"?', v) if lit is None else None
            if m and lit is None:
                lit = "${path.module}" + ("/" if m.group(1) and not m.group(1).startswith("/") else "") + m.group(1)
        if lit is None:
            return None
        p = subst(lit, f)
        p = p if os.path.isabs(p) else str(f.parent / p)
        return Path(os.path.normpath(p))

    # Addresses are scoped to the module folder that declares them ("<folder>|aws_sqs_queue.jobs"): two modules may
    # both have an aws_iam_role.lambda. A reference resolves in its own folder first, else to the only match anywhere.
    def qa(kind, a, b, f):
        return f"{f.parent}|" + (f"module.{a}" if kind == "module" else (f"data.{a}.{b}" if kind == "data" else f"{a}.{b}"))

    by_addr, plain_index = {}, {}
    for blk in blocks:
        k = qa(blk[0], blk[1], blk[2], blk[4])
        by_addr[k] = blk
        plain_index.setdefault(k.split("|", 1)[1], []).append(k)
    cur = [root]   # the folder of the block being read; refs() resolves there

    def resolve(addr, d):
        k = f"{d}|{addr}"
        if k in by_addr:
            return k
        c = plain_index.get(addr, [])
        return c[0] if len(c) == 1 else None

    def refs(text: str, d=None, depth=0) -> list[str]:
        d = d or cur[0]
        out = []
        for m in REF.finditer(text or ""):
            if m.group(2) in SKIP_REF_HEADS:
                continue
            k = resolve(f"data.{m.group(2)}.{m.group(3)}" if m.group(1) else f"{m.group(2)}.{m.group(3)}", d)
            if k:
                out.append(k)
        for m in MOD_REF.finditer(text or ""):
            k = resolve(f"module.{m.group(1)}", d)
            if k and (d, m.group(1)) not in module_dir:
                out.append(k)   # a community module that is itself a resource
            elif (d, m.group(1)) in module_dir and depth < 4:   # a local module: follow its output
                md = module_dir[(d, m.group(1))]
                out += refs(outputs.get((md, m.group(2)), ""), md, depth + 1)
        if depth < 4:   # var.x: what the callers of this module pass in
            for vm in re.finditer(r"\bvar\.(\w+)", text or ""):
                for cd, body in callers.get(d, []):
                    out += refs(_attr(body, vm.group(1)) or "", cd, depth + 1)
        return list(dict.fromkeys(out))

    def plain(k):
        return k.split("|", 1)[-1] if isinstance(k, str) else k

    def tmpl(text: str, f: Path) -> str:
        """templatefile("x.tpl", { key = aws_lambda_function.y.arn }) → the template's text with each ${key} replaced by
        the expression passed for it, so the references inside (a Step Functions task, a policy resource) can be read."""
        out = text or ""
        for m in list(re.finditer(r"templatefile\(", text or "")):
            inner = text[m.end() - 1:_close(text, m.end() - 1)][1:-1]
            depth, cut = 0, None
            for i, c in enumerate(inner):
                depth += c in "([{"
                depth -= c in ")]}"
                if c == "," and depth == 0:
                    cut = i
                    break
            if cut is None:
                continue
            path = path_value(inner[:cut].strip(), f)
            mapping = inner[cut + 1:].strip()
            lm = re.fullmatch(r"local\.(\w+)", mapping)
            if lm:
                mapping = locals_raw.get((f.parent, lm.group(1)), "")
            try:
                body = path.read_text(encoding="utf-8", errors="replace") if path else ""
            except OSError:
                body = ""
            for km in re.finditer(r'(?m)^[ \t]*"?([\w-]+)"?\s*[=:]\s*(.+?),?\s*$', mapping):
                body = re.sub(r"\$\{\s*" + re.escape(km.group(1)) + r"\s*\}", lambda _m, v=km.group(2): v, body)   # ${ name } too
            out += "\n" + body
        return out

    def archive_dir(ref_text: str):
        """`data.archive_file.x.output_path` (or a bucket object built from it) → the source folder."""
        for addr in refs(ref_text):
            kind, a, b, body, f, rel, line = by_addr[addr]
            if a == "archive_file":   # `data "archive_file"` or the newer `resource "archive_file"`
                return path_value(_attr(body, "source_dir"), f) or (lambda p: p.parent if p else None)(path_value(_attr(body, "source_file"), f))
            if a in ("google_storage_bucket_object", "aws_s3_object", "aws_s3_bucket_object"):
                saved, cur[0] = cur[0], f.parent
                try:
                    return archive_dir(_attr(body, "source") or "")
                finally:
                    cur[0] = saved
        return None

    def image_build(ref_text: str):
        """`docker_registry_image.x.name` / `docker_image.y.name` → (build context, dockerfile)."""
        for addr in refs(ref_text):
            kind, a, b, body, f, rel, line = by_addr[addr]
            if a == "docker_registry_image":
                saved, cur[0] = cur[0], f.parent
                try:
                    return image_build(_attr(body, "name") or "")
                finally:
                    cur[0] = saved
            if a == "docker_image":
                build = (_blocks(body, "build") or [""])[0]
                ctx = path_value(_attr(build, "context"), f)
                if ctx:
                    return ctx, _lit(_attr(build, "dockerfile"))
        return None

    file_of_module = {info["file"]: m for m, info in modules.items()}

    def link(py: Path | None, fn: str | None):
        if not py or not fn:
            return None
        try:
            mod = file_of_module.get(py.relative_to(root).as_posix())
        except ValueError:
            return None
        return f"{mod}:{fn}" if mod and f"{mod}:{fn}" in symbols else None

    resources, index = [], {}
    for blk in blocks:
        kind, a, b, body, f, rel, line = blk
        cur[0] = f.parent
        if kind == "module":
            src = _lit(_attr(body, "source")) or ""
            if any(src.endswith(x) for x in LAMBDA_MODULES):
                service, category, typ = "Lambda", "compute", "module"
            else:
                kind_ = next((t for key, t in MODULE_TYPES if key in src), None)
                if not kind_:
                    continue
                (service, category), typ = kind_, "module:" + src
        elif kind == "resource" and a in TYPES:
            (service, category), typ = TYPES[a], a
        else:
            continue
        name = b if kind == "resource" else a
        addr = qa(kind, a, b, f)
        r = {"id": _lit(_attr(body, "function_name")) or _lit(_attr(body, "name")) or name, "var": plain(addr), "cls": typ,
             "service": service, "category": category, "file": rel, "line": line, "owner": None}
        if r["id"].startswith("${") or "${" in r["id"]:
            r["id"] = name
        if typ in FUNCTIONS or typ == "module":
            handler = _lit(_attr(body, "handler"))
            runtime = (_lit(_attr(body, "runtime")) or "").lower()
            build = (_blocks(body, "build_config") or [""])[0]
            runtime = runtime or (_lit(_attr(build, "runtime")) or "").lower()
            r["runtime"] = "python" if "python" in runtime else ("node" if "node" in runtime else runtime[:10])
            if typ in ("aws_lambda_function", "module"):
                r["handler"] = handler
                src = path_value(_attr(body, "source_path"), f) if typ == "module" else archive_dir(_attr(body, "filename") or "")
                if src and handler and "." in handler:
                    mod, fn = handler.rsplit(".", 1)
                    r["asset"] = os.path.relpath(src, root).replace(os.sep, "/")
                    r["handler_symbol"] = link(src / (mod.replace(".", "/") + ".py"), fn)
                image = image_build(_attr(body, "image_uri") or "")
                if image and not r.get("handler_symbol"):  # a container image: the Dockerfile's CMD names the handler
                    cmd = _lit(_attr(" ".join(_blocks(body, "image_config")), "command")) or \
                        (re.findall(r'"([^"]+)"', _attr(" ".join(_blocks(body, "image_config")), "command") or "") or [None])[0]
                    py, fn = dockerfile_handler(*image, cmd=cmd)
                    r["handler"] = r["handler"] or (f"{py.stem}.{fn}" if py else "container image")
                    if py:
                        r["asset"] = os.path.relpath(image[0], root).replace(os.sep, "/")
                        r["handler_symbol"] = link(py, fn)
            else:  # Google Cloud Functions: entry_point in main.py of the uploaded source
                entry = _lit(_attr(body, "entry_point")) or _lit(_attr(build, "entry_point"))
                r["handler"] = entry
                src = archive_dir(_attr(body, "source_archive_object") or "") or archive_dir(build)
                if src and entry:
                    r["asset"] = os.path.relpath(src, root).replace(os.sep, "/")
                    r["handler_symbol"] = link(src / "main.py", entry)
            if not r.get("handler_symbol"):
                r.pop("handler_symbol", None)
        index[addr] = len(resources)
        resources.append(r)

    edges = []

    def edge(frm, to, kind, label, rel, line):
        a = index.get(frm) if frm in index else plain(frm)
        b = index.get(to) if to in index else plain(to)
        if (isinstance(a, int) or isinstance(b, int)) and a != b and a is not None and b is not None:
            edges.append({"from": a, "to": b, "kind": kind, "label": label, "file": rel, "line": line})

    def first(text):
        rs = refs(text)
        return rs[0] if rs else None

    fn_role, sa_of = {}, {}   # IAM role / service account → functions using it
    for blk in blocks:
        kind, a, b, body, f, rel, line = blk
        cur[0] = f.parent
        addr = qa(kind, a, b, f)
        if addr in index and resources[index[addr]]["category"] == "compute":
            role = first(_attr(body, "role") or "")
            if role:
                fn_role.setdefault(role, []).append(addr)
            sa = first(_attr(body, "service_account_email") or "") or first(" ".join(_blocks(body, "service_config")))
            if sa and plain(sa).startswith("google_service_account."):
                sa_of.setdefault(sa, []).append(addr)
            for envb in _blocks(body, "environment") + _blocks(body, "service_config") + [body]:
                for key in ("variables", "environment_variables", "app_settings"):
                    obj = _attr(envb, key)
                    for em in re.finditer(r'(?m)^[ \t]*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*=\s*(.+)$', (obj or "")[1:-1]):
                        target = first(em.group(2))
                        if target and target != addr:
                            edge(addr, target, "env", em.group(1), rel, line)
            # Google Cloud Functions triggers
            for trig in _blocks(body, "event_trigger"):
                src = first(_attr(trig, "resource") or "") or first(_attr(trig, "pubsub_topic") or "") or first(trig)
                event = _lit(_attr(trig, "event_type")) or "event"
                if src:
                    edge(src, addr, "trigger", event.rsplit(".", 1)[-1] if "." in event else event, rel, line)
            if re.search(r"(?m)^[ \t]*trigger_http\s*=\s*true", body) or a == "google_cloudfunctions2_function" and not _blocks(body, "event_trigger"):
                edge("HTTPS", addr, "route", "HTTP trigger", rel, line)  # invoked by its URL
        if kind == "module" and addr in index:  # terraform-aws-modules/lambda: triggers declared as module inputs
            for k, entry in _map_entries(_attr(body, "allowed_triggers")):
                src = first(entry)
                svc = _lit(_attr(entry, "service")) or _lit(_attr(entry, "principal")) or k
                if src:
                    edge(src, addr, "route" if "apigateway" in svc else "trigger", svc, rel, line)
            for k, entry in _map_entries(_attr(body, "event_source_mapping")):
                src = first(_attr(entry, "event_source_arn") or "")
                if src:
                    edge(src, addr, "trigger", TYPES.get(plain(src).split(".")[0], (k,))[0], rel, line)
        # AWS connectors
        if a == "aws_lambda_event_source_mapping":
            src, fn = first(_attr(body, "event_source_arn") or ""), first(_attr(body, "function_name") or "")
            if src and fn:
                edge(src, fn, "trigger", TYPES.get(plain(src).split(".")[0], ("event source",))[0], rel, line)
        elif a == "aws_lambda_permission":
            src, fn = first(_attr(body, "source_arn") or ""), first(_attr(body, "function_name") or "")
            principal = _lit(_attr(body, "principal")) or ""
            if src and fn and not principal.startswith("apigateway"):
                edge(src, fn, "trigger" if "events" not in principal else "target", principal.split(".")[0] or "invoke", rel, line)
        elif a == "aws_apigatewayv2_route":
            api = first(_attr(body, "api_id") or "")
            integ = first(_attr(body, "target") or "")
            if integ and integ in by_addr:
                fn = first(_attr(by_addr[integ][3], "integration_uri") or "")
                if api and fn:
                    edge(api, fn, "route", _lit(_attr(body, "route_key")) or "route", rel, line)
        elif a == "aws_api_gateway_integration":
            api, fn = first(_attr(body, "rest_api_id") or ""), first(_attr(body, "uri") or "")
            res = first(_attr(body, "resource_id") or "")
            path = "/" + (_lit(_attr(by_addr[res][3], "path_part")) or "") if res and res in by_addr and "path_part" in by_addr[res][3] else "/"
            method = _lit(_attr(body, "http_method"))
            if method is None:
                mref = first(_attr(body, "http_method") or "")
                method = _lit(_attr(by_addr[mref][3], "http_method")) if mref in by_addr else "ANY"
            if api and fn:
                edge(api, fn, "route", f"{method} {path}", rel, line)
        elif a == "aws_cloudwatch_event_target":
            rule, target = first(_attr(body, "rule") or ""), first(_attr(body, "arn") or "")
            label = "event pattern"
            if rule in by_addr:
                label = _lit(_attr(by_addr[rule][3], "schedule_expression")) or label
            if rule and target:
                edge(rule, target, "target", label, rel, line)
        elif a == "aws_scheduler_schedule" and addr in index:
            for t in _blocks(body, "target"):
                target = first(_attr(t, "arn") or "")
                if target:
                    edge(addr, target, "target", _lit(_attr(body, "schedule_expression")) or "schedule", rel, line)
        elif a == "aws_s3_bucket_notification":
            bucket = first(_attr(body, "bucket") or "")
            for kind_, key in (("lambda_function", "lambda_function_arn"), ("queue", "queue_arn"), ("topic", "topic_arn")):
                for nb in _blocks(body, kind_):
                    target = first(_attr(nb, key) or "")
                    if bucket and target:
                        edge(bucket, target, "notify", "S3 event", rel, line)
        elif a == "aws_sns_topic_subscription":
            topic, endpoint = first(_attr(body, "topic_arn") or ""), first(_attr(body, "endpoint") or "")
            if topic and endpoint:
                edge(topic, endpoint, "subscribe", _lit(_attr(body, "protocol")) or "subscription", rel, line)
        elif a == "aws_sfn_state_machine" and addr in index:
            for target in dict.fromkeys(refs(tmpl(_attr(body, "definition") or "", f))):   # ordered: the map must not change per run
                if target in index and resources[index[target]]["category"] == "compute":
                    edge(addr, target, "invoke", "Step Functions task", rel, line)
        # Google Cloud connectors
        elif a == "google_cloud_scheduler_job" and addr in index:
            for tb in _blocks(body, "pubsub_target") + _blocks(body, "http_target"):
                target = first(tb)
                if target:
                    edge(addr, target, "target", _lit(_attr(body, "schedule")) or "schedule", rel, line)
        elif a == "google_eventarc_trigger" and addr in index:
            dest = first(" ".join(_blocks(body, "destination")))
            if dest:
                edge(addr, dest, "trigger", "Eventarc", rel, line)
        elif a == "google_pubsub_subscription" and addr in index:
            topic = first(_attr(body, "topic") or "")
            if topic:
                edge(topic, addr, "subscribe", "subscription", rel, line)
            push = first(" ".join(_blocks(body, "push_config")))
            if push:
                edge(addr, push, "subscribe", "push", rel, line)
        elif a == "google_storage_notification":
            bucket, topic = first(_attr(body, "bucket") or ""), first(_attr(body, "topic") or "")
            if bucket and topic:
                edge(bucket, topic, "notify", "object event", rel, line)

    # permissions: AWS IAM policies attached to a function's role; Google IAM members bound to its service account;
    # Azure role assignments to its identity
    policy_docs = {qa(kind, a, b, f): body for kind, a, b, body, f, *_ in blocks if kind == "data" and a == "aws_iam_policy_document"}
    attached = {}   # aws_iam_policy addr → roles
    for kind, a, b, body, f, rel, line in blocks:
        cur[0] = f.parent
        if a in ("aws_iam_role_policy_attachment", "aws_iam_policy_attachment"):
            pol = first(_attr(body, "policy_arn") or "")
            for role in refs(_attr(body, "role") or "") + refs(_attr(body, "roles") or ""):
                if pol:
                    attached.setdefault(pol, []).append(role)
    for kind, a, b, body, f, rel, line in blocks:
        cur[0] = f.parent
        roles = []
        if a == "aws_iam_role_policy":
            roles = refs(_attr(body, "role") or "")
        elif a == "aws_iam_policy":
            roles = attached.get(qa(kind, a, b, f), [])
        elif a == "aws_iam_role" and qa(kind, a, b, f) in fn_role:
            roles = [qa(kind, a, b, f)]
        if not roles:
            continue
        text = tmpl(_attr(body, "policy") or "", f) + " ".join(_blocks(body, "inline_policy"))
        for d in refs(text):
            if d in policy_docs:
                text += " ".join(_blocks(policy_docs[d], "statement"))
        for actions, targets in _statements(text):
            targets = [resolve(t, f.parent) for t in targets]
            targets = [t for t in targets if t in index and not plain(t).startswith("aws_iam_role.")]
            for role in roles:
                for fn in fn_role.get(role, []):
                    for t in dict.fromkeys(targets):
                        edge(fn, t, "grant", ", ".join(actions[:3]) + (" …" if len(actions) > 3 else "") or "policy", rel, line)
    for kind, a, b, body, f, rel, line in blocks:
        cur[0] = f.parent
        if a.startswith("google_") and a.endswith(("_iam_member", "_iam_binding")):
            member = _attr(body, "member") or _attr(body, "members") or ""
            sa = first(member)
            target = next((r for r in refs(body) if r in index and not plain(r).startswith("google_service_account.")), None)
            for fn in sa_of.get(sa, []) if sa else []:
                if target:
                    edge(fn, target, "grant", _lit(_attr(body, "role")) or "iam", rel, line)
        elif a == "azurerm_role_assignment":
            scope, principal = first(_attr(body, "scope") or ""), first(_attr(body, "principal_id") or "")
            if scope and principal:
                edge(principal, scope, "grant", _lit(_attr(body, "role_definition_name")) or "role", rel, line)
    seen, out = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["kind"], e["label"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return resources, out


def _statements(text: str) -> list[tuple[list[str], list[str]]]:
    """IAM policy statements → [(actions, referenced resources)], innermost objects that hold an action list:
    jsonencode({ Statement = [{ Action = [...], Resource = [...] }] }), heredoc JSON, or `statement { actions … }` blocks."""
    out, i = [], 0
    while True:
        i = text.find("{", i)
        if i < 0:
            break
        j = _close(text, i)
        obj = text[i:j]
        inner_has = re.search(r"\{[^{}]*(?:Action|actions)", obj[1:])
        if re.search(r'(?i)"?(?:Action|actions)"?\s*[=:]', obj) and not inner_has:
            acts = sorted(set(re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', obj)))
            out.append((acts, [m for m in _refs_in(obj)]))
            i = j
        else:
            i += 1
    return out


def _refs_in(text: str) -> list[str]:
    out = []
    for m in REF.finditer(text):
        if m.group(2) not in SKIP_REF_HEADS:
            out.append(f"data.{m.group(2)}.{m.group(3)}" if m.group(1) else f"{m.group(2)}.{m.group(3)}")
    out += [f"module.{m.group(1)}" for m in MOD_REF.finditer(text)]
    return out


def _service_prefix(service: str) -> set[str]:
    return {"Lambda": {"lambda"}, "SQS": {"sqs"}, "SNS": {"sns"}, "DynamoDB": {"dynamodb"}, "S3": {"s3"}, "Step Functions": {"states"},
            "Kinesis": {"kinesis"}, "Secrets Manager": {"secretsmanager"}, "SSM parameter": {"ssm"}, "KMS key": {"kms"},
            "OpenSearch": {"es"}, "OpenSearch Serverless": {"aoss"}, "Bedrock knowledge base": {"bedrock"},
            "EventBridge bus": {"events"}}.get(service, set())
