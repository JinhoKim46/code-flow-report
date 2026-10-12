/* System map component. Renders every [data-sysmap] block from its JSON spec (see system_map.py).
   Click or Enter a part: its files, facts, tags and neighbours light up, the rest fades, and the view
   zooms to what is lit. A part with an inside view opens on "Look inside" or a double click; the trail
   above the map goes back up. Click a tag: every part that carries it. Walkthrough steps light one
   path at a time. Esc clears. No dependencies; colours come from --sm-* tokens with fallbacks. */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const W = 150, H = 52;
  const FALLBACK = { ui: "#3b5b92", core: "#0b6e69", svc: "#a8436e", lab: "#8a5a2b", data: "#5f7a1e", any: "#6e7378" };
  let uid = 0;

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const svgEl = (tag, attrs = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  };
  const colorOf = layer => {
    const c = FALLBACK[layer.color] ? layer.color : "any";
    return `var(--sm-${c}, ${FALLBACK[c]})`;
  };
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- geometry: a curve between boxes; a same-row link arcs underneath so it crosses nothing
  function geometry(A, B) {
    let pts;
    if (Math.abs(A.y - B.y) < 10) {
      const y0 = A.y + H / 2, dir = B.x > A.x ? 1 : -1;
      const x1 = A.x + dir * 20, x2 = B.x - dir * 20, depth = 34 + Math.abs(B.x - A.x) * 0.08;
      pts = [[x1, y0], [x1, y0 + depth], [x2, y0 + depth], [x2, y0 + 2]];
    } else {
      const down = B.y > A.y;
      const y1 = A.y + (down ? H / 2 : -H / 2), y2 = B.y + (down ? -H / 2 : H / 2), my = (y1 + y2) / 2;
      pts = [[A.x, y1], [A.x, my], [B.x, my], [B.x, y2]];
    }
    const [a, b, c, d] = pts;
    return { d: `M${a[0]} ${a[1]} C ${b[0]} ${b[1]}, ${c[0]} ${c[1]}, ${d[0]} ${d[1]}`, pts };
  }
  function bezier(pts, t) {
    const u = 1 - t, w = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
    return [0, 1].map(i => w.reduce((sum, wi, k) => sum + wi * pts[k][i], 0));
  }
  // A label goes on its curve, at the first point (middle first) that covers no box and no label
  // already placed. With no free point, the point covering the fewest wins.
  const LABEL_TS = [0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78, 0.15, 0.85];
  function labelSpot(pts, text, obstacles) {
    const w = text.length * 6.4 + 8, h = 14;
    const rectAt = (x, y) => [x - w / 2, y - h + 3, x + w / 2, y + 4];
    const covered = r => obstacles.filter(b => r[0] < b[2] && r[2] > b[0] && r[1] < b[3] && r[3] > b[1]).length;
    let best = null;
    for (const t of LABEL_TS) {
      const [x, y0] = bezier(pts, t), y = y0 - 2, r = rectAt(x, y), n = covered(r);
      if (n === 0) return { x, y, rect: r };
      if (!best || n < best.n) best = { x, y, rect: r, n };
    }
    return best;
  }

  function init(root, index) {
    const dataEl = root.querySelector("script.sysmap-data");
    if (!dataEl) return;
    const top = JSON.parse(dataEl.textContent);
    const T = top.labels;
    const trail = [];  // the specs above the one shown, top first
    const path = [];   // the ids of the parts opened to get here, top first
    const key = "sysmap" + index;  // this map's own field in the browser's history entries
    let view = null;

    // ---- one view: draws `spec` into the root and returns what the events need
    function mount(spec) {
      const id = ++uid;
      const byId = Object.fromEntries(spec.nodes.map(n => [n.id, n]));
      const layerById = Object.fromEntries(spec.layers.map(l => [l.id, l]));
      const outs = {}, ins = {}, tags = {};
      spec.nodes.forEach(n => { outs[n.id] = []; ins[n.id] = []; (n.tags || []).forEach(t => (tags[t] = tags[t] || []).push(n.id)); });
      spec.edges.forEach((e, i) => { outs[e[0]].push(i); ins[e[1]].push(i); });
      const steps = spec.steps || [];

      root.replaceChildren();
      root.classList.add("sysmap--ready");
      root.classList.remove("sm-dim");
      const trailEl = document.createElement("nav");
      trailEl.className = "sm-trail";
      trailEl.setAttribute("aria-label", T.trail);
      const banner = document.createElement("div");
      banner.className = "sm-banner";
      banner.setAttribute("aria-live", "polite");
      const stepsEl = document.createElement("div");
      stepsEl.className = "sm-steps";
      const body = document.createElement("div");
      body.className = "sm-body";
      const frame = document.createElement("div");
      frame.className = "sm-frame";
      const panel = document.createElement("aside");
      panel.className = "sm-panel";
      panel.setAttribute("aria-live", "polite");
      body.append(frame, panel);
      const legend = document.createElement("div");
      legend.className = "sm-legend";
      legend.innerHTML = spec.layers.map(l => `<span><i style="background:${colorOf(l)}"></i>${esc(l.label)}</span>`).join("")
        + `<span class="sm-muted">${esc(T.hint)}</span>`;
      if (trail.length) {
        trailEl.innerHTML = trail.map((s, i) => `<button type="button" class="sm-chip" data-up="${i}">${esc(s.title)}</button>`).join(" › ")
          + ` › <strong>${esc(spec.title)}</strong>`;
      }
      root.append(...(trail.length ? [trailEl] : []), banner, ...(steps.length ? [stepsEl] : []), body, legend);

      // ---- svg
      const svg = svgEl("svg", { viewBox: spec.view.join(" "), role: "img", "aria-label": spec.title, class: "sm-svg" });
      const defs = svgEl("defs");
      [["ah", "sm-ah"], ["ahhl", "sm-ah-hl"]].forEach(([mid, cls]) => {
        const m = svgEl("marker", { id: `sm${id}-${mid}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
        m.appendChild(svgEl("path", { d: "M0 0L10 5L0 10z", class: cls }));
        defs.appendChild(m);
      });
      svg.appendChild(defs);
      const edgeLayer = svgEl("g"), labelLayer = svgEl("g"), nodeLayer = svgEl("g");
      svg.append(edgeLayer, nodeLayer, labelLayer);
      frame.appendChild(svg);

      const boxes = spec.nodes.map(n => [n.x - W / 2 - 3, n.y - H / 2 - 3, n.x + W / 2 + 3, n.y + H / 2 + 3]);
      const edgeEls = spec.edges.map(e => {
        const g = geometry(byId[e[0]], byId[e[1]]);
        const p = svgEl("path", { d: g.d, class: "sm-edge", "marker-end": `url(#sm${id}-ah)` });
        const spot = labelSpot(g.pts, e[2] || "", boxes);
        const t = svgEl("text", { x: spot.x, y: spot.y, "text-anchor": "middle", class: "sm-edge-label" }, e[2] || "");
        edgeLayer.appendChild(p);
        labelLayer.appendChild(t);
        return { p, t, pts: g.pts, weight: parseInt(e[2], 10) || 0 };
      });

      const nodeEls = {};
      spec.nodes.forEach(n => {
        const g = svgEl("g", { class: "sm-node" + (n.children ? " sm-has-inside" : ""), tabindex: "0", role: "button", "aria-label": `${n.name}, ${layerById[n.layer].label}`, "data-node": n.id });
        g.appendChild(svgEl("rect", { class: "sm-box", x: n.x - W / 2, y: n.y - H / 2, width: W, height: H, rx: 8 }));
        g.appendChild(svgEl("rect", { class: "sm-bar", x: n.x - W / 2, y: n.y - H / 2 + 8, width: 4, height: H - 16, rx: 2, fill: colorOf(layerById[n.layer]) }));
        const size = n.name.length > 18 ? 11 : 13.5;  // a long name gets a smaller font so it stays inside the box
        g.appendChild(svgEl("text", { x: n.x + 4, y: n.sub ? n.y - 3 : n.y + 5, "text-anchor": "middle", "font-size": size, "font-weight": "600", class: "sm-name" }, n.name));
        if (n.sub) g.appendChild(svgEl("text", { x: n.x + 4, y: n.y + 15, "text-anchor": "middle", "font-size": "9.5", class: "sm-sub" }, n.sub));
        nodeLayer.appendChild(g);
        nodeEls[n.id] = g;
      });

      // ---- labels: only lit ones show, so they are placed again on every change, heaviest first,
      // each one avoiding the boxes and the labels already placed
      function placeLabels() {
        const placed = boxes.slice();
        edgeEls.map((e, i) => [e, i]).filter(([e]) => e.p.classList.contains("sm-hl"))
          .sort((a, b) => b[0].weight - a[0].weight)
          .forEach(([e, i]) => {
            const spot = labelSpot(e.pts, spec.edges[i][2] || "", placed);
            e.t.setAttribute("x", spot.x);
            e.t.setAttribute("y", spot.y);
            placed.push(spot.rect);
          });
      }

      // ---- state
      let current = -1;
      function reset() {
        root.classList.remove("sm-dim");
        Object.values(nodeEls).forEach(g => g.classList.remove("sm-sel", "sm-hl", "sm-gr"));
        edgeEls.forEach(({ p, t }) => { p.classList.remove("sm-hl"); p.setAttribute("marker-end", `url(#sm${id}-ah)`); t.classList.remove("sm-hl"); });
      }
      function lightEdge(i) {
        const { p, t } = edgeEls[i];
        p.classList.add("sm-hl");
        p.setAttribute("marker-end", `url(#sm${id}-ahhl)`);
        t.classList.add("sm-hl");
      }

      // ---- view: zoom to what is lit, keep the frame's shape so the page below never moves
      const full = spec.view.slice();
      let shown = full.slice(), anim = 0, settle = 0;
      const MAX_ZOOM = 2.5, PAD = 36;
      function setView(v) { shown = v; svg.setAttribute("viewBox", v.map(n => n.toFixed(1)).join(" ")); }
      function zoomTo(target) {
        cancelAnimationFrame(anim);
        clearTimeout(settle);
        if (reduceMotion) { setView(target); return; }
        // if frames never come (a background tab, a print, a headless run), land on the target anyway
        settle = setTimeout(() => { cancelAnimationFrame(anim); setView(target); }, 340);
        const from = shown.slice(), t0 = performance.now(), ms = 280;
        const tick = () => {
          // clamp: a frame timestamp can come from a different clock than t0, and a k outside 0..1 extrapolates
          const k = Math.max(0, Math.min(1, (performance.now() - t0) / ms)), ease = 1 - Math.pow(1 - k, 3);
          setView(from.map((f, i) => f + (target[i] - f) * ease));
          if (k < 1) anim = requestAnimationFrame(tick);
        };
        anim = requestAnimationFrame(tick);
      }
      function fitTo(ids) {
        if (!ids.length) { zoomTo(full); return; }
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        ids.forEach(nid => { const n = byId[nid]; x0 = Math.min(x0, n.x - W / 2); x1 = Math.max(x1, n.x + W / 2); y0 = Math.min(y0, n.y - H / 2); y1 = Math.max(y1, n.y + H / 2); });
        x0 -= PAD; x1 += PAD; y0 -= PAD; y1 += PAD + 30;  // room for same-row arcs and edge labels below
        let w = x1 - x0, h = y1 - y0;
        const ratio = full[2] / full[3];  // same shape as the whole map: the svg keeps its height
        if (w / h > ratio) { const nh = w / ratio; y0 -= (nh - h) / 2; h = nh; } else { const nw = h * ratio; x0 -= (nw - w) / 2; w = nw; }
        const minW = full[2] / MAX_ZOOM;
        if (w < minW) { const grow = minW / w; x0 -= (minW - w) / 2; y0 -= (h * grow - h) / 2; w = minW; h *= grow; }
        if (w >= full[2]) { zoomTo(full); return; }
        x0 = Math.max(full[0], Math.min(x0, full[0] + full[2] - w));
        y0 = Math.max(full[1], Math.min(y0, full[1] + full[3] - h));
        zoomTo([x0, y0, w, h]);
      }
      function settleView() {
        placeLabels();
        fitTo(Object.keys(nodeEls).filter(nid => nodeEls[nid].matches(".sm-sel, .sm-hl, .sm-gr")));
      }

      function clearAll() {
        reset();
        current = -1;
        banner.innerHTML = `<span class="sm-muted">${esc(T.nothing)}</span>`;
        panel.innerHTML = `<div class="sm-kind">${esc(T.intro)}</div>`;
        renderSteps();
        settleView();
      }
      function select(nid) {
        reset();
        root.classList.add("sm-dim");
        nodeEls[nid].classList.add("sm-sel");
        outs[nid].forEach(i => { lightEdge(i); nodeEls[spec.edges[i][1]].classList.add("sm-hl"); });
        ins[nid].forEach(i => { lightEdge(i); nodeEls[spec.edges[i][0]].classList.add("sm-hl"); });
        const n = byId[nid];
        banner.innerHTML = `<span class="sm-muted">${esc(T.selected)}:</span> <strong>${esc(n.name)}</strong>`
          + ` <span class="sm-muted">· ${outs[nid].length} ${esc(T.outgoing)}, ${ins[nid].length} ${esc(T.incoming)}</span>`
          + (n.children ? ` <button type="button" class="sm-chip sm-open" data-open="${esc(nid)}">${esc(T.open)}</button>` : "")
          + ` <button type="button" class="sm-chip" data-clear>${esc(T.clear)}</button>`;
        panel.innerHTML = nodePanel(n);
        current = -1;
        renderSteps();
        settleView();
      }
      function highlightTag(tag) {
        reset();
        root.classList.add("sm-dim");
        const ids = tags[tag] || [];
        ids.forEach(nid => nodeEls[nid].classList.add("sm-gr"));
        spec.edges.forEach((e, i) => { if (ids.includes(e[0]) && ids.includes(e[1])) lightEdge(i); });
        banner.innerHTML = `<span class="sm-muted">${esc(T.tag)}:</span> <strong>${esc(tag)}</strong>`
          + ` <span class="sm-muted">· ${ids.length}</span>`
          + ` <button type="button" class="sm-chip" data-clear>${esc(T.clear)}</button>`;
        panel.innerHTML = `<div class="sm-kind">${esc(T.tag)}</div><h3>${esc(tag)}</h3>`
          + `<div class="sm-links">${ids.map(nid => `<button type="button" data-node="${esc(nid)}">${esc(byId[nid].name)}</button>`).join("")}</div>`;
        current = -1;
        renderSteps();
        settleView();
      }
      function applyStep(i) {
        const s = steps[i];
        reset();
        root.classList.add("sm-dim");
        s.nodes.forEach(nid => nodeEls[nid].classList.add("sm-hl"));
        const pairs = s.edges || spec.edges.filter(e => s.nodes.includes(e[0]) && s.nodes.includes(e[1])).map(e => [e[0], e[1]]);
        pairs.forEach(([a, b]) => spec.edges.forEach((e, k) => { if (e[0] === a && e[1] === b) lightEdge(k); }));
        current = i;
        banner.innerHTML = `<span class="sm-muted">${esc(T.step)} ${i + 1}:</span> <strong>${esc(s.title)}</strong>`
          + ` <button type="button" class="sm-chip" data-clear>${esc(T.clear)}</button>`;
        panel.innerHTML = `<div class="sm-kind">${esc(T.step)} ${i + 1} ${esc(T.of)} ${steps.length}</div>`
          + `<h3>${esc(s.title)}</h3>${s.text ? `<p>${esc(s.text)}</p>` : ""}`
          + `<div class="sm-links">${s.nodes.map(nid => `<button type="button" data-node="${esc(nid)}">${esc(byId[nid].name)}</button>`).join("")}</div>`;
        renderSteps();
        settleView();
      }
      function renderSteps() {
        if (!steps.length) return;
        if (current < 0) {
          stepsEl.innerHTML = `<span class="sm-muted">${esc(T.walkthrough)}</span> <button type="button" class="sm-btn" data-step="0">${esc(T.start)}</button>`;
          return;
        }
        stepsEl.innerHTML = `<span class="sm-muted">${esc(T.walkthrough)} ${current + 1} ${esc(T.of)} ${steps.length}</span>`
          + ` <button type="button" class="sm-btn" data-prev ${current === 0 ? "disabled" : ""}>${esc(T.prev)}</button>`
          + ` <button type="button" class="sm-btn" data-next ${current === steps.length - 1 ? "disabled" : ""}>${esc(T.next)}</button>`;
      }
      function nodePanel(n) {
        const link = (nid, label) => `<button type="button" data-node="${esc(nid)}">${esc(byId[nid].name)} <span class="sm-muted">${esc(label || "")}</span></button>`;
        const layer = layerById[n.layer];
        const inside = n.children ? n.children.nodes.filter(c => c.layer === "modules").length : 0;
        return `<div class="sm-kind" style="color:${colorOf(layer)}">${esc(layer.label)}</div>
          <h3>${esc(n.name)}</h3>
          ${n.package && n.package !== n.name ? `<code>${esc(n.package)}</code>` : ""}
          ${n.children ? `<button type="button" class="sm-btn sm-open" data-open="${esc(n.id)}">${esc(T.open)} · ${inside} ${esc(T.inside)}</button>` : ""}
          ${n.job ? `<p>${esc(n.job)}</p>` : ""}
          ${n.files && n.files.length ? `<h4>${esc(T.files)}</h4><div class="sm-files">${n.files.map(f => `<code>${esc(f)}</code>`).join("")}</div>` : ""}
          ${n.facts && n.facts.length ? `<h4>${esc(T.facts)}</h4><ul>${n.facts.map(f => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
          ${n.tags && n.tags.length ? `<h4>${esc(T.tags)}</h4><div class="sm-tags">${n.tags.map(t => `<button type="button" class="sm-tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
          ${outs[n.id].length ? `<h4>${esc(T.calls)}</h4><div class="sm-links">${outs[n.id].map(i => link(spec.edges[i][1], spec.edges[i][2])).join("")}</div>` : ""}
          ${ins[n.id].length ? `<h4>${esc(T.called_by)}</h4><div class="sm-links">${ins[n.id].map(i => link(spec.edges[i][0], spec.edges[i][2])).join("")}</div>` : ""}`;
      }

      clearAll();
      return {
        spec, frame, select, highlightTag, clearAll, applyStep,
        stepCount: steps.length, current: () => current,
        inside: nid => byId[nid] && byId[nid].children,
      };
    }

    // ---- events, attached once to the root; they act on whichever view is mounted
    // A click changes the banner, the trail and the panel: scroll back so the map stays where it was on screen.
    function steady(change) {
      const before = view.frame.getBoundingClientRect().top;
      change();
      const moved = view.frame.getBoundingClientRect().top - before;
      if (moved) window.scrollBy({ top: moved, behavior: "instant" });
    }
    function open(nid) {
      const child = view.inside(nid);
      if (!child) return;
      trail.push(view.spec);
      path.push(nid);
      view = mount(child);
    }
    function up(depth) {
      const spec = trail[depth];
      trail.length = depth;
      path.length = depth;
      view = mount(spec);
    }
    // Opening and leaving a part are steps in the browser's history, so Back and Forward move through
    // them. The map adds only its own field to an entry and keeps the page's fields; the
    // "sysmap:navigate" event lets the page refresh its own fields (scroll, selection) first.
    function record() {
      try {
        const detail = { key, path: path.slice(), state: { ...(history.state || {}) } };
        root.dispatchEvent(new CustomEvent("sysmap:navigate", { bubbles: true, detail }));
        detail.state[key] = path.slice();
        history.pushState(detail.state, "");
      } catch (e) { /* no history here (a sandboxed frame): the trail above the map still goes back */ }
    }
    // Show the part reached by opening `ids` from the top; stops at the first id that is not there.
    function goTo(ids) {
      let spec = top;
      trail.length = 0;
      path.length = 0;
      for (const nid of ids) {
        const node = spec.nodes.find(n => n.id === nid);
        if (!node || !node.children) break;
        trail.push(spec);
        path.push(nid);
        spec = node.children;
      }
      view = mount(spec);
    }
    window.addEventListener("popstate", ev => {
      const want = (ev.state && ev.state[key]) || [];
      if (want.join("\u0000") !== path.join("\u0000")) steady(() => goTo(want));
    });
    root.addEventListener("click", e => {
      const t = e.target.closest("[data-node],[data-tag],[data-clear],[data-step],[data-prev],[data-next],[data-open],[data-up]");
      if (!t || !root.contains(t)) return;
      const moves = t.hasAttribute("data-open") || t.hasAttribute("data-up");
      steady(() => {
        if (t.hasAttribute("data-open")) open(t.dataset.open);
        else if (t.hasAttribute("data-up")) up(Number(t.dataset.up));
        else if (t.hasAttribute("data-node")) view.select(t.dataset.node);
        else if (t.hasAttribute("data-tag")) view.highlightTag(t.dataset.tag);
        else if (t.hasAttribute("data-clear")) view.clearAll();
        else if (t.hasAttribute("data-step")) view.applyStep(Number(t.dataset.step));
        else if (t.hasAttribute("data-prev")) view.applyStep(Math.max(0, view.current() - 1));
        else if (t.hasAttribute("data-next")) view.applyStep(Math.min(view.stepCount - 1, view.current() + 1));
      });
      if (moves) record();  // after steady(), so the entry holds the scroll position the reader sees
    });
    root.addEventListener("dblclick", e => {
      const g = e.target.closest(".sm-node");
      if (g && view.inside(g.dataset.node)) { steady(() => open(g.dataset.node)); record(); }
    });
    root.addEventListener("keydown", e => {
      if (e.key === "Escape") {
        const goesUp = trail.length && !root.classList.contains("sm-dim");
        steady(goesUp ? () => up(trail.length - 1) : view.clearAll);
        if (goesUp) record();
        return;
      }
      const g = e.target.closest && e.target.closest(".sm-node");
      if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); steady(() => view.select(g.dataset.node)); }
    });
    // a reload keeps the part that was open
    const saved = history.state && history.state[key];
    if (Array.isArray(saved) && saved.length) goTo(saved);
    else view = mount(top);
  }

  // The script may sit in <head>, before the blocks exist: wait for the document to be parsed.
  const boot = () => document.querySelectorAll("[data-sysmap]").forEach((root, i) => init(root, i));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
