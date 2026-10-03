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
        self.assertEqual(self.cm["dead_candidates"], ["app.orders:unused_helper"])

    def test_tests_are_read_for_callers_only(self):
        self.assertEqual(self.cm["test_only"], ["app.orders:totals"])  # only tests/test_views.py refers to it
        self.assertEqual(self.cm["test_files"], 1)
        self.assertFalse(any(a.startswith("tests.") for a, _, _ in self.cm["calls"] + self.cm["refs"]))

    def test_convention_typed_calls_are_counted_separately(self):
        self.assertGreater(self.cm["summary"]["resolved_by_convention"], 0)


class FastApiLlm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("fastapi_llm")

    def test_router_prefix_is_mount_then_declared(self):
        self.assertEqual(self.cm["routes"]["svc.routes:ask"]["urls"], [["POST", "/api/v1/ask"]])
        # a second file also calls its router `router`: each keeps its own prefix
        self.assertEqual(self.cm["routes"]["svc.admin:stats"]["urls"], [["GET", "/api/admin/stats"]])

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


class TypeInference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("types_lib")
        cls.e = edges(cls.cm)

    def test_rule_by_rule(self):
        cases = [
            ("return annotation", ("tl.use:returns", "tl.store:Store.save")),
            ("dataclass field", ("tl.use:field", "tl.store:Store.save")),
            ("Optional[...] annotation", ("tl.store:maybe", "tl.store:Store.save")),
            ("string annotation", ("tl.store:quoted", "tl.store:Store.save")),
            ("type seen at every call site", ("tl.use:takes", "tl.store:Store.save")),
            ("super()", ("tl.store:Child.save", "tl.store:Store.save")),
        ]
        for name, edge in cases:
            with self.subTest(name):
                self.assertIn(edge, self.e)

    def test_value_methods_are_builtin_not_unresolved(self):
        names = dict(self.cm["summary"]["top_unresolved_names"])
        for n in ("get", "join", "upper", "strip", "count"):
            with self.subTest(n):
                self.assertNotIn(n, names)

    def test_unique_method_name_is_inferred_not_resolved(self):
        self.assertIn(("tl.use:guess", "tl.store:Store.only_here_xyz"), {(a, b) for a, b, _ in self.cm["inferred_calls"]})
        self.assertNotIn(("tl.use:guess", "tl.store:Store.only_here_xyz"), self.e)
        self.assertEqual(self.cm["summary"]["inferred_edges"], 1)

    def test_coverage_figures(self):
        s = self.cm["summary"]
        self.assertEqual(s["unresolved"], 1)  # only the inferred one stays unresolved
        self.assertGreaterEqual(s["graph_coverage"], s["resolved_ratio"] - 0.2)


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


class LlmApp(unittest.TestCase):
    """The repo's own model client: roles live where the app calls its wrapper, reached through injected deps."""

    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("llm_app")
        cls.llm = {(r.get("kind", "sdk"), r["symbol"]): r for r in cls.cm["profiles"]["llm"]}

    def test_calls_to_the_wrapper_are_the_model_roles(self):
        self.assertEqual(set(self.llm), {("sdk", "ai.client:LLMClient.chat"), ("sdk", "ai.decide:decide"),
                                         ("gateway", "ai.judge:run_judge"), ("gateway", "ai.guard:Guard.check")})
        judge = self.llm[("gateway", "ai.judge:run_judge")]
        self.assertEqual((judge["label"], judge["call"], judge["output_schema"], judge["messages"]),
                         ("judge", "LLMClient.chat_json", "Verdict", "ai.judge:judge_messages"))
        self.assertEqual(judge["settings"], {"model": "'demo-judge'", "temperature": "0"})
        self.assertEqual(self.llm[("sdk", "ai.decide:decide")]["provider"], "OpenRouter")  # HTTP to a model host

    def test_injected_callable_binds_to_the_function_passed_in(self):
        self.assertEqual([b[:2] for b in self.cm["binds"]], [["ai.deps:Deps.make_llm", "ai.wiring:build_deps.make_llm"]])
        self.assertIn(("ai.judge:run_judge", "ai.wiring:build_deps.make_llm"), edges(self.cm))

    def test_attribute_typed_from_the_init_parameter(self):
        self.assertIn(("ai.guard:Guard.check", "ai.client:LLMClient.chat"), edges(self.cm))  # self.llm = llm: LLMClient

    def test_bare_import_from_a_script_folder(self):
        self.assertIn(("scripts.run:main", "scripts.helpers:ping"), edges(self.cm))

    def test_draft_makes_one_card_per_role_plus_the_gateway(self):
        import draft
        cards = {r["id"]: r for r in draft.propose_roles(self.cm, 6) if r["kind"] == "model"}
        self.assertEqual(set(cards), {"model-judge", "model-guard", "model-gateway"})
        self.assertTrue(cards["model-judge"]["output"].startswith("Verdict"))


class LibPkg(unittest.TestCase):
    """A library: entry points are its exported API and console scripts; active-record models; SurrealQL schema."""

    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("lib_pkg")

    def test_library_api_console_scripts_and_scripts_are_entries(self):
        import draft
        self.assertEqual({(s, k, t) for s, k, t in draft.entry_points(self.cm)},
                         {("scripts.seed:<module>", "cli", "python scripts/seed.py"),  # top-level script code is a symbol
                          ("lib.cli:run", "cli", "libtool"),                              # [project.scripts]
                          ("lib.agents:Base.run", "api", "Agent().run()"),                 # __all__ class, method via its base
                          ("lib.chain:ask", "api", "ask()")})                              # re-exported by lib/__init__.py

    def test_virtual_call_reaches_the_override(self):
        # Base.run calls self.step(): the base's step only raises, Agent.step is what runs
        self.assertIn(["lib.agents:Base.run", "lib.agents:Agent.step", 11], self.cm["override_calls"])
        import draft
        g = draft.Graph(self.cm)
        self.assertIn("lib.agents:Agent.step", g.chain("lib.agents:Base.run"))

    def test_active_record_models_on_a_surrealql_schema(self):
        self.assertEqual(self.cm["tables"], ["note"])  # DEFINE TABLE; ApiModel(Model) is this repo's Model, not a table
        by = {(e["symbol"], op): e[op] for e in self.cm["sql"] for op in ("insert", "update", "delete", "read") if e.get(op)}
        self.assertEqual(by, {("lib.store:add_note", "insert"): ["note"], ("lib.store:list_notes", "read"): ["note"]})

    def test_model_calls_through_inheritance_retry_wrappers_and_langchain(self):
        llm = {(r.get("kind", "sdk"), r["symbol"]) for r in self.cm["profiles"]["llm"]}
        self.assertEqual(llm, {("sdk", "lib.models:OpenAIModel.generate"),  # SDK method handed to self.retry(...)
                               ("gateway", "lib.agents:Agent.step"),       # self.model (typed in Base) → Model.generate
                               ("sdk", "lib.chain:ask")})                  # llm.invoke(...)


class StreamlitApp(unittest.TestCase):
    """A script-style UI: widgets are the entry points; SQLModel writes go through a @contextmanager session."""

    @classmethod
    def setUpClass(cls):
        cls.cm = code_map("streamlit_app")

    def test_contextmanager_session_resolves(self):
        # `with session_scope(e) as s:` binds the Session that `-> Iterator[Session]` yields
        self.assertEqual(self.cm["summary"]["unresolved"], 0)

    def test_orm_session_calls_name_the_exact_table(self):
        by = {(e["symbol"], op): e[op] for e in self.cm["sql"] for op in ("insert", "update", "delete", "read") if e.get(op)}
        self.assertEqual(by, {("notes.store:save_note", "insert"): ["note"],
                              ("notes.store:delete_note", "delete"): ["note"],  # not tag: only `row` is deleted
                              ("notes.store:delete_note", "read"): ["note", "tag"]})  # read, then deleted: both

    def test_third_party_packages_per_module_for_layer_rules(self):
        self.assertEqual(self.cm["modules"]["app.views.notes"]["packages"], ["streamlit"])
        self.assertNotIn("streamlit", self.cm["modules"]["notes.store"]["packages"])

    def test_pydantic_secret_is_not_aws(self):
        self.assertEqual(self.cm["external"], [])

    def test_widgets_become_journey_entries(self):
        import draft
        self.assertEqual({(s, k) for s, k, _ in draft.entry_points(self.cm)},
                         {("notes.store:save_note", "ui"), ("app.views.notes:delete_form", "ui")})
        self.assertIn({"kind": "page", "symbol": "app.main:<module>", "line": 3, "page": "views/notes.py"},
                      self.cm["profiles"]["ui"])


if __name__ == "__main__":
    unittest.main()
