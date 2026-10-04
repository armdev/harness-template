// ForceGraph: a small force-directed graph in SVG, no dependencies.
//   const g = ForceGraph(box, { onClick: node => ..., onOpen: node => ... });
//   g.add([{id, type: "post"|"tag"|"author", label, size}], [{source, target, weight}]);
// Drag a node to move it, drag the background to pan, wheel to zoom. Click calls onClick, double-click onOpen.
"use strict";

function ForceGraph(box, opts = {}) {
  const NS = "http://www.w3.org/2000/svg";
  const nodes = new Map(), edges = new Map();
  let alpha = 1, frame = null, view = { x: 0, y: 0, k: 1 }, focusId = null;

  box.innerHTML = `<div class="legend"><span class="lp">post</span><span class="lt">tag</span><span class="la">author</span></div>
    <div class="tools"><button data-t="fit" title="Fit to view">Fit</button><button data-t="shake" title="Re-layout">Shake</button></div>`;
  const svg = document.createElementNS(NS, "svg");
  const world = document.createElementNS(NS, "g");
  const edgeLayer = document.createElementNS(NS, "g"), nodeLayer = document.createElementNS(NS, "g");
  world.append(edgeLayer, nodeLayer); svg.append(world); box.append(svg);
  box.querySelector('[data-t="fit"]').onclick = () => fit();
  box.querySelector('[data-t="shake"]').onclick = () => { nodes.forEach(n => { n.x += rnd(40); n.y += rnd(40); }); kick(1); };

  const size = () => ({ w: box.clientWidth || 800, h: box.clientHeight || 500 });
  const rnd = s => (Math.random() - 0.5) * s;
  const ekey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  const radius = n => 7 + Math.min(14, Math.sqrt(n.size || 1) * 2.4);

  function add(newNodes, newEdges = []) {
    const { w, h } = size();
    for (const n of newNodes) {
      const old = nodes.get(n.id);
      if (old) { Object.assign(old, { ...n, x: old.x, y: old.y }); old.el.querySelector("text").textContent = short(old.label); continue; }
      const near = n.near && nodes.get(n.near);
      const node = { ...n, vx: 0, vy: 0,
        x: near ? near.x + rnd(80) : w / 2 + rnd(w / 3), y: near ? near.y + rnd(80) : h / 2 + rnd(h / 3) };
      node.el = drawNode(node); nodes.set(n.id, node);
    }
    for (const e of newEdges) {
      if (!nodes.has(e.source) || !nodes.has(e.target) || e.source === e.target) continue;
      const k = ekey(e.source, e.target);
      if (edges.has(k)) { edges.get(k).weight = Math.max(edges.get(k).weight, e.weight || 1); continue; }
      const line = document.createElementNS(NS, "line");
      line.setAttribute("class", "edge" + ((e.weight || 1) > 1 ? " strong" : ""));
      line.setAttribute("stroke-width", String(1 + Math.min(5, (e.weight || 1) - 1)));
      if (e.title) { const t = document.createElementNS(NS, "title"); t.textContent = e.title; line.append(t); }
      edgeLayer.append(line);
      edges.set(k, { ...e, el: line });
    }
    if (!settledOnce) {                 // first picture: lay it out before showing it, then fit it to the box
      for (let i = 0; i < 220; i++) { tick(); alpha = Math.max(0.05, alpha * 0.985); }
      settledOnce = true; render(); fit(); kick(0.08);
    } else { refitPending = true; kick(1); }
  }

  function short(s) { s = String(s); return s.length > 28 ? s.slice(0, 27) + "…" : s; }

  function drawNode(n) {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", `node ${n.type}`);
    const c = document.createElementNS(NS, "circle"); c.setAttribute("r", radius(n));
    const t = document.createElementNS(NS, "text"); t.setAttribute("dy", radius(n) + 13); t.setAttribute("text-anchor", "middle");
    t.textContent = short(n.label);
    const title = document.createElementNS(NS, "title"); title.textContent = `${n.type}: ${n.label}` + (n.hint ? `\n${n.hint}` : "");
    g.append(c, t, title); nodeLayer.append(g);
    let down = null;
    g.addEventListener("pointerdown", ev => {
      ev.stopPropagation(); capture(g, ev);
      down = { x: ev.clientX, y: ev.clientY, moved: false }; n.fixed = true;
    });
    g.addEventListener("pointermove", ev => {
      if (!down) return;
      if (Math.abs(ev.clientX - down.x) + Math.abs(ev.clientY - down.y) > 3) down.moved = true;
      const p = toWorld(ev); n.x = p.x; n.y = p.y; kick(0.3);
    });
    g.addEventListener("pointerup", () => {
      if (down && !down.moved && opts.onClick) opts.onClick(n);
      n.fixed = false; down = null;
    });
    g.addEventListener("dblclick", ev => { ev.stopPropagation(); if (opts.onOpen) opts.onOpen(n); });
    return g;
  }

  function capture(el, ev) {   // keeps a drag going outside the element; a synthetic event has no pointer to capture
    try { el.setPointerCapture(ev.pointerId); } catch { /* nothing to capture */ }
  }

  function toWorld(ev) {
    const r = svg.getBoundingClientRect();
    return { x: (ev.clientX - r.left - view.x) / view.k, y: (ev.clientY - r.top - view.y) / view.k };
  }

  // background pan + wheel zoom
  let pan = null;
  svg.addEventListener("pointerdown", ev => { pan = { x: ev.clientX - view.x, y: ev.clientY - view.y }; capture(svg, ev); });
  svg.addEventListener("pointermove", ev => { if (pan) { view.x = ev.clientX - pan.x; view.y = ev.clientY - pan.y; applyView(); } });
  svg.addEventListener("pointerup", () => { pan = null; });
  svg.addEventListener("wheel", ev => {
    ev.preventDefault();
    const r = svg.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const k = Math.max(0.2, Math.min(4, view.k * (ev.deltaY < 0 ? 1.1 : 1 / 1.1)));
    view.x = mx - (mx - view.x) * (k / view.k); view.y = my - (my - view.y) * (k / view.k); view.k = k; applyView();
  }, { passive: false });
  const applyView = () => world.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);

  function fit() {
    if (!nodes.size) return;
    const { w, h } = size(); let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach(n => { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y); });
    const k = Math.min(1.3, Math.max(0.2, Math.min((w - 80) / (x1 - x0 || 1), (h - 80) / (y1 - y0 || 1))));
    view = { k, x: w / 2 - k * (x0 + x1) / 2, y: h / 2 - k * (y0 + y1) / 2 }; applyView();
  }

  function kick(a) { alpha = Math.max(alpha, a); if (!frame) frame = requestAnimationFrame(step); }

  let settledOnce = false, refitPending = false;
  function step() {
    frame = null;
    tick();
    render();
    alpha *= 0.985;
    if (alpha > 0.02) frame = requestAnimationFrame(step);
    else if (refitPending) { refitPending = false; fit(); }
  }

  function tick() {
    const list = [...nodes.values()], { w, h } = size();
    for (let i = 0; i < list.length; i++) {                     // repulsion
      const a = list[i];
      for (let j = i + 1; j < list.length; j++) {
        const b = list[j]; let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 250000) continue;
        const f = (5200 / d2) * alpha, d = Math.sqrt(d2); dx /= d; dy /= d;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
    }
    edges.forEach(e => {                                           // springs
      const a = nodes.get(e.source), b = nodes.get(e.target);
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const len = 85 + radius(a) + radius(b), f = ((d - len) / d) * 0.06 * alpha;
      a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    });
    list.forEach(n => {                                            // gravity, damping, move
      n.vx += (w / 2 - n.x) * 0.004 * alpha; n.vy += (h / 2 - n.y) * 0.004 * alpha;
      if (n.fixed) { n.vx = n.vy = 0; return; }
      n.vx *= 0.82; n.vy *= 0.82; n.x += Math.max(-30, Math.min(30, n.vx)); n.y += Math.max(-30, Math.min(30, n.vy));
    });
  }

  function render() {
    edges.forEach(e => {
      const a = nodes.get(e.source), b = nodes.get(e.target);
      e.el.setAttribute("x1", a.x); e.el.setAttribute("y1", a.y); e.el.setAttribute("x2", b.x); e.el.setAttribute("y2", b.y);
    });
    nodes.forEach(n => {
      n.el.setAttribute("transform", `translate(${n.x},${n.y})`);
      n.el.classList.toggle("focus", n.id === focusId); n.el.classList.toggle("expanded", !!n.expanded);
    });
  }

  return {
    add, fit, has: id => nodes.has(id), get: id => nodes.get(id), get size() { return nodes.size; },
    focus(id) { focusId = id; render(); },
    clear() { nodes.clear(); edges.clear(); edgeLayer.innerHTML = ""; nodeLayer.innerHTML = ""; settledOnce = false;
              view = { x: 0, y: 0, k: 1 }; applyView(); },
    refit() { refitPending = true; kick(0.6); },
  };
}
