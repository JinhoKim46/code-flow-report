"""The system map: one spec, four outputs; the feature catalog; and the map inside the built report."""
import json
import unittest

from _support import FIXTURES, code_map
from test_cli import run, setup

import features
import system_map as sm
import architecture
import build as builder


def tiny(**over):
    spec = {
        "title": "Tiny",
        "layers": [{"id": "ui", "label": "UI", "color": "ui"}, {"id": "core", "label": "Core", "color": "core"}],
        "nodes": [{"id": "home", "layer": "ui", "name": "Home", "sub": "app/views"},
                  {"id": "engine", "layer": "core", "name": "Engine", "tags": ["R1"]}],
        "edges": [["home", "engine", "start"]],
        "steps": [{"title": "Start", "nodes": ["home", "engine"], "edges": [["home", "engine"]], "text": "Go"}],
    }
    spec.update(over)
    return spec


class Validate(unittest.TestCase):
    def test_clean_spec_has_no_problems(self):
        self.assertEqual(sm.validate(tiny()), [])

    def test_unknown_endpoint_layer_and_step_edge_are_named(self):
        bad = tiny(edges=[["home", "ghost"]],
                   nodes=[{"id": "home", "layer": "nowhere", "name": "Home"}, {"id": "engine", "layer": "core", "name": "Engine"}],
                   steps=[{"title": "S", "nodes": ["engine"], "edges": [["engine", "home"]]}])
        problems = " | ".join(sm.validate(bad))
        self.assertIn("unknown layer 'nowhere'", problems)
        self.assertIn("unknown node 'ghost'", problems)
        self.assertIn("edge engine -> home, which is not in the map", problems)

    def test_load_raises_with_every_problem(self):
        with self.assertRaises(ValueError) as ctx:
            sm.load(tiny(edges=[["home", "x"], ["y", "engine"]]))
        self.assertEqual(str(ctx.exception).count("unknown node"), 2)


class Layout(unittest.TestCase):
    def test_every_node_gets_a_position_inside_the_view(self):
        spec = sm.load(tiny())
        x0, y0, w, h = spec["view"]
        for n in spec["nodes"]:
            self.assertTrue(x0 <= n["x"] <= x0 + w and y0 <= n["y"] <= y0 + h)
        self.assertLess(spec["nodes"][0]["y"], spec["nodes"][1]["y"], "layers are rows, in layer order")

    def test_explicit_positions_are_kept(self):
        spec = sm.load(tiny(nodes=[{"id": "home", "layer": "ui", "name": "Home", "x": 500, "y": 70},
                                   {"id": "engine", "layer": "core", "name": "Engine"}]))
        self.assertEqual((spec["nodes"][0]["x"], spec["nodes"][0]["y"]), (500, 70))


class Mermaid(unittest.TestCase):
    def test_subgraphs_edges_and_quotes(self):
        spec = sm.load(tiny(nodes=[{"id": "home", "layer": "ui", "name": 'Home "main"', "sub": "a|b"},
                                   {"id": "engine", "layer": "core", "name": "Engine"}]))
        text = sm.to_mermaid(spec)
        self.assertTrue(text.startswith("flowchart LR"))
        self.assertIn('subgraph n_L_ui["UI"]', text)
        self.assertIn("n_home -->|\"start\"| n_engine", text)
        self.assertIn("#quot;main#quot;", text)
        self.assertNotIn('"main"', text, "raw quotes would break the node label")
        self.assertIn("classDef ui", text)


class Markdown(unittest.TestCase):
    def test_pr_page_has_chart_table_and_walkthrough(self):
        text = sm.to_markdown(sm.load(tiny()))
        self.assertIn("```mermaid", text)
        self.assertIn("| **Home** | UI |", text)
        self.assertIn("1. **Start** — Go", text)


class Html(unittest.TestCase):
    def test_script_breaking_text_cannot_end_the_data_block(self):
        spec = sm.load(tiny(nodes=[{"id": "home", "layer": "ui", "name": "</script><b>x", "job": "</script>"},
                                   {"id": "engine", "layer": "core", "name": "Engine"}]))
        fragment = sm.to_fragment(spec)
        self.assertEqual(fragment.count("</script>"), 1, "only the closing tag of the data block")
        self.assertIn("data-sysmap", fragment)

    def test_standalone_page_carries_the_component_once(self):
        page = sm.standalone_page(sm.load(tiny()))
        self.assertEqual(page.count('class="sysmap" data-sysmap'), 1)
        self.assertEqual(page.count("<script>"), 1, "the component script, once")
        self.assertIn("<style>", page)
        self.assertIn("data-sysmap", page)

    def test_component_waits_for_the_document(self):
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        self.assertIn('document.readyState === "loading"', js, "the script can sit in <head>")

    # Behaviour (zoom, steady scroll, fade) was checked in headless Chrome; these pin the pieces in place.
    def test_component_zooms_to_what_is_lit_and_keeps_its_shape(self):
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        self.assertIn("function fitTo(", js)
        self.assertIn("const ratio = full[2] / full[3]", js, "the zoomed view keeps the map's shape, so the page height never changes")
        self.assertIn("Math.max(0, Math.min(1,", js, "the animation step is clamped")
        self.assertIn("settle = setTimeout(", js, "the view lands on its target even without animation frames")

    def test_edge_labels_look_for_a_spot_that_covers_no_box(self):
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        self.assertIn("function labelSpot(", js)
        self.assertIn("labelSpot(g.pts,", js, "every edge label is placed through it, not at the bare midpoint")

    def test_clicks_keep_the_map_where_it_was_on_screen(self):
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        self.assertIn("function steady(", js)
        template = (sm.HERE.parent / "assets" / "template.html").read_text(encoding="utf-8")
        self.assertIn("function steadyArch(", template, "the module map does the same")

    def test_back_and_forward_move_between_places_in_the_report(self):
        # Checked in headless Chrome: two jumps, Back twice, Forward once restore hash, selection and scroll.
        template = (sm.HERE.parent / "assets" / "template.html").read_text(encoding="utf-8")
        self.assertIn("history.pushState(", template, "every in-page jump is a history step")
        self.assertIn('window.addEventListener("popstate"', template)
        self.assertIn('document.addEventListener("click", noteLeaving, true)', template,
                      "the place being left is read before click handlers change the selection")

    def test_opening_a_part_is_a_history_step_that_keeps_the_pages_own_fields(self):
        # Checked in headless Chrome, in the report and alone: open, Back, Forward, a report jump and Back.
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        self.assertIn('new CustomEvent("sysmap:navigate"', js, "the page can refresh its own fields first")
        self.assertIn("{ ...(history.state || {}) }", js, "the map adds its field and keeps the page's")
        self.assertIn('window.addEventListener("popstate"', js)
        template = (sm.HERE.parent / "assets" / "template.html").read_text(encoding="utf-8")
        self.assertIn('document.addEventListener("sysmap:navigate"', template)

    def test_the_page_fade_slider_reaches_the_map(self):
        css = (sm.HERE / "system_map.css").read_text(encoding="utf-8")
        self.assertIn("opacity: var(--fade, .28)", css)
        self.assertIn("align-items: start", css, "the map frame does not stretch to the panel's height")


class FromStructure(unittest.TestCase):
    def test_roles_follow_the_code_not_the_folder_names(self):
        cm = code_map("llm_app")
        roles = architecture.roles(cm)
        self.assertEqual(set(roles), set(cm["modules"]), "every module gets a role")
        self.assertEqual(roles["ai.routes"] if "ai.routes" in roles else "entry", "entry")

    def test_map_is_valid_and_has_external_services(self):
        cm = code_map("llm_app")
        spec = sm.load(architecture.map_spec(cm, "en", "llm", purposes={}))
        self.assertTrue(any(n["id"].startswith("ext-") for n in spec["nodes"]), "external services become parts")
        self.assertTrue(all(e[2] for e in spec["edges"]), "every connection says how many calls it counts")

    def test_any_fixture_gives_a_valid_map(self):
        for name in ("llm_app", "fastapi_llm", "flask_app", "celery_jobs", "lib_pkg", "oo_lib",
                     "streamlit_app", "django_site", "src_layout_lib", "k8s_app", "tf_aws_app"):
            with self.subTest(fixture=name):
                spec = architecture.map_spec(code_map(name), "en", name)
                self.assertEqual(sm.validate(spec), [])
                self.assertTrue(spec["nodes"])

    def test_a_library_uses_its_roots_as_entry_points(self):
        cm = code_map("oo_lib")
        roles = architecture.roles(cm)
        self.assertIn("entry", set(roles.values()))

    def test_registered_pages_and_their_launcher_are_entry_points(self):
        roles = architecture.roles(code_map("streamlit_app"))
        self.assertEqual(roles["app.main"], "entry", "the file that registers the pages is the one people run")
        self.assertEqual(roles["app.views.notes"], "entry", "a page registered by path is its own entry point")

    def test_parts_sharing_a_last_segment_get_unique_names(self):
        mods = ("interview_app.lab.run", "app.lab.run", "views.home", "app.views.page", "app.main")
        cm = {"modules": {m: {"file": m.replace(".", "/") + ".py", "lines": 10} for m in mods}}
        spec = architecture.map_spec(cm, "en", "x")
        names = {n["package"]: n["name"] for n in spec["nodes"]}
        self.assertEqual(names["interview_app.lab"], "interview_app.lab")
        self.assertEqual(names["app.lab"], "app.lab")
        self.assertEqual(names["views"], "views")
        self.assertEqual(names["app.views"], "app.views")
        self.assertEqual(names["app"], "app")
        self.assertEqual(sm.validate(spec), [])
        self.assertEqual(architecture.short_names(["a.b.c", "x.b.c", "y.c"]), {"a.b.c": "a.b.c", "x.b.c": "x.b.c", "y.c": "y.c"})

    def test_long_names_are_cut_to_fit_a_box(self):
        pkg = "a_really_long_package_name_for_a_box"
        cm = {"modules": {f"{pkg}.mod": {"file": f"{pkg}/mod.py", "lines": 5}}}
        node = architecture.map_spec(cm, "en", "x")["nodes"][0]
        self.assertLessEqual(len(node["name"]), architecture.NAME_MAX)
        self.assertTrue(node["name"].endswith("…"))
        self.assertEqual(node["package"], pkg)
        for spec in (architecture.map_spec(code_map(n), "en", n) for n in ("llm_app", "django_site")):
            self.assertTrue(all(len(n["name"]) <= architecture.NAME_MAX for n in spec["nodes"]))

    def test_data_and_external_layers_have_distinct_colours(self):
        import re
        spec = architecture.map_spec(code_map("llm_app"), "en", "x")
        color = {layer["id"]: layer["color"] for layer in spec["layers"]}
        self.assertNotEqual(color.get("data", "data"), color["external"])
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        fallback = dict(re.findall(r'(\w+): "(#[0-9a-f]{6})"', re.search(r"FALLBACK = \{([^}]*)\}", js).group(1)))
        css = (sm.HERE / "system_map.css").read_text(encoding="utf-8")
        palettes = [dict(re.findall(r"--sm-(\w+): (#[0-9a-f]{6})", line)) for line in css.splitlines() if "--sm-data" in line]
        self.assertEqual(len(palettes), 3, "light, dark (system) and dark (forced)")
        for pal in [fallback] + palettes:
            self.assertNotEqual(pal["data"], pal["svc"])
            self.assertNotEqual(pal["any"], pal["lab"])
            self.assertEqual(len(set(pal[k] for k in ("ui", "core", "svc", "lab", "data", "any"))), 6)
        self.assertEqual(fallback["data"], palettes[0]["data"])
        self.assertEqual(fallback["svc"], palettes[0]["svc"])

    def test_korean_map_has_korean_layer_names(self):
        spec = architecture.map_spec(code_map("llm_app"), "ko", "x")
        self.assertIn(spec["layers"][0]["label"], {"진입점", "스크립트", "핵심 로직", "데이터 접근", "지원", "외부 서비스"})


class PartText(unittest.TestCase):
    """Each part's job and facts come from the narrative's module notes, or say plainly they are missing."""

    def test_a_described_part_gets_its_purposes_and_capabilities(self):
        spec = architecture.map_spec(
            code_map("llm_app"), "en", "x",
            purposes={"ai.client": "The one gateway for model calls.", "ai.judge": "Scores answers."},
            capabilities={"ai.client": "Sends chat requests; retries once", "ai.judge": ["Builds the judge prompt", "Parses"]})
        part = next(n for n in spec["nodes"] if n.get("package") == "ai")
        self.assertIn("The one gateway for model calls.", part["job"])
        self.assertIn("Scores answers.", part["job"])
        self.assertIn("Sends chat requests", part["facts"])
        self.assertIn("Builds the judge prompt", part["facts"])
        self.assertNotIn("retries once", part["facts"], "only the first capability of each module")
        self.assertEqual(sm.validate(spec), [])

    def test_does_stands_in_for_a_missing_purpose(self):
        job = architecture.part_job(["a", "b"], {}, {"a": "Loads settings; validates them"}, "en")
        self.assertEqual(job, "Loads settings.")

    def test_a_job_is_short_and_deduplicated(self):
        purposes = {m: "Same sentence." for m in "abc"} | {"d": "Two.", "e": "Three.", "f": "Four."}
        self.assertEqual(architecture.part_job(list("abcdef"), purposes, {}, "en"), "Same sentence. Two. Three.")

    def test_an_undescribed_part_says_so(self):
        spec = architecture.map_spec(code_map("llm_app"), "en", "x")
        part = next(n for n in spec["nodes"] if n.get("package") == "ai")
        self.assertEqual(part["job"], f"Not described yet: {part['sub'].split()[0]} modules.")
        ko = architecture.map_spec(code_map("llm_app"), "ko", "x")
        self.assertTrue(all(n["job"] for n in ko["nodes"]), "every part has a job")
        self.assertIn("아직 설명 없음", next(n for n in ko["nodes"] if n.get("package") == "ai")["job"])

    def test_external_parts_name_their_call_sites(self):
        spec = architecture.map_spec(code_map("llm_app"), "en", "x")
        openai = next(n for n in spec["nodes"] if n["id"] == "ext-openai-api")
        self.assertIn("ai.client", openai["job"])
        self.assertIn("openai.OpenAI().chat.completions.create", openai["job"])
        httpx = next(n for n in spec["nodes"] if n["id"] == "ext-http-httpx")
        self.assertIn("httpx.post", httpx["job"])
        self.assertNotIn("json", httpx["job"], "an accessor on the result is not what the service is used for")

    def test_module_texts_reads_purpose_and_does(self):
        purposes, caps = builder.module_texts({"module_notes": {
            "a": {"purpose": "P.", "does": "D1; D2"}, "b": {"purpose": "TODO: write", "does": "TODO"}}})
        self.assertEqual(purposes, {"a": "P."})
        self.assertEqual(caps, {"a": "D1; D2"})


class DrillDown(unittest.TestCase):
    def test_every_code_part_opens_onto_its_modules_and_neighbours(self):
        cm = code_map("flask_app")
        spec = sm.load(architecture.map_spec(cm, "en", "x"))
        parts = [n for n in spec["nodes"] if not n["id"].startswith("ext-")]
        self.assertTrue(parts)
        for part in parts:
            inside = part["children"]
            modules = [n for n in inside["nodes"] if n["layer"] == "modules"]
            self.assertTrue(modules, part["id"])
            self.assertTrue(all(n["package"].startswith(part["package"].split(".")[0]) for n in modules))
            self.assertIn("view", inside, "the inside view is laid out too")

    def test_a_broken_inside_view_is_reported_with_its_part(self):
        spec = tiny(nodes=[{"id": "home", "layer": "ui", "name": "Home",
                            "children": {"title": "in", "layers": [{"id": "m", "label": "M"}],
                                         "nodes": [{"id": "a", "layer": "m", "name": "A"}], "edges": [["a", "ghost"]]}},
                           {"id": "engine", "layer": "core", "name": "Engine"}])
        self.assertTrue(any(p.startswith("inside 'home':") and "ghost" in p for p in sm.validate(spec)))

    def test_a_wide_layer_wraps_onto_more_rows(self):
        many = [{"id": f"n{i}", "layer": "ui", "name": f"N{i}"} for i in range(sm.MAX_COLS + 2)]
        spec = sm.load(tiny(nodes=many + [{"id": "engine", "layer": "core", "name": "Engine"}], edges=[], steps=[]))
        ys = {n["id"]: n["y"] for n in spec["nodes"]}
        self.assertEqual(len({ys[f"n{i}"] for i in range(sm.MAX_COLS + 2)}), 2, "the 7th part starts a second row")
        self.assertGreater(ys["engine"], ys[f"n{sm.MAX_COLS}"], "the next layer comes after the wrapped rows")

    def test_one_call_is_singular(self):
        self.assertEqual(architecture.calls_label(1, "en"), "1 call")
        self.assertEqual(architecture.calls_label(3, "en"), "3 calls")
        self.assertEqual(architecture.calls_label(3, "ko"), "3회")

    def test_component_opens_parts_and_places_lit_labels_again(self):
        js = (sm.HERE / "system_map.js").read_text(encoding="utf-8")
        self.assertIn("function mount(", js)
        self.assertIn("data-open", js)
        self.assertIn("data-up", js)
        self.assertIn("function placeLabels(", js, "lit labels avoid boxes and each other")


class Features(unittest.TestCase):
    def test_defaults_and_auto_detection(self):
        self.assertTrue(features.enabled({}, "system_map"))
        self.assertFalse(features.enabled({}, "staleness_test"))
        self.assertFalse(features.enabled({}, "model_calls", {}))
        self.assertTrue(features.enabled({}, "model_calls", {"llm": True}))

    def test_saving_a_plan_leaves_auto_features_to_the_repo(self):
        repo = setup("llm_app")
        code, out = run(repo, "plan", "--select", "system_map", "--save")
        self.assertEqual(code, 0, out)
        cfg = (repo / "docs" / "code-flow" / "codeflow.toml").read_text(encoding="utf-8")
        self.assertIn("system_map = true", cfg)
        self.assertNotIn("model_calls", cfg)

    def test_saved_choice_wins_over_default(self):
        self.assertFalse(features.enabled({"features": {"system_map": False}}, "system_map"))
        self.assertTrue(features.enabled({"features": {"staleness_test": True}}, "staleness_test"))

    def test_plan_lists_every_feature_and_marks_the_selection(self):
        text = features.plan(["system_map"], "en")
        self.assertIn("[x] System map", text)
        self.assertIn("[ ] Findings", text)
        self.assertIn("→ report section; system-map.html", text)

    def test_catalog_has_text_in_both_languages(self):
        for lang in ("en", "ko"):
            for f in features.catalog(lang):
                self.assertTrue(f["title"] and f["preview"], f["id"])


class InReport(unittest.TestCase):
    def test_built_report_embeds_the_map_and_stays_offline(self):
        repo = setup("llm_app")
        html = (repo / "docs" / "code-flow" / "code-flow-report.html").read_text(encoding="utf-8")
        self.assertIn("data-sysmap", html)
        self.assertNotIn("<!--__SYSTEM_MAP", html)
        self.assertNotRegex(html, r'src="https?://')

    def test_switching_the_feature_off_removes_it(self):
        repo = setup("llm_app")
        cfg = repo / "docs" / "code-flow" / "codeflow.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8") + "\n[features]\nsystem_map = false\n", encoding="utf-8")
        code, out = run(repo, "build")
        self.assertEqual(code, 0, out)
        html = (repo / "docs" / "code-flow" / "code-flow-report.html").read_text(encoding="utf-8")
        self.assertNotIn("data-sysmap", html)

    def test_unticked_sections_are_hidden_and_pr_files_follow_the_choice(self):
        repo = setup("llm_app")
        code, out = run(repo, "plan", "--select", "system_map", "--save")
        self.assertEqual(code, 0, out)
        code, out = run(repo, "build")
        self.assertEqual(code, 0, out)
        html = (repo / "docs" / "code-flow" / "code-flow-report.html").read_text(encoding="utf-8")
        self.assertIn('<section id="journeys" hidden>', html)
        self.assertIn('<section id="findings" hidden>', html)
        self.assertNotIn('<section id="arch" hidden>', html)
        self.assertFalse((repo / "docs" / "code-flow" / "system-map.md").exists(), "pr_output is off")

    def test_pr_files_are_written_with_the_report(self):
        repo = setup("llm_app")
        self.assertTrue((repo / "docs" / "code-flow" / "system-map.md").exists())
        self.assertTrue((repo / "docs" / "code-flow" / "system-map.mmd").exists())

    def test_a_broken_hand_written_map_fails_the_build(self):
        repo = setup("llm_app")
        spec = {"title": "Mine", "layers": [{"id": "a", "label": "A"}], "nodes": [{"id": "x", "layer": "a", "name": "X"}],
                "edges": [["x", "missing"]]}
        (repo / "docs" / "code-flow" / "system_map.json").write_text(json.dumps(spec), encoding="utf-8")
        code, out = run(repo, "build")
        self.assertEqual(code, 1, out)
        self.assertIn("system map:", out)
        self.assertIn("missing", out)

    def test_system_map_command_writes_the_three_outputs(self):
        repo = setup("llm_app")
        code, out = run(repo, "system-map", "--out", str(repo / "pr"))
        self.assertEqual(code, 0, out)
        for name in ("system-map.html", "system-map.md", "system-map.mmd"):
            self.assertTrue((repo / "pr" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
