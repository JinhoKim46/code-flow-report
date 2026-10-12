# System map spec

The system map is one reusable component with four outputs: an interactive HTML block (for the report, or any page), a standalone HTML file, a Mermaid flowchart (GitHub draws it in PR descriptions), and a Markdown page (Mermaid plus a parts table).

The report builds its map from the code by default. Write `docs/code-flow/system_map.json` only to improve it. `codeflow.py system-map --write-spec` writes the derived spec there to edit.

## Fields

```json
{
  "title": "Interview Helper — system map",
  "lang": "en",
  "layers": [{"id": "ui", "label": "UI (Streamlit pages)", "color": "ui"}],
  "nodes": [{"id": "home", "layer": "ui", "name": "Home", "sub": "app/views",
             "job": "What it does, in one or two sentences.",
             "files": ["app/views/home.py"], "facts": ["A fact a reviewer would check"],
             "tags": ["R2"]}],
  "edges": [["home", "history", "sessions, progress"]],
  "steps": [{"title": "Open Home", "nodes": ["home", "history"],
             "edges": [["home", "history"]], "text": "What happens in this step."}]
}
```

| Field | Required | Meaning |
|---|---|---|
| `layers[].id`, `label` | yes | Rows of the map, in order. `color`: `ui`, `core`, `svc`, `lab` (or anything, which gets the neutral colour). |
| `nodes[].id`, `layer`, `name` | yes | A part. `layer` must be a layer id. |
| `nodes[].sub`, `job`, `files`, `facts`, `tags` | no | Shown in the panel. Clicking a tag lights every part that carries it. |
| `nodes[].x`, `y` | no | Position in the SVG. Without them the map lays out one row per layer. |
| `edges` | no | `[from, to, label]`: an arrow from the caller to the callee. Every end must be a node id. |
| `nodes[].children` | no | The part's inside view: a spec of the same shape (layers, nodes, edges). The map shows a "Look inside" button and opens it on a double click; the trail goes back up. |
| `steps` | no | Walkthrough: each lights its `nodes` and `edges`. Without `edges` it lights the edges between its nodes. A step edge must be an edge of the map. |

## Rules the build enforces

- Ids are unique within their kind. Every node names a known layer. Every edge and step names known nodes, and every step edge exists in `edges`.
- A problem fails `build` and lists every problem at once (`system map: …`), so the report never ships a broken map.

## The derived map

Without a `system_map.json`, `scripts/architecture.py` builds the map from the code alone. Roles: **entry** (routes, UI pages, jobs, cloud functions), **script** (runnable files), **data** (reads or writes a table), **logic** (reached from an entry), **support** (reached from none), plus one part per **external** service. A library with no entry point uses its roots. Each part opens onto its modules, with its callers above and its callees below.

## Using it outside the report

- `codeflow.py system-map --format md` (or `mermaid`, or `html`) writes the files. Paste the Markdown into a PR description.
- Opening and leaving a part are browser-history steps. The map adds only its own field (`sysmap0`, `sysmap1`, … by order on the page) to an entry and fires `sysmap:navigate` (bubbling, `detail.state` is the entry about to be pushed) so a host page can add its own fields first.
- `scripts/system_map.py` has no dependency on the report: `load(spec)`, `to_fragment(spec)` (the block) and `assets_html()` (its CSS and JS, once per page) can be used from any Python project.
