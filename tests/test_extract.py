"""What the extractor must find in each fixture — exact sets, so a regression cannot hide."""
import unittest

from _support import code_map, config, extract, FIXTURES


def edges(cm):
    return {(a, b) for a, b, _ in cm["calls"]}


class FlaskApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("flask_app")

    def test_tests_are_not_scanned(self):
        self.assertNotIn("tests.test_views", self.cm["modules"])

    def test_call_edges(self):
        self.assertEqual(edges(self.cm), {
            ("app.orders:insert_order", "app.orders:notify"), ("app.orders:run_write", "app.db:connect"),
            ("app.views:create_order", "app.orders:run_write"), ("app.views:create_order.work", "app.orders:insert_order"),
            ("app.views:list_orders", "app.db:connect"), ("app.views:list_orders", "app.orders:list_orders")})

    def test_callback_is_a_reference_edge(self):
        self.assertIn(("app.views:create_order", "app.views:create_order.work"), {(a, b) for a, b, _ in self.cm["refs"]})

    def test_routes_carry_the_blueprint_prefix_and_guards(self):
        r = self.cm["routes"]
        self.assertEqual(r["app.views:create_order"]["urls"], [["POST", "/shop/orders"]])
        self.assertEqual(r["app.views:list_orders"]["urls"], [["GET", "/shop/orders"]])
        self.assertEqual(r["app.views:list_orders"]["guards"], ["login_required"])
        self.assertEqual(r["app.views:list_orders"]["templates"], ["orders.html"])

    def test_sql_tables_from_schema_and_access(self):
        self.assertEqual(self.cm["tables"], ["customers", "order_totals", "orders"])
        by = {(e["symbol"], op): e[op] for e in self.cm["sql"] for op in ("insert", "update", "delete", "read") if e.get(op)}
        self.assertEqual(by[("app.orders:insert_order", "insert")], ["orders"])
        self.assertEqual(by[("app.orders:list_orders", "read")], ["customers", "orders"])
        self.assertEqual(by[("app.orders:totals", "read")], ["order_totals"])  # through a module-level SQL constant

    def test_gateway_and_boundaries(self):
        self.assertEqual([(g["symbol"], g["action"]) for g in self.cm["gateways"]], [("app.views:create_order", "order_create")])
        services = {(e["symbol"], e["service"]) for e in self.cm["external"]}
        self.assertIn(("app.orders:notify", "HTTP (requests)"), services)
        self.assertIn(("app.db:connect", "SQLite"), services)

    def test_no_profile_without_its_stack(self):
        self.assertEqual(self.cm["profiles"], {})

    def test_dead_candidates(self):
        self.assertEqual(self.cm["dead_candidates"], ["app.orders:totals", "app.orders:unused_helper"])

    def test_convention_typed_calls_are_counted_separately(self):
        self.assertGreater(self.cm["summary"]["resolved_by_convention"], 0)


class FastApiLlm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("fastapi_llm")

    def test_router_prefix_is_mount_then_declared(self):
        self.assertEqual(self.cm["routes"]["svc.routes:ask"]["urls"], [["POST", "/api/v1/ask"]])

    def test_llm_profile_routes_on_and_reads_the_call(self):
        self.assertEqual(list(self.cm["profiles"]), ["llm"])
        (rec,) = self.cm["profiles"]["llm"]
        self.assertEqual(rec["symbol"], "svc.agent:answer")
        self.assertEqual(rec["provider"], "Anthropic")
        self.assertEqual(rec["settings"], {"model": "'demo-model-1'", "temperature": "0.2", "max_tokens": "512"})
        self.assertEqual(rec["message_roles"], ["system (system=)", "user"])
        self.assertEqual(rec["output_schema"], "output_format=Answer")

    def test_profile_can_be_disabled(self):
        cm = extract.build(FIXTURES / "fastapi_llm", config(profiles={"disable": ["llm"]}))
        self.assertEqual(cm["profiles"], {})


class DjangoSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("django_site")

    def test_urls_function_and_class_views(self):
        r = {k: v["urls"] for k, v in self.cm["routes"].items()}
        self.assertEqual(r["shop.views:order_list"], [["ANY", "/orders/"]])
        self.assertEqual(r["shop.views:OrderDetail"], [["ANY", "/orders/<int:pk>/"]])

    def test_models_become_tables_and_uses(self):
        self.assertEqual(self.cm["orm_models"], {"shop.models:Invoice": "billing_invoice", "shop.models:Order": "order"})
        self.assertEqual(self.cm["orm_uses"]["order"], ["shop.views:OrderDetail.get", "shop.views:order_list"])


class CeleryJobs(unittest.TestCase):
    def test_jobs_profile_links_enqueue_to_task(self):
        cm = code_map("celery_jobs")
        self.assertEqual(list(cm["profiles"]), ["jobs"])
        self.assertEqual([(r["kind"], r["symbol"], r["job"]) for r in cm["profiles"]["jobs"]],
                         [("enqueue", "jobs.api:trigger", "jobs.tasks:nightly_digest")])
        self.assertIn(("jobs.mail:send_digest", "SMTP email"), {(e["symbol"], e["service"]) for e in cm["external"]})


class SrcLayoutLib(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("src_layout_lib")

    def test_src_prefix_is_stripped(self):
        self.assertIn("pkg.core", self.cm["modules"])
        self.assertNotIn("src.pkg.core", self.cm["modules"])

    def test_reexport_relative_import_and_methods_resolve(self):
        e = edges(self.cm)
        self.assertIn(("pkg.cli:main", "pkg.core:run"), e)           # `from pkg import run` → pkg/__init__ re-export
        self.assertIn(("pkg.core:Engine.step", "pkg.util:helper"), e)  # `from . import util`
        self.assertIn(("pkg.core:Engine.start", "pkg.core:Engine.step"), e)  # self.method()
        self.assertIn(("pkg.core:run", "pkg.core:Engine.start"), e)  # Engine().start()
        self.assertEqual(self.cm["summary"]["unresolved"], 0)

    def test_real_and_lazy_cycles_are_told_apart(self):
        self.assertEqual(self.cm["import_cycles"], [["pkg.a", "pkg.b"]])
        self.assertEqual(self.cm["lazy_import_cycles"], [["pkg.core", "pkg.util"]])

    def test_cli_is_marked(self):
        self.assertTrue(self.cm["modules"]["pkg.cli"]["cli"])


class ObjectInference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("oo_lib")
        cls.calls = {e["call"] for e in cls.cm["external"]} | set()

    def test_attribute_assigned_in_init_types_later_calls(self):
        self.assertIn(("oo.app:Service.run", "oo.base:Store.save"), edges(self.cm))

    def test_inherited_library_method_imported_object_and_annotation(self):
        s = self.cm["summary"]
        self.assertEqual(s["unresolved"], 0, s["top_unresolved_names"])

    def test_sqlmodel_table_true_is_a_table(self):
        self.assertEqual(self.cm["orm_models"], {"oo.models:Hero": "hero"})


class Broken(unittest.TestCase):
    def test_a_syntax_error_is_recorded_not_fatal(self):
        cm = code_map("broken")
        self.assertEqual(list(cm["modules"]), ["good"])
        self.assertEqual(cm["parse_errors"][0][0], "bad.py")


class Determinism(unittest.TestCase):
    def test_same_source_same_bytes(self):
        for fx in ("flask_app", "src_layout_lib", "fastapi_llm"):
            with self.subTest(fx):
                self.assertEqual(extract.render(code_map(fx)), extract.render(code_map(fx)))


if __name__ == "__main__":
    unittest.main()
