"""The whole pipeline on throwaway copies of the fixtures, through the vendored CLI — as a user runs it."""
import json
import re
import subprocess
import sys
import tomllib
import unittest

from _support import SCRIPTS, copy_fixture

CLI = SCRIPTS / "codeflow.py"


def run(repo, *args, tool=None):
    tool = tool or (repo / "docs" / "code-flow" / "tools" / "codeflow.py")
    r = subprocess.run([sys.executable, str(tool), *args], cwd=repo, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def setup(fixture, lang="en", depth="quick"):
    repo = copy_fixture(fixture)
    code, out = run(repo, "init", "--lang", lang, tool=CLI)
    assert code == 0, out
    code, out = run(repo, "draft", "--depth", depth)
    assert code == 0, out
    code, out = run(repo, "build")
    assert code == 0, out
    return repo


def page_data(repo):
    html = (repo / "docs" / "code-flow" / "code-flow-report.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="code-map">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)), html


class FullRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = setup("flask_app")
        cls.out = cls.repo / "docs" / "code-flow"

    def test_init_vendors_everything_needed_to_rebuild(self):
        for name in ["codeflow.py", "common.py", "extract.py", "build.py", "draft.py", "report.py", "infra.py", "template.html", "profiles/__init__.py", "profiles/llm.py"]:
            with self.subTest(name):
                self.assertTrue((self.out / "tools" / name).exists())
        self.assertEqual(tomllib.loads((self.out / "codeflow.toml").read_text())["paths"]["root"], "../..")

    def test_draft_proposes_the_write_journey_in_call_order(self):
        n = tomllib.loads((self.out / "narrative.toml").read_text(encoding="utf-8"))
        j = next(j for j in n["journeys"] if j["steps"][0]["symbol"] == "app.views:create_order")
        steps = [s["symbol"] for s in j["steps"]]
        self.assertEqual(steps[:2], ["app.views:create_order", "app.orders:run_write"])
        self.assertLess(steps.index("app.views:create_order.work"), steps.index("app.orders:insert_order"))
        self.assertEqual(j["trigger"], "POST /shop/orders")
        insert = next(s for s in j["steps"] if s["symbol"] == "app.orders:insert_order")
        self.assertEqual(insert["tables"], ["orders"])

    def test_page_carries_data_and_is_safe_inline(self):
        data, html = page_data(self.repo)
        self.assertEqual(data["lang"], "en")
        self.assertIn("app.views:create_order", data["keys"])
        self.assertGreater(data["todo"], 0)
        self.assertEqual(html.count("</script>"), 2)  # the JSON cannot close its own script tag
        self.assertEqual(data["profiles"], [])
        self.assertIn("note", data["modules"]["app.orders"])

    def test_check_passes_right_after_build(self):
        self.assertEqual(run(self.repo, "check")[0], 0)

    def test_candidates_and_query_run(self):
        code, out = run(self.repo, "candidates")
        self.assertEqual(code, 0)
        self.assertIn("app.views:create_order", out)
        code, out = run(self.repo, "query", "insert_order")
        self.assertEqual(code, 0)
        self.assertIn("insert ['orders']", out)


class Merge(unittest.TestCase):
    def test_check_writes_nothing_and_a_second_merge_adds_nothing(self):
        repo = setup("flask_app")
        narrative = repo / "docs" / "code-flow" / "narrative.toml"
        before = tomllib.loads(narrative.read_text(encoding="utf-8"))
        part = repo / "docs" / "code-flow" / ".parts" / "x.toml"
        part.parent.mkdir(exist_ok=True)
        dropped = before["roles"][0]["id"]
        part.write_text('[[layer_rules]]\ntext = "Orders never import views."\nfrom = ["app.orders"]\nforbid = ["app.views"]\n\n'
                        f'[[roles]]\nid = "{dropped}"\ndrop = true\n', encoding="utf-8")
        text = narrative.read_text(encoding="utf-8")
        self.assertEqual(run(repo, "merge", "--check", str(part))[0], 0)
        self.assertEqual(narrative.read_text(encoding="utf-8"), text)  # --check only validates
        for _ in range(2):
            self.assertEqual(run(repo, "merge", str(part))[0], 0)
        after = tomllib.loads(narrative.read_text(encoding="utf-8"))
        self.assertEqual(len(after["layer_rules"]), len(before.get("layer_rules", [])) + 1)  # an id-less entry is not appended twice
        self.assertNotIn(dropped, [r["id"] for r in after["roles"]])


class Staleness(unittest.TestCase):
    def test_code_change_makes_check_fail(self):
        repo = setup("flask_app")
        (repo / "app" / "orders.py").write_text((repo / "app" / "orders.py").read_text() + "\n\ndef added():\n    return notify({})\n")
        code, out = run(repo, "check")
        self.assertEqual(code, 1)
        self.assertIn("code_map.json is stale", out)

    def test_renamed_function_names_the_narrative_entry(self):
        repo = setup("flask_app")
        src = repo / "app" / "orders.py"
        src.write_text(src.read_text().replace("def insert_order(", "def add_order(").replace("insert_order(cur", "add_order(cur"))
        (repo / "app" / "views.py").write_text((repo / "app" / "views.py").read_text().replace("orders.insert_order", "orders.add_order"))
        code, out = run(repo, "check")
        self.assertEqual(code, 1)
        self.assertIn("symbol not in code: app.orders:insert_order", out)
        self.assertRegex(out, r"journeys\[create-order\]")

    def test_new_module_outside_every_layer_fails(self):
        repo = setup("src_layout_lib")
        (repo / "src" / "pkg").rename(repo / "src" / "pkg")  # no-op, keeps paths explicit
        (repo / "newtop.py").write_text("def hello():\n    return 1\n")
        cfg = repo / "docs" / "code-flow" / "codeflow.toml"
        cfg.write_text(cfg.read_text().replace('include = ["src"]', 'include = ["src", "newtop.py"]'))
        code, out = run(repo, "check")
        self.assertEqual(code, 1)
        self.assertIn("module newtop is in no layer", out)

    def test_module_notes_are_checked(self):
        cases = [("app.gone", 'purpose = "p"\ndoes = "d"\nflow = "f"', "module_notes: module not in code: app.gone"),
                 ("app.orders", 'purpose = "p"\ndoes = "d"', "module_notes.app.orders: empty flow")]
        for mod, body, expected in cases:
            with self.subTest(mod):
                repo = setup("flask_app")
                n = repo / "docs" / "code-flow" / "narrative.toml"
                text = n.read_text(encoding="utf-8")
                if mod == "app.orders":  # replace the drafted entry with an incomplete one
                    start = text.index('[module_notes."app.orders"]')
                    end = text.index("\n[", start + 1)
                    text = text[:start] + f'[module_notes."{mod}"]\n{body}\n' + text[end:]
                else:
                    text += f'\n[module_notes."{mod}"]\n{body}\n'
                n.write_text(text, encoding="utf-8")
                code, out = run(repo, "build")
                self.assertEqual(code, 1)
                self.assertIn(expected, out)

    def test_findings_retire_themselves_when_the_code_is_fixed(self):
        repo = setup("flask_app")
        n = repo / "docs" / "code-flow" / "narrative.toml"
        head = 'severity = "info"\ncategory = "x"\ndetail = "x"\n'
        n.write_text(n.read_text(encoding="utf-8")
                     + f'\n[[findings]]\nid = "dead-helper"\n{head}title = "no caller"\nsymbols = ["app.orders:unused_helper"]\ncheck = "no_callers"\n'
                     + f'\n[[findings]]\nid = "no-notify"\n{head}title = "list skips notify"\nsymbols = ["app.orders:list_orders"]\n'
                       'check = { kind = "not_calls", target = "app.orders:notify" }\n'
                     + f'\n[[findings]]\nid = "todo-text"\n{head}title = "has a TODO"\nsymbols = ["app.orders:unused_helper"]\n'
                       'check = { kind = "text_in", pattern = "def unused_helper" }\n', encoding="utf-8")
        self.assertEqual(run(repo, "build")[0], 0)
        status = lambda: {f["id"]: f.get("status", "open") for f in page_data(repo)[0]["findings"] if not f.get("generated")}  # noqa: E731
        self.assertEqual(status(), {"dead-helper": "open", "no-notify": "open", "todo-text": "open"})
        src = repo / "app" / "orders.py"
        text = src.read_text()
        src.write_text(text.replace("def unused_helper(", "def renamed_helper(") + "\n\ndef uses_it():\n    return renamed_helper()\n")
        self.assertEqual(run(repo, "build")[0], 0)  # a fixed finding is not a broken build: it moves to the Fixed list
        self.assertEqual(status(), {"dead-helper": "fixed", "no-notify": "open", "todo-text": "fixed"})

    def test_malformed_check_fails_the_build(self):
        repo = setup("flask_app")
        n = repo / "docs" / "code-flow" / "narrative.toml"
        n.write_text(n.read_text(encoding="utf-8") + '\n[[findings]]\nid = "bad"\nseverity = "info"\ncategory = "x"\ntitle = "t"\n'
                     'detail = "x"\nsymbols = ["app.orders:notify"]\ncheck = { kind = "calls" }\n', encoding="utf-8")
        code, out = run(repo, "build")
        self.assertEqual(code, 1)
        self.assertIn("calls needs target", out)


class Languages(unittest.TestCase):
    def test_korean_page_and_unicode_round_trip(self):
        repo = setup("flask_app", lang="ko")
        n = repo / "docs" / "code-flow" / "narrative.toml"
        text = n.read_text(encoding="utf-8").replace('lede = "TODO:', 'lede = "주문을 받아 저장하고 알린다 — \\"따옴표\\" 포함. TODO:', 1)
        n.write_text(text, encoding="utf-8")
        self.assertEqual(run(repo, "build")[0], 0)
        data, html = page_data(repo)
        self.assertEqual(data["lang"], "ko")
        self.assertIn('lang="ko"', html)
        self.assertIn("주문을 받아", data["meta"]["lede"])


class Infrastructure(unittest.TestCase):
    def test_cdk_section_on_the_page_and_drafted_lambda_cards(self):
        repo = setup("cdk_ts_app")
        data, _ = page_data(repo)
        sec = next(p for p in data["profiles"] if p["name"] == "infra")
        self.assertTrue(sec["title"].startswith("Infrastructure (TypeScript CDK)"))
        runs = [row[-1] for row in sec["rows"] if isinstance(row[-1], dict)]
        self.assertEqual(sorted(r["sym"] for r in runs), ["functions.orders.app:create_order", "functions.orders.worker:handle"])
        n = tomllib.loads((repo / "docs" / "code-flow" / "narrative.toml").read_text(encoding="utf-8"))
        self.assertTrue(any(r["kind"] == "infra" for r in n["roles"]))


class Profiles(unittest.TestCase):
    def test_llm_section_and_card_only_where_the_stack_is_used(self):
        repo = setup("fastapi_llm")
        data, _ = page_data(repo)
        self.assertEqual([p["name"] for p in data["profiles"]], ["llm"])
        self.assertEqual(data["profiles"][0]["rows"][0][0]["sym"], "svc.agent:answer")
        self.assertIn("svc.agent:answer", data["cardExtras"])
        n = tomllib.loads((repo / "docs" / "code-flow" / "narrative.toml").read_text(encoding="utf-8"))
        self.assertTrue(any(r.get("kind") == "model" for r in n["roles"]))

    def test_jobs_section_lists_tasks_and_enqueue(self):
        repo = setup("celery_jobs")
        data, _ = page_data(repo)
        (sec,) = data["profiles"]
        kinds = {(r[0]["sym"], r[1]) for r in sec["rows"]}
        self.assertEqual(kinds, {("jobs.tasks:nightly_digest", "task"), ("jobs.tasks:nightly_digest", "enqueue")})


class Report(unittest.TestCase):
    def test_markdown_report_becomes_a_page(self):
        repo = setup("flask_app")
        md = repo / "docs" / "code-flow" / "overview.md"
        md.write_text("# Shop overview\n\nIntro with `code`.\n\n## Goals\n\n| A | B |\n|---|---|\n| x \\| y | **z** |\n\n- one\n- two\n", encoding="utf-8")
        code, out = run(repo, "report", str(md))
        self.assertEqual(code, 0, out)
        html = md.with_suffix(".html").read_text(encoding="utf-8")
        self.assertIn("<td>x | y</td>", html)
        self.assertIn('<a href="code-flow-report.html">', html)


if __name__ == "__main__":
    unittest.main()
