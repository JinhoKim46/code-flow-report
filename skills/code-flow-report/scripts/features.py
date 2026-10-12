"""What a report can contain: the feature catalog, its previews and the plan shown before building.

The skill asks about each feature with its preview (`codeflow.py features --json`), then shows the
whole plan as a tree (`codeflow.py plan --select …`) before writing anything. Choices are stored in
codeflow.toml under [features]; a feature left out of that table takes its default.
"""
from __future__ import annotations

FEATURES = [
    {
        "id": "system_map", "default": True, "auto": False,
        "title": {"en": "System map", "ko": "시스템 맵"},
        "what": {"en": "Layers, parts and labelled connections; click a part for its files and neighbours; tags and a walkthrough",
                 "ko": "레이어·부품·연결선. 부품을 누르면 파일과 이웃이 보이고, 태그와 흐름 따라가기 제공"},
        "preview": {
            "en": "[UI] Home ──▶ [Core] Engine ──▶ [SQLite]\n"
                  "                  └──▶ [Service] OpenRouter\n"
                  "Click a box → its files, what it calls, what calls it.\n"
                  "Tags (R2, E4 …) light every part that delivers them.",
            "ko": "[UI] 홈 ──▶ [핵심] 엔진 ──▶ [SQLite]\n"
                  "                └──▶ [외부] OpenRouter\n"
                  "상자를 누르면 → 파일, 호출하는 곳, 호출받는 곳.\n"
                  "태그(R2, E4 …)를 누르면 그 태그를 가진 부품이 켜짐.",
        },
        "output": {"en": "report section; system-map.html; system-map.md (PR-ready)", "ko": "보고서 섹션; system-map.html; system-map.md (PR용)"},
    },
    {
        "id": "call_flow", "default": True, "auto": False,
        "title": {"en": "Call flow of each journey", "ko": "여정별 호출 흐름"},
        "what": {"en": "From an entry point (a route, CLI, job) down the call chain to the database or an external service",
                 "ko": "진입점(라우트·CLI·작업)에서 호출 체인을 따라 DB나 외부 서비스까지"},
        "preview": {
            "en": "POST /interview/start\n"
                  "  1. engine.start        interview/engine.py:42\n"
                  "  2. prompts.build       prompts/prompting.py:17\n"
                  "  3. llm.chat_json  ──▶ OpenRouter            [external]\n"
                  "  4. db.save_turn   ──▶ SQLite                [write]",
            "ko": "POST /interview/start\n"
                  "  1. engine.start        interview/engine.py:42\n"
                  "  2. prompts.build       prompts/prompting.py:17\n"
                  "  3. llm.chat_json  ──▶ OpenRouter            [외부]\n"
                  "  4. db.save_turn   ──▶ SQLite                [쓰기]",
        },
        "output": {"en": "journeys section with one step list per entry point", "ko": "여정 섹션 (진입점마다 단계 목록)"},
    },
    {
        "id": "data_life", "default": True, "auto": False,
        "title": {"en": "Data lifecycle per table", "ko": "표별 데이터 일생"},
        "what": {"en": "Where each table is created, updated, deleted and read", "ko": "표마다 생성·수정·삭제·읽기가 일어나는 곳"},
        "preview": {
            "en": "applications\n"
                  "  born       ingest.create_application\n"
                  "  update     applications.rename\n"
                  "  read       history.list_for_user\n"
                  "  delete     applications.delete (blocked while an interview runs)",
            "ko": "applications\n"
                  "  생성       ingest.create_application\n"
                  "  수정       applications.rename\n"
                  "  읽기       history.list_for_user\n"
                  "  삭제       applications.delete (면접 진행 중이면 막힘)",
        },
        "output": {"en": "data section with one card per table", "ko": "데이터 섹션 (표마다 카드)"},
    },
    {
        "id": "model_calls", "default": True, "auto": True, "profile": "llm",
        "title": {"en": "Model calls", "ko": "모델 호출"},
        "what": {"en": "Provider, model, settings and message roles at each call site. Switched on automatically when the repo imports an LLM SDK",
                 "ko": "호출 지점별 제공자·모델·설정·메시지 역할. 레포가 LLM SDK를 import하면 자동으로 켜짐"},
        "preview": {
            "en": "[auto · import openai detected]\n"
                  "interview/engine.py  chat_json   gpt-5-mini   system · user · assistant\n"
                  "evaluation/judge.py  run_judge   claude-haiku  ×3, median",
            "ko": "[자동 · openai import 감지]\n"
                  "interview/engine.py  chat_json   gpt-5-mini   system · user · assistant\n"
                  "evaluation/judge.py  run_judge   claude-haiku  ×3, 중앙값",
        },
        "output": {"en": "model-calls section", "ko": "모델 호출 섹션"},
    },
    {
        "id": "pr_output", "default": True, "auto": False,
        "title": {"en": "PR-ready Mermaid and Markdown", "ko": "PR용 Mermaid · Markdown"},
        "what": {"en": "The system map as a Mermaid chart (GitHub draws it) plus a Markdown page to paste into a PR or README",
                 "ko": "시스템 맵을 Mermaid 차트(GitHub가 그림)와 PR·README에 붙일 Markdown으로"},
        "preview": {
            "en": "```mermaid\nflowchart LR\n  subgraph ui[\"UI\"] … end\n  n_home --> n_engine\n```\n"
                  "→ renders inside the PR description",
            "ko": "```mermaid\nflowchart LR\n  subgraph ui[\"UI\"] … end\n  n_home --> n_engine\n```\n"
                  "→ PR 설명 안에서 그려짐",
        },
        "output": {"en": "system-map.md, system-map.mmd", "ko": "system-map.md, system-map.mmd"},
    },
    {
        "id": "findings", "default": True, "auto": False,
        "title": {"en": "Findings: docs vs code, real risks", "ko": "발견 사항: 문서와 코드 차이, 실제 위험"},
        "what": {"en": "Where documentation and code disagree, with the trigger and reach of each real risk",
                 "ko": "문서와 코드가 어긋나는 곳, 실제 위험의 발생 조건과 영향 범위"},
        "preview": {"en": "⚠ README says retries=3; code/client.py:88 uses retries=1\n   trigger: any 429  ·  reach: every chat call",
                    "ko": "⚠ README 는 retries=3; code/client.py:88 은 retries=1\n   발생: 429 응답  ·  영향: 모든 채팅 호출"},
        "output": {"en": "findings section", "ko": "발견 사항 섹션"},
    },
    {
        "id": "staleness_test", "default": False, "auto": False,
        "title": {"en": "Staleness test in the repo", "ko": "낡음 검사 테스트 설치"},
        "what": {"en": "A unittest that fails when the report no longer matches the code. Every PR that moves a function must rebuild",
                 "ko": "보고서가 코드와 맞지 않으면 실패하는 unittest. 함수가 움직이는 PR마다 재생성 필요"},
        "preview": {"en": "$ python -m unittest tests/test_code_flow.py\nFAILED: 2 narrative entries point at changed code\n  → run: codeflow.py build",
                    "ko": "$ python -m unittest tests/test_code_flow.py\nFAILED: 서술 항목 2개가 바뀐 코드를 가리킴\n  → 실행: codeflow.py build"},
        "output": {"en": "tests/test_code_flow.py", "ko": "tests/test_code_flow.py"},
    },
]

PLAN_HEAD = {"en": "Report plan", "ko": "보고서 계획"}


def by_id(feature_id: str) -> dict:
    for f in FEATURES:
        if f["id"] == feature_id:
            return f
    raise KeyError(feature_id)


def enabled(cfg: dict, feature_id: str, detected: dict | None = None) -> bool:
    """Whether a feature is on. `[features]` in codeflow.toml wins; otherwise the default.
    Auto features (model calls) follow what the repo imports, unless set explicitly."""
    table = (cfg or {}).get("features", {})
    if feature_id in table:
        return bool(table[feature_id])
    f = by_id(feature_id)
    if f.get("auto"):
        return bool((detected or {}).get(f.get("profile", ""), False))
    return bool(f["default"])


def catalog(lang: str = "en", detected: dict | None = None) -> list[dict]:
    """Each feature with its text for one language, ready to show or to put in a question's preview."""
    lang = lang if lang in ("en", "ko") else "en"
    out = []
    for f in FEATURES:
        out.append({"id": f["id"], "title": f["title"][lang], "what": f["what"][lang],
                    "preview": f["preview"][lang], "output": f["output"][lang],
                    "default": enabled({}, f["id"], detected), "auto": f.get("auto", False)})
    return out


def plan(selected: list[str] | None, lang: str = "en", detected: dict | None = None) -> str:
    """The whole plan as a tree, the way it will be built. `selected` None means the defaults."""
    lang = lang if lang in ("en", "ko") else "en"
    chosen = set(selected) if selected is not None else {f["id"] for f in FEATURES if enabled({}, f["id"], detected)}
    rows = []
    for f in FEATURES:
        on = f["id"] in chosen
        mark = "[x]" if on else "[ ]"
        tag = " (auto)" if f.get("auto") else ""
        rows.append((mark, f["title"][lang] + tag, f["id"], f["output"][lang] if on else ""))
    lines = [f"{PLAN_HEAD[lang]}  ·  code-flow-report.html"]
    for i, (mark, title, fid, out) in enumerate(rows):
        branch = "└─" if i == len(rows) - 1 else "├─"
        lines.append(f"{branch} {mark} {title:<38} {fid}")
        if out:
            lines.append(f"{'   ' if i == len(rows) - 1 else '│  '}     → {out}")
    unknown = sorted(chosen - {f["id"] for f in FEATURES})
    if unknown:
        lines.append(f"! unknown features: {', '.join(unknown)}")
    return "\n".join(lines)
