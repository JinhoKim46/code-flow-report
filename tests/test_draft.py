"""What `draft` must propose, on the example app — the gaps the SKILL.md acceptance run found."""
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from _support import REPO
from test_cli import CLI, run

DEMO = REPO / "examples" / "demo-shop"


class DemoDraft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp(prefix="codeflow-demo-"))
        cls.repo = tmp / "demo-shop"
        shutil.copytree(DEMO, cls.repo, ignore=shutil.ignore_patterns("docs"))
        assert run(cls.repo, "init", tool=CLI)[0] == 0
        code, cls.out = run(cls.repo, "draft", "--depth", "standard")
        assert code == 0, cls.out
        cls.n = tomllib.loads((cls.repo / "docs" / "code-flow" / "narrative.toml").read_text(encoding="utf-8"))

    def journey(self, entry):
        return next(j for j in self.n["journeys"] if j["steps"][0]["symbol"] == entry)

    def test_handler_keeps_its_validation_step(self):
        steps = [s["symbol"] for s in self.journey("shop.web:place_order")["steps"]]
        self.assertIn("shop.orders:validate", steps)
        self.assertLess(steps.index("shop.orders:validate"), steps.index("shop.orders:create_order"))

    def test_no_duplicate_card_for_a_profiled_function(self):
        cards = [r for r in self.n["roles"] if "shop.summary:summarise" in r.get("symbols", [])]
        self.assertEqual([r["kind"] for r in cards], ["model"])

    def test_decorator_only_task_gets_a_card(self):
        jobs = {r["symbols"][0] for r in self.n["roles"] if r["kind"] == "background"}
        self.assertIn("shop.tasks:cancel_unpaid", jobs)

    def test_input_flows_are_proposed_for_write_routes(self):
        self.assertEqual(self.n["input_flows"][0]["steps"][0]["symbol"], "shop.web:place_order")

    def test_todo_counts_agree(self):
        drafted = int(self.out.split("·")[-1].split()[0])
        code, listed = run(self.repo, "todo")
        self.assertEqual(int(listed.strip().splitlines()[-1].split()[0]), drafted)

    def test_every_module_gets_a_note_prefilled_or_todo(self):
        notes = self.n["module_notes"]
        self.assertEqual(set(notes), {"shop", "shop.web", "shop.orders", "shop.catalog", "shop.db", "shop.payments", "shop.summary",
                                      "shop.mail", "shop.tasks"})
        self.assertEqual(notes["shop.orders"], "Order rules: totals are computed here, never taken from the client.")  # from the docstring
        self.assertTrue(notes["shop.mail"].startswith("TODO"))  # no docstring

    def test_no_bytecode_left_in_the_target_repo(self):
        run(self.repo, "build")
        self.assertEqual(list((self.repo / "docs" / "code-flow" / "tools").rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
