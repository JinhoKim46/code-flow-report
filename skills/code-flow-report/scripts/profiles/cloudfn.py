"""Serverless functions declared in Python: Azure Functions (v2 model), Google `functions_framework`, AWS Chalice.

Switched on when the repo imports one of them. These frameworks put the trigger on the function itself —
`@app.queue_trigger(queue_name="jobs")`, `@functions_framework.cloud_event`, `@app.on_sqs_message(queue="jobs")` —
so the infrastructure code (Terraform, Bicep) names the app but not the handler. This profile reads the
decorators, lists every trigger, and offers each decorated function as a journey entry.
"""
from __future__ import annotations

import ast

NAME = "cloudfn"
PACKAGES = ["azure", "functions_framework", "chalice"]
SINK = False
ENTRY_KIND = "infra"  # the platform invokes these functions
TITLE = {"en": "Function triggers", "ko": "함수 트리거"}
INTRO = {"en": "Functions whose trigger is declared in Python (Azure Functions, Google Cloud Functions Framework, AWS Chalice): what invokes each one and with which binding.",
         "ko": "트리거가 파이썬 데코레이터에 적힌 함수(Azure Functions, Google Cloud Functions Framework, AWS Chalice): 무엇이 각 함수를 부르는지와 그 바인딩."}

AZURE = {"route": "HTTP", "queue_trigger": "Storage queue", "blob_trigger": "Blob storage", "timer_trigger": "Timer",
         "service_bus_queue_trigger": "Service Bus queue", "service_bus_topic_trigger": "Service Bus topic",
         "event_grid_trigger": "Event Grid", "event_hub_message_trigger": "Event Hub", "cosmos_db_trigger": "Cosmos DB change feed",
         "orchestration_trigger": "Durable orchestration", "activity_trigger": "Durable activity", "entity_trigger": "Durable entity",
         "kafka_trigger": "Kafka", "sql_trigger": "Azure SQL change", "mcp_tool_trigger": "MCP tool"}
FUNCTIONS_FRAMEWORK = {"http": "HTTP", "cloud_event": "CloudEvent (Eventarc / Pub/Sub / Storage)", "typed": "HTTP (typed)"}
CHALICE = {"route": "HTTP (API Gateway)", "on_sqs_message": "SQS", "on_s3_event": "S3 event", "on_sns_message": "SNS",
           "schedule": "Schedule (EventBridge)", "on_cw_event": "EventBridge event", "on_kinesis_record": "Kinesis",
           "on_dynamodb_record": "DynamoDB stream", "lambda_function": "Direct invoke", "on_ws_message": "WebSocket message"}
DETAIL_KW = ("route", "queue_name", "path", "schedule", "topic_name", "event_hub_name", "container_name", "queue", "bucket",
             "topic", "name", "methods")


def on_call(ctx, node, resolved, chain):
    return None


def _platform(ctx):
    pkgs = {str(t).split(".")[0] for t in (ctx.imports.values() if isinstance(ctx.imports, dict) else [])}
    text = " ".join(str(v) for v in (ctx.imports.values() if isinstance(ctx.imports, dict) else []))
    if "azure.functions" in text or "azure" in pkgs and "functions" in text:
        return "Azure Functions", AZURE
    if "functions_framework" in text:
        return "Cloud Functions", FUNCTIONS_FRAMEWORK
    if "chalice" in text:
        return "Chalice (AWS Lambda)", CHALICE
    return None, {}


def on_module(ctx, tree):
    platform, table = _platform(ctx)
    if not platform:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            call = d if isinstance(d, ast.Call) else None
            func = call.func if call else d
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in table:
                continue
            bits = []
            if call and call.args:
                bits.append(ast.unparse(call.args[0])[:60])
            for kw in call.keywords if call else []:
                if kw.arg in DETAIL_KW:
                    bits.append(f"{kw.arg}={ast.unparse(kw.value)[:50]}")
            qual = ".".join(_qual(tree, node))
            out.append({"kind": "trigger", "symbol": f"{ctx.mod}:{qual}", "line": node.lineno, "platform": platform,
                        "trigger": table[name], "decorator": name, "detail": ", ".join(bits)})
    return out


def _qual(tree, target):
    """Qualified name of a function in a module (top-level or a method)."""
    for node in tree.body:
        if node is target:
            return [target.name]
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if sub is target:
                    return [node.name, target.name]
    return [target.name]


def triggers(records, code_map):
    out = []
    for r in records:
        if r.get("kind") == "trigger" and r["symbol"] in code_map["symbols"]:
            detail = f" ({r['detail']})" if r.get("detail") else ""
            out.append((r["symbol"], f"{r['platform']}: {r['trigger']}{detail}"))
    return out


def section(records, code_map):
    rows = [[{"sym": r["symbol"], "line": r["line"]}, r["platform"], r["trigger"], f"@{r['decorator']}" + (f"({r['detail']})" if r.get("detail") else "")]
            for r in sorted(records, key=lambda r: (r["symbol"], r["line"])) if r.get("kind") == "trigger"]
    return {"columns": {"en": ["Function", "Platform", "Trigger", "Declared as"], "ko": ["함수", "플랫폼", "트리거", "선언"]}, "rows": rows}
