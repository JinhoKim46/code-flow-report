"""Background-jobs profile: work that runs without a request — task queues and schedulers.

Switched on when the repo imports a task or scheduling library. Recognises task decorators
(`@app.task`, `@shared_task`, `@dramatiq.actor`, `@job`), scheduler registrations
(`scheduler.add_job(fn, ...)`, `schedule.every(...).do(fn)`) and enqueue calls (`.delay`, `.apply_async`,
`.enqueue`, `.send`), so the report can show what runs on its own and who triggers it.
"""
from __future__ import annotations

import ast

NAME = "jobs"
PACKAGES = ["celery", "rq", "dramatiq", "huey", "apscheduler", "schedule", "arq", "prefect", "airflow", "dagster", "luigi"]
TITLE = {"en": "Background jobs", "ko": "백그라운드 작업"}
INTRO = {"en": "Functions registered as tasks or scheduled jobs, and the places that enqueue them. A task's real caller is the worker, so these edges are invisible in an ordinary call graph.",
         "ko": "작업 큐나 스케줄러에 등록된 함수와, 그것을 큐에 넣는 곳. 실제로 부르는 쪽이 워커라서 보통의 호출 그래프에는 이 간선이 보이지 않는다."}

TASK_DECORATORS = {"task", "shared_task", "actor", "job", "periodic_task", "flow", "dag", "asset", "op"}
SCHEDULE_CALLS = {"add_job", "scheduled_job", "do", "add_periodic_task", "every"}
ENQUEUE_CALLS = {"delay", "apply_async", "enqueue", "enqueue_call", "send", "kiq", "submit"}


def _target_name(node):
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)


def on_call(ctx, node, resolved, chain):
    name = _target_name(node.func)
    if name in SCHEDULE_CALLS:
        fn = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg in ("func", "sig")), None)
        if fn is not None:
            r = ctx.resolve_expr(fn)
            if r and r[0] == "internal":
                trig = ", ".join(f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords if k.arg in ("trigger", "hour", "minute", "day_of_week", "seconds", "cron"))[:80]
                return {"kind": "schedule", "symbol": ctx.here(), "line": node.lineno, "job": r[1], "how": f"{chain or name}({trig})"}
    if name in ENQUEUE_CALLS and isinstance(node.func, ast.Attribute):
        r = ctx.resolve_expr(node.func.value)
        if r and r[0] == "internal":
            return {"kind": "enqueue", "symbol": ctx.here(), "line": node.lineno, "job": r[1], "how": f".{name}()"}
    return None


def decorated_tasks(code_map):
    out = []
    for key, s in code_map["symbols"].items():
        for d in s.get("decorators", []):
            if d.split(".")[-1] in TASK_DECORATORS:
                out.append({"kind": "task", "symbol": key, "line": s["line"], "job": key, "how": "@" + d})
    return out


def section(records, code_map):
    rows = []
    for r in sorted(decorated_tasks(code_map) + records, key=lambda r: (r["job"], r["kind"])):
        rows.append([{"sym": r["job"], "line": code_map["symbols"].get(r["job"], {}).get("line", 0)}, r["kind"], r["how"],
                     {"sym": r["symbol"], "line": r["line"]} if r["kind"] != "task" else "–"])
    return {"columns": {"en": ["Job", "Kind", "How", "Registered / triggered by"], "ko": ["작업", "종류", "방법", "등록 · 실행하는 곳"]},
            "rows": rows}


def draft_roles(records, code_map=None):
    jobs = sorted({r["job"] for r in records} | {t["job"] for t in (decorated_tasks(code_map) if code_map else [])})
    return [{"id": "job-" + j.split(":", 1)[1].replace(".", "-").replace("_", "-").lower(), "name": f"Background job: {j.split(':', 1)[1]}",
             "kind": "background", "symbols": [j], "purpose": "TODO: what runs, when, and why it cannot wait for a request",
             "config": "TODO: where the schedule or queue is configured", "validation": "TODO: retries, idempotency, what happens on failure",
             "logging": "TODO: where a failed run is noticed"} for j in jobs[:12]]
