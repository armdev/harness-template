// rag-web: the portal. Every call goes to /api/* on this origin, which the web service forwards to the gateway.
"use strict";

const view = document.getElementById("view");
const TAG_RE = /^[a-z0-9-]{1,32}$/, AUTHOR_RE = /^[A-Za-z0-9._-]{1,64}$/;

// ------------------------------------------------------------------ helpers
async function api(path, opts = {}) {
  const r = await fetch("/api" + path, { headers: { "content-type": "application/json" }, ...opts });
  const text = await r.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) {
    const d = body && body.detail;
    const msg = Array.isArray(d) ? d.map(e => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ") : (d || r.statusText);
    const err = new Error(msg); err.status = r.status; throw err;
  }
  return body;
}
const get = (path, params) => api(path + (params ? "?" + new URLSearchParams(params) : ""));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const tagChip = t => `<a class="chip" href="#/tag/${encodeURIComponent(t)}">#${esc(t)}</a>`;
const authorChip = a => `<a class="chip author" href="#/author/${encodeURIComponent(a)}">@${esc(a)}</a>`;
const postLink = p => `<a class="t" href="#/post/${p.id}">${esc(p.title)}</a>`;
const when = s => s ? new Date(s).toLocaleString() : "";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const go = hash => { location.hash = hash; };
const nf = new Intl.NumberFormat();

function bars(rows, cls = "") {
  if (!rows.length) return `<p class="empty">nothing yet</p>`;
  const max = Math.max(...rows.map(r => r.value), 1);
  return `<div class="bars">${rows.map(r => `<div class="bar ${cls}"><a class="name" href="${r.href}" title="${esc(r.name)}">${esc(r.name)}</a>
    <div class="track"><div class="fill" style="width:${(100 * r.value / max).toFixed(1)}%"></div></div>
    <span class="v">${nf.format(r.value)}</span></div>`).join("")}</div>`;
}

function countBy(items) {
  const m = new Map(); items.forEach(x => m.set(x, (m.get(x) || 0) + 1));
  return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}

function fail(e) {
  if (e.status === 404) {
    view.innerHTML = `<div class="card"><h1>Not found</h1><p class="sub">${esc(e.message)}</p><a href="#/">Back to Analyze</a></div>`;
    return;
  }
  view.innerHTML = `<div class="card"><h1>Something went wrong</h1><p class="error">${esc(e.message)}</p>
    <p class="sub">Is the application running? <code>./app.sh status</code></p></div>`;
}

function nodeHref(n) {
  return n.type === "post" ? `#/post/${n.ref}` : n.type === "tag" ? `#/tag/${n.ref}` : `#/author/${n.ref}`;
}
const P = id => "p:" + id, T = t => "t:" + t, A = a => "a:" + a;

// ------------------------------------------------------------------ Analyze (dashboard)
async function pageAnalyze() {
  const o = await get("/graph/overview", { limit: 15 });
  if (!o.posts) {
    view.innerHTML = `<div class="card"><h1>Nothing to analyze yet</h1><p class="sub">The knowledge graph is empty.</p>
      <div class="row"><a href="#/write"><button class="primary">Write the first post</button></a>
      <span class="hint">or load a sample dataset:</span></div>
      <div id="datasets" class="datasets"></div><p id="sample-msg" class="hint"></p></div>`;
    await showDatasets();
    return;
  }
  view.innerHTML = `<h1>Analyze</h1><p class="sub">The knowledge graph at a glance: what is written, by whom, and which topics belong together.
      <button id="samples" class="small-btn">+ sample data</button> <span id="sample-msg" class="hint"></span></p>
    <div id="datasets" class="datasets" hidden></div>
    <div class="grid g3">
      <div class="card tile post"><div class="n">${nf.format(o.posts)}</div><div class="l">posts</div></div>
      <div class="card tile author"><div class="n">${nf.format(o.authors)}</div><div class="l">authors</div></div>
      <div class="card tile tag"><div class="n">${nf.format(o.tags)}</div><div class="l">tags</div></div>
    </div>
    <div class="card"><div class="row"><h2 class="grow">Topic map: the ${o.top_tags.length} biggest tags and how often they share a post</h2>
      <a href="#/graph"><button>Open in graph explorer →</button></a></div>
      <div id="topic-map" class="graph-box"></div>
      <p class="hint">Bigger circle = more posts; thicker line = more posts carrying both tags. Click a tag to open it; drag, scroll to zoom.</p></div>
    <div class="grid g2">
      <div class="card"><h2>Top tags</h2>${bars(o.top_tags.map(t => ({ name: "#" + t.tag, value: t.posts, href: `#/tag/${t.tag}` })))}</div>
      <div class="card"><h2>Top authors</h2>${bars(o.top_authors.map(a => ({ name: "@" + a.author, value: a.posts, href: `#/author/${a.author}` })), "author")}</div>
    </div>
    <div class="card"><h2>Strongest topic pairs</h2>${o.tag_links.length ? `<ul class="list">${o.tag_links.slice(0, 10).map(l =>
      `<li>${tagChip(l.source)} + ${tagChip(l.target)} <span class="m">together in ${nf.format(l.together)} posts</span></li>`).join("")}</ul>`
      : `<p class="empty">no two top tags share a post yet</p>`}</div>`;
  document.getElementById("samples").onclick = ev => { ev.target.hidden = true; showDatasets(); };
  const g = ForceGraph(document.getElementById("topic-map"), { onClick: n => go(nodeHref(n)) });
  g.add(o.top_tags.map(t => ({ id: T(t.tag), ref: t.tag, type: "tag", label: "#" + t.tag, size: t.posts, hint: `${t.posts} posts` })),
        o.tag_links.map(l => ({ source: T(l.source), target: T(l.target), weight: l.together, title: `${l.together} posts` })));
}

const datasetIndex = () => fetch("/static/datasets/index.json").then(r => r.json());

async function showDatasets() {
  const box = document.getElementById("datasets");
  box.hidden = false;
  const sets = await datasetIndex();
  box.innerHTML = sets.map(d => `<div class="card dataset"><h2>${esc(d.name)} <span class="hint">${d.posts} posts</span></h2>
    <p class="m">${esc(d.about)}</p><button class="primary" data-set="${esc(d.id)}">Load</button></div>`).join("");
  box.querySelectorAll("[data-set]").forEach(b => { b.onclick = () => loadDataset(sets.find(d => d.id === b.dataset.set), b); });
}

async function titlesOf(author) {              // every title the author has, page by page
  const titles = new Set();
  for (let before = null; ;) {
    const page = (await get("/posts", { author, limit: 50, ...(before ? { before } : {}) })).posts;
    page.forEach(p => titles.add(p.title));
    if (page.length < 50) return titles;
    const last = page[page.length - 1].id;
    if (before !== null && last >= before) throw new Error("the API ignored the 'before' cursor; cannot page safely");
    before = last;
  }
}

// The same as ./app.sh seed: through the public API, and idempotent (an author's post with the same title is skipped).
async function loadDataset(set, btn) {
  const msg = document.getElementById("sample-msg");
  btn.disabled = true;
  try {
    const posts = await (await fetch(`/static/datasets/${set.file}`)).json();
    const have = new Map();
    for (const author of new Set(posts.map(p => p.author))) have.set(author, await titlesOf(author));
    const todo = posts.filter(p => !have.get(p.author).has(p.title));
    let last = null;
    for (const [i, p] of todo.entries()) {
      last = (await api("/posts", { method: "POST", body: JSON.stringify(p) })).id;
      msg.textContent = `${set.name}: published ${i + 1} of ${todo.length}…`;
    }
    if (last === null) { msg.textContent = `${set.name}: all ${posts.length} posts are already there.`; btn.disabled = false; return; }
    msg.textContent = `${set.name}: ${todo.length} published; waiting for the graph to index them…`;
    for (let n = 0; n < 60; n++) {
      try { await get(`/posts/${last}/related`); break; } catch { await sleep(500); }
    }
    route();
  } catch (e) { msg.textContent = e.message; btn.disabled = false; }
}

// ------------------------------------------------------------------ Search
async function pageSearch(_arg, q) {
  const params = { q: q.get("q") || "", tag: q.get("tag") || "", author: q.get("author") || "" };
  view.innerHTML = `<h1>Search</h1><p class="sub">Full-text search over every post (retrieval: Postgres full text, indexed from Kafka).</p>
    <div class="card"><form id="sf" class="row">
      <input class="grow" name="q" type="search" placeholder="words, &quot;a phrase&quot;, or -exclude" value="${esc(params.q)}" required>
      <input name="tag" placeholder="tag (optional)" value="${esc(params.tag)}" size="14" pattern="[a-z0-9\\-]{1,32}">
      <input name="author" placeholder="author (optional)" value="${esc(params.author)}" size="14">
      <button class="primary">Search</button></form></div>
    <div id="results"></div>`;
  document.getElementById("sf").onsubmit = ev => {
    ev.preventDefault();
    const f = new FormData(ev.target), p = new URLSearchParams();
    for (const [k, v] of f) if (String(v).trim()) p.set(k, String(v).trim());
    go("#/search?" + p);
  };
  if (!params.q) return;
  const box = document.getElementById("results");
  box.innerHTML = `<p class="empty">searching…</p>`;
  const req = { q: params.q, limit: 50 };
  if (params.tag) req.tag = params.tag;
  if (params.author) req.author = params.author;
  const r = await get("/search", req);
  const words = params.q.toLowerCase().match(/[a-z0-9]{2,}/g) || [];
  const re = words.length ? new RegExp(`(${words.join("|")})`, "gi") : null;     // split, then escape each part:
  const hl = s => re ? String(s).split(re).map((part, i) => i % 2 ? `<mark>${esc(part)}</mark>` : esc(part)).join("")
    : esc(s);                                                                    // never highlight inside &amp; etc.
  if (!r.hits.length) { box.innerHTML = `<div class="card"><p class="empty">No posts match “${esc(params.q)}”.</p></div>`; return; }
  const tags = countBy(r.hits.flatMap(h => h.tags)).slice(0, 12), authors = countBy(r.hits.map(h => h.author)).slice(0, 8);
  box.innerHTML = `<div class="grid g-side"><div class="card"><h2>${r.hits.length} result${r.hits.length > 1 ? "s" : ""}</h2>
      <ul class="list">${r.hits.map(h => `<li><a class="t" href="#/post/${h.id}">${hl(h.title)}</a>
        <div>${authorChip(h.author)}${h.tags.map(tagChip).join("")}<span class="chip score" title="relevance">${h.score.toFixed(3)}</span></div></li>`).join("")}</ul></div>
    <div><div class="card"><h2>Tags in these results</h2>${bars(tags.map(([t, n]) => ({ name: "#" + t, value: n, href: `#/search?${new URLSearchParams({ q: params.q, tag: t })}` })))}
      <p class="hint">Click to narrow the search to a tag.</p></div>
      <div class="card"><h2>Authors in these results</h2>${bars(authors.map(([a, n]) => ({ name: "@" + a, value: n, href: `#/search?${new URLSearchParams({ q: params.q, author: a })}` })), "author")}</div></div></div>`;
}

// ------------------------------------------------------------------ Write
function pageWrite() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("rag-web.author") || "{}"); } catch { /* storage unavailable */ }
  view.innerHTML = `<h1>Write a post</h1><p class="sub">Stored by <b>content</b>, then delivered over Kafka to <b>search</b>, the knowledge <b>graph</b> and <b>notify</b>.</p>
    <div class="grid g-side"><div class="card"><form id="wf" class="form">
      <label>Title <input name="title" required maxlength="200" placeholder="What is it about?"></label>
      <label>Body <textarea name="body" required maxlength="20000" placeholder="Write it here…"></textarea></label>
      <div class="row"><label class="grow">Author <input name="author" required pattern="[A-Za-z0-9._\\-]{1,64}" value="${esc(saved.author || "")}" placeholder="your-name"></label>
        <label class="grow">Tags <span class="hint">up to 5, comma-separated, lowercase</span><input name="tags" placeholder="kafka, events"></label></div>
      <div class="row"><button class="primary" id="publish">Publish</button><span id="werr" class="error"></span></div>
    </form></div>
    <div class="card"><h2>What happens</h2><ol id="steps" class="steps">
      <li>content stores the post</li><li>search indexes it</li><li>graph links it to its author and tags</li><li>notify records it</li></ol>
      <div id="wdone"></div></div></div>`;
  document.getElementById("wf").onsubmit = async ev => {
    ev.preventDefault();
    const f = new FormData(ev.target), err = document.getElementById("werr"), btn = document.getElementById("publish");
    const tags = String(f.get("tags") || "").split(",").map(t => t.trim().toLowerCase()).filter(Boolean);
    const bad = tags.find(t => !TAG_RE.test(t));
    if (bad) { err.textContent = `invalid tag “${bad}”: lowercase letters, digits and dashes`; return; }
    if (tags.length > 5) { err.textContent = "at most 5 tags"; return; }
    const post = { title: String(f.get("title")).trim(), body: String(f.get("body")).trim(), author: String(f.get("author")).trim(), tags };
    try { localStorage.setItem("rag-web.author", JSON.stringify({ author: post.author })); } catch { /* storage unavailable */ }
    err.textContent = ""; btn.disabled = true;
    try { await track(await api("/posts", { method: "POST", body: JSON.stringify(post) })); }
    catch (e) { err.textContent = e.message; btn.disabled = false; }
  };
}

// Any of the post's own words (title first): a title of only stopwords or a "-word" must not hide the post.
function ownWords(p) {
  const words = [...new Set(`${p.title} ${p.body}`.toLowerCase().match(/[a-z0-9]{3,}/g) || [])].slice(0, 12);
  return words.length ? words.join(" or ") : p.title;
}

async function track(p) {
  const li = [...document.querySelectorAll("#steps li")];
  li[0].className = "ok"; li[0].innerHTML = `content stored post <a href="#/post/${p.id}">#${p.id}</a>`;
  const checks = [
    async () => (await get("/search", { q: ownWords(p), author: p.author, limit: 50 })).hits.some(h => h.id === p.id),
    async () => { try { await get(`/posts/${p.id}/related`); return true; } catch (e) { if (e.status === 404) return false; throw e; } },
    async () => (await get("/notifications", { author: p.author, limit: 50 })).notifications.some(n => n.post_id === p.id),
  ];
  await Promise.all(checks.map(async (check, i) => {
    li[i + 1].className = "run";
    for (let n = 0; n < 60; n++) {
      if (!document.body.contains(li[i + 1])) return;            // the user navigated away
      try { if (await check()) { li[i + 1].className = "ok"; return; } } catch { /* retried below */ }
      await sleep(500);
    }
    li[i + 1].className = "bad";
  }));
  const done = document.getElementById("wdone");
  if (done) done.innerHTML = `<p><a href="#/post/${p.id}"><button class="primary">Open the post and its graph →</button></a></p>`;
}

// ------------------------------------------------------------------ Post
async function pagePost(id) {
  const p = await get(`/posts/${encodeURIComponent(id)}`);
  let rel = null;
  try { rel = (await get(`/posts/${p.id}/related`, { limit: 12 })).related; } catch (e) { if (e.status !== 404) throw e; }
  view.innerHTML = `<div class="grid g-side"><div>
      <div class="card"><h1>${esc(p.title)}</h1><p class="sub">${authorChip(p.author)} ${p.tags.map(tagChip).join("")} · ${when(p.created_at)} · #${p.id}</p>
        <div class="body">${esc(p.body)}</div></div>
      <div class="card"><h2>Its neighbourhood in the knowledge graph</h2><div id="ego" class="graph-box small"></div>
        <p class="hint">Related posts connect through the tags they share, or through the author. Click any node to open it.</p></div></div>
    <div class="card"><h2>Related posts</h2>${rel === null ? `<p class="empty">Not in the graph yet (indexing takes a moment).</p>`
      : rel.length ? `<ul class="list">${rel.map(r => `<li>${postLink(r)}<div>${authorChip(r.author)}${r.shared_tags.map(tagChip).join("")}
        <span class="chip score" title="score = shared tags + same author">score ${r.score}</span>${r.same_author ? `<span class="m"> same author</span>` : ""}</div></li>`).join("")}</ul>`
      : `<p class="empty">No other post shares a tag or the author.</p>`}</div></div>`;
  const g = ForceGraph(document.getElementById("ego"), { onClick: n => n.id !== P(p.id) && go(nodeHref(n)) });
  const nodes = [{ id: P(p.id), ref: p.id, type: "post", label: p.title, size: 6 }, { id: A(p.author), ref: p.author, type: "author", label: "@" + p.author, size: 3 },
    ...p.tags.map(t => ({ id: T(t), ref: t, type: "tag", label: "#" + t, size: 3 }))];
  const edges = [{ source: A(p.author), target: P(p.id) }, ...p.tags.map(t => ({ source: P(p.id), target: T(t) }))];
  for (const r of rel || []) {
    nodes.push({ id: P(r.id), ref: r.id, type: "post", label: r.title, size: 1 + r.score, hint: `score ${r.score}` });
    r.shared_tags.forEach(t => edges.push({ source: P(r.id), target: T(t) }));
    if (r.same_author) edges.push({ source: A(p.author), target: P(r.id) });
  }
  g.add(nodes, edges); g.focus(P(p.id));
}

// ------------------------------------------------------------------ Tag
async function pageTag(tag) {
  if (!TAG_RE.test(tag)) { view.innerHTML = `<div class="card"><p class="error">“${esc(tag)}” is not a valid tag.</p></div>`; return; }
  let nb, posts;
  try { [nb, posts] = await Promise.all([get(`/tags/${tag}`, { limit: 15 }), get(`/tags/${tag}/posts`, { limit: 30 })]); }
  catch (e) {
    if (e.status !== 404) throw e;
    view.innerHTML = `<div class="card"><h1>#${esc(tag)}</h1><p class="empty">No post carries this tag yet.</p></div>`; return;
  }
  view.innerHTML = `<h1>#${esc(tag)}</h1><p class="sub">${nf.format(nb.posts)} posts carry this tag · <a href="#/graph?tag=${tag}">explore from here →</a></p>
    <div class="grid g-side"><div><div class="card"><h2>Topic neighbourhood</h2><div id="tg" class="graph-box small"></div>
      <p class="hint">Tags that appear on the same posts. Click a tag to move there.</p></div>
      <div class="card"><h2>Newest posts</h2><ul class="list">${posts.posts.map(p => `<li>${postLink(p)}<div>${authorChip(p.author)}</div></li>`).join("")}</ul></div></div>
    <div><div class="card"><h2>Appears together with</h2>${bars(nb.related.map(r => ({ name: "#" + r.tag, value: r.together, href: `#/tag/${r.tag}` })))}</div>
      <div class="card"><h2>Who writes about it</h2>${bars(countBy(posts.posts.map(p => p.author)).slice(0, 10)
        .map(([a, n]) => ({ name: "@" + a, value: n, href: `#/author/${a}` })), "author")}<p class="hint">among the newest ${posts.posts.length} posts</p></div></div></div>`;
  const g = ForceGraph(document.getElementById("tg"), { onClick: n => n.id !== T(tag) && go(nodeHref(n)) });
  g.add([{ id: T(tag), ref: tag, type: "tag", label: "#" + tag, size: nb.posts }, ...nb.related.map(r => ({ id: T(r.tag), ref: r.tag, type: "tag", label: "#" + r.tag, size: r.together, hint: `together in ${r.together} posts` }))],
        nb.related.map(r => ({ source: T(tag), target: T(r.tag), weight: r.together, title: `${r.together} posts` })));
  g.focus(T(tag));
}

// ------------------------------------------------------------------ Author
async function pageAuthor(author) {
  if (!AUTHOR_RE.test(author)) { view.innerHTML = `<div class="card"><p class="error">“${esc(author)}” is not a valid author name.</p></div>`; return; }
  const [ps, ns] = await Promise.all([get("/posts", { author, limit: 50 }), get("/notifications", { author, limit: 50 })]);
  const tags = countBy(ps.posts.flatMap(p => p.tags));
  view.innerHTML = `<h1>@${esc(author)}</h1><p class="sub">${ps.posts.length}${ps.posts.length === 50 ? "+" : ""} posts · <a href="#/graph?author=${encodeURIComponent(author)}">explore from here →</a></p>
    ${ps.posts.length ? "" : `<div class="card"><p class="empty">No posts by this author.</p></div>`}
    <div class="grid g-side"><div><div class="card"><h2>Posts</h2><ul class="list">${ps.posts.map(p => `<li>${postLink(p)}
        <div>${p.tags.map(tagChip).join("")}<span class="m">${when(p.created_at)}</span></div></li>`).join("") || `<li class="empty">none</li>`}</ul></div>
      <div class="card"><h2>Author map</h2><div id="ag" class="graph-box small"></div></div></div>
    <div><div class="card"><h2>Topics</h2>${bars(tags.slice(0, 12).map(([t, n]) => ({ name: "#" + t, value: n, href: `#/tag/${t}` })))}</div>
      <div class="card"><h2>Notifications</h2><ul class="list">${ns.notifications.map(n => `<li><a href="#/post/${n.post_id}">post #${n.post_id}</a>
        <div class="m">${when(n.created_at)}</div></li>`).join("") || `<li class="empty">none</li>`}</ul></div></div></div>`;
  const g = ForceGraph(document.getElementById("ag"), { onClick: n => n.id !== A(author) && go(nodeHref(n)) });
  const posts = ps.posts.slice(0, 25);
  g.add([{ id: A(author), ref: author, type: "author", label: "@" + author, size: posts.length },
    ...posts.map(p => ({ id: P(p.id), ref: p.id, type: "post", label: p.title, size: 1 })),
    ...countBy(posts.flatMap(p => p.tags)).map(([t, n]) => ({ id: T(t), ref: t, type: "tag", label: "#" + t, size: n }))],
  [...posts.map(p => ({ source: A(author), target: P(p.id) })), ...posts.flatMap(p => p.tags.map(t => ({ source: P(p.id), target: T(t) })))]);
  g.focus(A(author));
}

// ------------------------------------------------------------------ Graph explorer
async function pageGraph(_arg, q) {
  view.innerHTML = `<h1>Graph explorer</h1><p class="sub">Build the graph step by step: <b>click</b> a node to expand its neighbours,
      <b>double-click</b> to open its page. Start from the topic map, a tag, a post or an author.</p>
    <div class="card"><form id="gf" class="row">
      <select name="kind"><option value="tag">tag</option><option value="post">post id</option><option value="author">author</option></select>
      <input class="grow" name="value" placeholder="kafka · 42 · alice" required>
      <button class="primary">Add to graph</button><button type="button" id="gtop">Topic map</button><button type="button" id="gclear">Clear</button>
      <span id="gerr" class="error"></span></form></div>
    <div class="grid g-side"><div class="card"><div id="gx" class="graph-box"></div></div>
      <div class="card panel-info" id="ginfo"><h2>Selection</h2><p class="empty">Click a node.</p>
        <p class="hint">Colours: <span class="chip" style="color:var(--post);background:none">post</span>
          <span class="chip">tag</span><span class="chip author">author</span></p></div></div>`;
  const info = document.getElementById("ginfo"), gerr = document.getElementById("gerr");
  const g = ForceGraph(document.getElementById("gx"), {
    onClick: n => expand(n).catch(e => { gerr.textContent = e.message; }),
    onOpen: n => go(nodeHref(n)),
  });

  async function expand(n) {
    g.focus(n.id); gerr.textContent = "";
    info.innerHTML = `<h2>${esc(n.label)}</h2><p class="m">${n.type}</p><p class="empty">expanding…</p>`;
    let summary = "";
    if (n.type === "tag") {
      const [nb, ps] = await Promise.all([get(`/tags/${n.ref}`, { limit: 8 }), get(`/tags/${n.ref}/posts`, { limit: 10 })]);
      g.add([...nb.related.map(r => ({ id: T(r.tag), ref: r.tag, type: "tag", label: "#" + r.tag, size: r.together, near: n.id })),
        ...ps.posts.map(p => ({ id: P(p.id), ref: p.id, type: "post", label: p.title, near: n.id, hint: "@" + p.author }))],
      [...nb.related.map(r => ({ source: n.id, target: T(r.tag), weight: r.together, title: `${r.together} posts` })),
        ...ps.posts.map(p => ({ source: P(p.id), target: n.id }))]);
      summary = `<p>${nf.format(nb.posts)} posts carry it.</p><p>${nb.related.map(r => tagChip(r.tag)).join("")}</p>`;
    } else if (n.type === "post") {
      const [p, rel] = await Promise.all([get(`/posts/${n.ref}`), get(`/posts/${n.ref}/related`, { limit: 8 }).catch(() => ({ related: [] }))]);
      g.add([{ id: A(p.author), ref: p.author, type: "author", label: "@" + p.author, near: n.id },
        ...p.tags.map(t => ({ id: T(t), ref: t, type: "tag", label: "#" + t, near: n.id })),
        ...rel.related.map(r => ({ id: P(r.id), ref: r.id, type: "post", label: r.title, size: 1 + r.score, near: n.id, hint: `score ${r.score}` }))],
      [{ source: A(p.author), target: n.id }, ...p.tags.map(t => ({ source: n.id, target: T(t) })),
        ...rel.related.map(r => ({ source: n.id, target: P(r.id), weight: r.score, title: `score ${r.score}: ${r.shared_tags.join(", ")}` }))]);
      summary = `<p>${authorChip(p.author)}${p.tags.map(tagChip).join("")}</p><p class="m">${esc(p.body.slice(0, 220))}${p.body.length > 220 ? "…" : ""}</p>`;
    } else {
      const ps = await get("/posts", { author: n.ref, limit: 15 });
      g.add([...ps.posts.map(p => ({ id: P(p.id), ref: p.id, type: "post", label: p.title, near: n.id })),
        ...ps.posts.flatMap(p => p.tags).map(t => ({ id: T(t), ref: t, type: "tag", label: "#" + t, near: n.id }))],
      [...ps.posts.map(p => ({ source: n.id, target: P(p.id) })), ...ps.posts.flatMap(p => p.tags.map(t => ({ source: P(p.id), target: T(t) })))]);
      summary = `<p>${ps.posts.length} posts shown.</p>`;
    }
    const node = g.get(n.id); if (node) node.expanded = true;
    info.innerHTML = `<h2>${esc(n.label)}</h2><p class="m">${n.type} · ${g.size} nodes in the graph</p>${summary}
      <p><a href="${nodeHref(n)}"><button>Open ${n.type} page →</button></a></p>`;
  }

  async function seed(kind, value) {
    if (kind === "tag" && !TAG_RE.test(value)) throw new Error("a tag is lowercase letters, digits and dashes");
    if (kind === "author" && !AUTHOR_RE.test(value)) throw new Error("an author is letters, digits, dot, dash or underscore");
    if (kind === "post" && !/^\d+$/.test(value)) throw new Error("a post id is a number");
    let node;
    if (kind === "tag") { await get(`/tags/${value}`, { limit: 1 }); node = { id: T(value), ref: value, type: "tag", label: "#" + value, size: 4 }; }
    else if (kind === "post") { const p = await get(`/posts/${value}`); node = { id: P(p.id), ref: p.id, type: "post", label: p.title, size: 4 }; }
    else node = { id: A(value), ref: value, type: "author", label: "@" + value, size: 4 };
    g.add([node]); await expand(node);
  }

  async function topicMap() {
    const o = await get("/graph/overview", { limit: 12 });
    g.add(o.top_tags.map(t => ({ id: T(t.tag), ref: t.tag, type: "tag", label: "#" + t.tag, size: t.posts })),
          o.tag_links.map(l => ({ source: T(l.source), target: T(l.target), weight: l.together })));
    info.innerHTML = `<h2>Topic map</h2><p>The ${o.top_tags.length} biggest tags of ${nf.format(o.posts)} posts. Click one to expand it.</p>`;
  }

  document.getElementById("gf").onsubmit = ev => {
    ev.preventDefault(); const f = new FormData(ev.target);
    seed(String(f.get("kind")), String(f.get("value")).trim()).catch(e => { gerr.textContent = e.status === 404 ? "not found" : e.message; });
  };
  document.getElementById("gtop").onclick = () => topicMap().catch(e => { gerr.textContent = e.message; });
  document.getElementById("gclear").onclick = () => { g.clear(); info.innerHTML = `<h2>Selection</h2><p class="empty">Cleared.</p>`; };

  const start = ["tag", "post", "author"].find(k => q.get(k));
  if (start) await seed(start, q.get(start)); else await topicMap();
}

// ------------------------------------------------------------------ Chat
const CHAT_KEY = "rag-web.chat";
const HISTORY = 8;                 // turns sent with a question; the chat service uses the same number
let activeStream = null;           // the answer being streamed; leaving the page stops it
let chatGeneration = 0;            // bumped by "New chat": a finishing answer from before it is discarded
// Suggested questions come from the sample datasets whose topics are in the graph (or all of them when it is empty).
async function suggestions() {
  try {
    const [sets, o] = await Promise.all([datasetIndex(), get("/graph/overview", { limit: 50 })]);
    const tags = new Set(o.top_tags.map(t => t.tag));
    const loaded = sets.filter(d => tags.has(d.marker));
    return (loaded.length ? loaded : sets).flatMap(d => d.questions).slice(0, 6);
  } catch { return []; }
}

function loadChat() {
  try { return JSON.parse(sessionStorage.getItem(CHAT_KEY) || "[]"); } catch { return []; }
}
function saveChat(turns) {
  try { sessionStorage.setItem(CHAT_KEY, JSON.stringify(turns)); } catch { /* storage unavailable */ }
}

// Markdown-lite for answers: escape first, then **bold**, `code`, "- " lists, paragraphs, and [#id] citations.
function renderAnswer(text, sources) {
  const known = new Set((sources || []).map(s => s.id));
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[#(\d+)\]/g, (m, id) => known.has(+id)
      ? `<a class="cite" href="#/post/${id}" data-cite="${id}">#${id}</a>` : `<span class="cite dead">#${id}</span>`);
  const out = []; let list = null;
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (m) { (list ||= []).push(`<li>${inline(m[1])}</li>`); continue; }
    if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
    if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`<ul>${list.join("")}</ul>`);
  return out.join("");
}

function parseEvents(buffer, onEvent) {          // returns the unparsed rest of the buffer
  let i;
  while ((i = buffer.indexOf("\n\n")) >= 0) {
    const block = buffer.slice(0, i); buffer = buffer.slice(i + 2);
    let name = "message", data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) name = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    try { onEvent(name, JSON.parse(data)); } catch { /* ignore a malformed event */ }
  }
  return buffer;
}

async function pageChat() {
  let turns = loadChat(), controller = null;
  const suggested = await suggestions();
  view.innerHTML = `<div class="chat-layout">
    <div class="chat-main card">
      <div class="row chat-head"><h1 class="grow">Chat</h1><button id="new-chat">New chat</button></div>
      <p class="sub">Answers come only from the posts: <b>search</b> finds matching posts, the knowledge <b>graph</b> adds their
        closest neighbours, a language model answers and cites them as <span class="cite">#id</span>.</p>
      <div id="thread" class="thread"></div>
      <form id="ask" class="composer">
        <textarea id="q" rows="2" maxlength="4000" placeholder="Ask about the posts…  (Enter to send, Shift+Enter for a new line)"></textarea>
        <button class="primary" id="send">Send</button><button type="button" id="stop" hidden>Stop</button>
      </form>
    </div>
    <aside class="card chat-side"><h2>Sources</h2><div id="sources"><p class="empty">Ask a question to see which posts answer it.</p></div>
      <div id="src-graph" class="graph-box small" hidden></div></aside></div>`;
  const thread = document.getElementById("thread"), q = document.getElementById("q");
  const send = document.getElementById("send"), stop = document.getElementById("stop");

  function showSources(turn) {
    const box = document.getElementById("sources"), gbox = document.getElementById("src-graph");
    if (!box || !gbox) return;                                     // not on the chat page any more
    const src = turn?.sources || [];
    if (!src.length) { box.innerHTML = `<p class="empty">${turn ? "No posts matched." : "Ask a question to see which posts answer it."}</p>`; gbox.hidden = true; return; }
    const cited = new Set(turn.citations || []);
    box.innerHTML = `<p class="hint">${src.length} posts given to the model · ${cited.size} cited${turn.model ? ` · ${esc(turn.model)}` : " · no model"}</p>
      <ul class="list sources">${src.map(s => `<li id="src-${s.id}" class="${cited.has(s.id) ? "cited" : ""}">
        <a class="t" href="#/post/${s.id}">#${s.id} ${esc(s.title)}</a>
        <div>${authorChip(s.author)}${s.tags.map(tagChip).join("")}
          <span class="chip score">${s.via === "graph" ? `graph · near #${s.near}` : "search"}</span></div>
        <div class="m">${esc(s.snippet)}${s.snippet.length >= 240 ? "…" : ""}</div></li>`).join("")}</ul>`;
    gbox.hidden = false;
    const g = ForceGraph(gbox, { onClick: n => go(nodeHref(n)) });
    const tags = countBy(src.flatMap(s => s.tags));
    g.add([...src.map(s => ({ id: P(s.id), ref: s.id, type: "post", label: `#${s.id} ${s.title}`, size: cited.has(s.id) ? 4 : 1 })),
      ...tags.map(([t, n]) => ({ id: T(t), ref: t, type: "tag", label: "#" + t, size: n }))],
    src.flatMap(s => s.tags.map(t => ({ source: P(s.id), target: T(t) }))));
  }

  function bubble(turn, i) {
    if (turn.role === "user") return `<div class="msg user"><div class="bubble">${esc(turn.content).replace(/\n/g, "<br>")}</div></div>`;
    const status = turn.pending ? `<span class="typing"><i></i><i></i><i></i></span>`
      : `<button class="link srcbtn" data-i="${i}">${(turn.sources || []).length} sources</button>${turn.model ? ` · ${esc(turn.model)}` : turn.sources?.length && !turn.error ? " · no model" : ""}${turn.error ? ` · <span class="error">${esc(turn.error)}</span>` : ""}`;
    return `<div class="msg bot"><div class="bubble">${renderAnswer(turn.content, turn.sources) || (turn.pending ? "" : "<p class=empty>(no answer)</p>")}
      <div class="meta">${status}</div></div></div>`;
  }

  function draw() {
    thread.innerHTML = turns.length ? turns.map(bubble).join("")
      : `<div class="suggest"><p class="hint">Try one of these:</p>${suggested.map(s => `<button class="sugg">${esc(s)}</button>`).join("")}</div>`;
    thread.querySelectorAll(".sugg").forEach(b => { b.onclick = () => { q.value = b.textContent; submit(); }; });
    thread.querySelectorAll(".srcbtn").forEach(b => { b.onclick = () => showSources(turns[+b.dataset.i]); });
    thread.querySelectorAll("[data-cite]").forEach(a => a.addEventListener("mouseenter", () => {
      document.querySelectorAll(".sources li").forEach(li => li.classList.toggle("hl", li.id === "src-" + a.dataset.cite));
    }));
    thread.scrollTop = thread.scrollHeight;
  }

  async function submit() {
    const text = q.value.trim();
    if (!text || controller) return;
    q.value = "";
    turns.push({ role: "user", content: text });
    const bot = { role: "assistant", content: "", sources: [], pending: true };
    turns.push(bot); draw();
    // The server uses the last 8 turns and accepts at most 20 of at most 4000 characters: never send more.
    const messages = turns.filter(t => !t.pending && t.content).slice(-HISTORY)
      .map(t => ({ role: t.role, content: t.content.slice(0, 4000) }));
    controller = new AbortController(); send.hidden = true; stop.hidden = false;
    const mine = controller, generation = chatGeneration;
    activeStream = mine; saveChat(turns);
    try {
      const r = await fetch("/api/chat", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages }), signal: controller.signal });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        const d = body.detail;
        throw new Error(Array.isArray(d) ? d.map(e => e.msg).join("; ") : d || r.statusText);
      }
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "", frame = null;
      const redraw = () => { if (!frame) frame = requestAnimationFrame(() => { frame = null; draw(); }); };
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf = parseEvents(buf + dec.decode(value, { stream: true }), (name, data) => {
          if (name === "sources") { bot.sources = data; showSources(bot); }
          else if (name === "token") bot.content += data.text;
          else if (name === "done") { bot.citations = data.citations; bot.model = data.model; }
          else if (name === "error") bot.error = data.detail;
          redraw();
        });
      }
    } catch (e) {
      bot.error = e.name === "AbortError" ? "stopped" : e.message;
    } finally {
      bot.pending = false;
      if (controller === mine) controller = null;
      if (activeStream === mine) activeStream = null;
      if (generation !== chatGeneration) return;                  // "New chat" was pressed: this turn is gone
      if (!thread.isConnected) {                                   // the user left the page: keep the turn, touch no DOM
        if (loadChat().length === turns.length) saveChat(turns);   // ...unless another chat page has saved since
        return;
      }
      send.hidden = false; stop.hidden = true;
      saveChat(turns); draw(); showSources(bot); q.focus();
    }
  }

  document.getElementById("ask").onsubmit = ev => { ev.preventDefault(); submit(); };
  q.addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); submit(); } });
  stop.onclick = () => controller && controller.abort();
  document.getElementById("new-chat").onclick = () => {
    chatGeneration++;
    if (controller) controller.abort();
    controller = null; send.hidden = false; stop.hidden = true;
    turns = []; saveChat(turns); draw(); showSources(null);
  };
  turns = turns.filter(t => !t.pending);
  draw();
  const last = [...turns].reverse().find(t => t.role === "assistant");
  if (last) showSources(last);
  q.focus();
}

// ------------------------------------------------------------------ Plan (planner: employees, tasks, meetings)
const SEVERITIES = ["blocker", "critical", "major", "minor", "trivial"];
const BUCKET_LABEL = { now: "do now", next: "next", later: "later", someday: "someday" };
const PLAN_LEGEND = [["person", "le"], ["blocker", "sb"], ["critical", "sc"], ["major", "sm"], ["minor / trivial", "sn"]];
const sevChip = s => `<span class="sev ${esc(s)}">${esc(s)}</span>`;
const bucketChip = t => `<span class="bucket ${esc(t.bucket)}" title="score ${t.score}">${BUCKET_LABEL[t.bucket]} · ${t.score}</span>`;
const personLink = (h, label) => h ? `<a href="#/plan/${encodeURIComponent(h)}">${esc(label || "@" + h)}</a>` : `<span class="m">unassigned</span>`;
const hours = m => `${+(m / 60).toFixed(2)} h`;
const dayName = d => new Date(d + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

// The same as ./app.sh seed planner: dates relative to today (day 0 = the first working day), upserted, repeatable.
function workingDays(n) {
  const out = [], d = new Date(); d.setHours(0, 0, 0, 0);
  while (out.length < n) {
    if (d.getDay() % 6 !== 0) out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    d.setDate(d.getDate() + 1);
  }
  return out;
}

async function loadPlannerDataset(btn, msg) {
  btn.disabled = true;
  try {
    const data = await (await fetch("/static/datasets/planner.json")).json();
    const days = workingDays(1 + Math.max(...data.tasks.map(t => t.due_in || 0), ...data.meetings.map(m => m.day)));
    const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });
    const total = data.employees.length + data.tasks.length + data.meetings.length;
    let n = 0;
    const step = () => { msg.textContent = `loading ${++n} of ${total}…`; };
    for (const e of data.employees) { await post("/planner/employees", e); step(); }
    for (const t of data.tasks) {
      const { due_in, ...body } = t;
      await post("/planner/tasks", { ...body, due: due_in == null ? null : days[due_in] }); step();
    }
    for (const m of data.meetings) {
      const [h, min] = m.start.split(":").map(Number), end = h * 60 + min + m.minutes;
      const at = x => `${days[m.day]}T${String(Math.floor(x / 60)).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}:00`;
      await post("/planner/meetings", { id: m.id, title: m.title, organizer: m.organizer, attendees: m.attendees,
                                        starts_at: at(h * 60 + min), ends_at: at(end) }); step();
    }
    route();
  } catch (e) { msg.textContent = e.message; btn.disabled = false; }
}

function taskRows(tasks, opts = {}) {
  if (!tasks.length) return `<p class="empty">no tasks match</p>`;
  return `<div class="table-wrap"><table class="tasks"><thead><tr>${opts.rank ? "<th>#</th>" : ""}<th>priority</th><th>task</th>
    <th>severity</th><th>status</th>${opts.person ? "" : "<th>assignee</th>"}<th class="num">est.</th><th>due</th><th>why</th></tr></thead><tbody>
    ${tasks.map((t, i) => `<tr class="${t.blocked_by.length ? "blocked" : ""}">${opts.rank ? `<td class="num">${i + 1}</td>` : ""}
      <td>${bucketChip(t)}</td>
      <td><b>${esc(t.key)}</b> ${esc(t.title)}${t.description ? `<div class="m clamp" title="${esc(t.description)}">${esc(t.description)}</div>` : ""}
        ${opts.notes && opts.notes[t.key] ? `<div class="note">✦ ${esc(opts.notes[t.key])}</div>` : ""}</td>
      <td>${sevChip(t.severity)}</td>
      <td>${opts.person ? `<select class="status" data-key="${esc(t.key)}">${["todo", "in_progress", "review", "done"].map(s =>
        `<option${s === t.status ? " selected" : ""}>${s}</option>`).join("")}</select>` : esc(t.status.replace("_", " "))}</td>
      ${opts.person ? "" : `<td>${personLink(t.assignee)}</td>`}
      <td class="num">${+t.estimate_hours} h</td><td>${t.due ? esc(t.due) : "—"}${opts.finishes && opts.finishes[t.key] ?
        `<div class="m ${t.due && opts.finishes[t.key] > t.due ? "error" : ""}">ends ${esc(opts.finishes[t.key])}</div>` : ""}</td>
      <td class="m">${t.reasons.map(esc).join(" · ")}${t.blocks.length ? `<div>unblocks ${t.blocks.map(esc).join(", ")}</div>` : ""}</td></tr>`).join("")}
    </tbody></table></div>`;
}

function planGraph(box, g) {
  const fg = ForceGraph(box, { legend: PLAN_LEGEND, onOpen: n => go(n.type === "employee" ? `#/plan/${encodeURIComponent(n.ref)}` : `#/plan/${encodeURIComponent(n.assignee || "")}`) });
  fg.add(g.nodes.map(n => n.type === "employee"
    ? { ...n, cls: "", size: 6, label: n.label, hint: `${n.role} · ${n.team}` }
    : { ...n, cls: n.severity, size: 1 + n.score / 25, hint: `${n.severity} · ${n.status} · score ${n.score} · @${n.assignee || "unassigned"}` }),
  g.edges.map(e => ({ ...e, cls: e.kind, weight: e.weight || 1,
    title: e.kind === "meets" ? `${e.weight} shared meeting(s) this week` : e.kind === "depends_on" ? "depends on" : "assigned" })));
  return fg;
}

async function pagePlan(handle, q) {
  if (handle) return pagePerson(handle, q);
  const filters = { status: q.get("status") || "open", sort: q.get("sort") || "priority" };
  for (const k of ["assignee", "project", "q"]) if (q.get(k)) filters[k] = q.get(k);
  const sev = q.getAll("severity").filter(s => SEVERITIES.includes(s));
  const params = new URLSearchParams({ ...filters, limit: 200 });
  if (filters.status === "all") params.delete("status");
  sev.forEach(s => params.append("severity", s));
  const [team, list, g] = await Promise.all([get("/planner/employees"), api("/planner/tasks?" + params), get("/planner/graph", { limit: 60 })]);
  const people = team.employees;
  if (!people.length) {
    view.innerHTML = `<div class="card"><h1>Plan</h1><p class="sub">No employees yet. Load the sample bank IT team: 11 people in 7 teams,
      61 Jira-style tasks (severity, estimate, due date, dependencies) and two weeks of meetings, dated from today.</p>
      <div class="row"><button id="load-team" class="primary">Load the iBank IT team</button><span id="team-msg" class="hint">or: <code>./app.sh seed planner</code></span></div></div>`;
    document.getElementById("load-team").onclick = ev => loadPlannerDataset(ev.target, document.getElementById("team-msg"));
    return;
  }
  const open = people.reduce((a, p) => a + p.open_tasks, 0), urgent = people.reduce((a, p) => a + p.urgent, 0);
  const overdue = people.reduce((a, p) => a + p.overdue, 0), work = people.reduce((a, p) => a + p.open_hours, 0);
  const projects = [...new Set(list.tasks.map(t => t.key.split("-")[0]))].sort();
  view.innerHTML = `<h1>Plan</h1><p class="sub">Who works on what, what matters most and why. Every task is scored by its severity,
      due date, the work that waits for it and whether it is started; open a person to plan their week around their meetings, or re-plan it with AI.
      <button id="reload-team" class="small-btn">reload sample team</button> <span id="team-msg" class="hint"></span></p>
    <div class="grid g4">
      <div class="card tile author"><div class="n">${people.length}</div><div class="l">people</div></div>
      <div class="card tile post"><div class="n">${nf.format(open)}</div><div class="l">open tasks · ${nf.format(Math.round(work))} h</div></div>
      <div class="card tile bad"><div class="n">${urgent}</div><div class="l">to do now</div></div>
      <div class="card tile warn"><div class="n">${overdue}</div><div class="l">overdue</div></div>
    </div>
    <div class="card"><h2>Team load: open work against 5 days of focus time</h2><div class="table-wrap"><table class="team">
      <thead><tr><th>person</th><th>team</th><th class="num">open</th><th>load</th><th class="num">meetings</th><th class="num">do now</th><th class="num">overdue</th></tr></thead><tbody>
      ${people.map(p => `<tr><td>${personLink(p.handle, p.name)}<div class="m">${esc(p.role)}</div></td><td>${esc(p.team)}</td>
        <td class="num">${p.open_tasks} · ${+p.open_hours} h</td>
        <td><div class="load ${p.load > 1 ? "over" : p.load > 0.8 ? "full" : ""}" title="${Math.round(p.load * 100)}% of ${p.capacity_hours} h × 5 days">
          <div style="width:${Math.min(100, p.load * 100).toFixed(0)}%"></div><span>${Math.round(p.load * 100)}%</span></div></td>
        <td class="num">${+p.meeting_hours} h</td><td class="num">${p.urgent || ""}</td><td class="num">${p.overdue ? `<b class="error">${p.overdue}</b>` : ""}</td></tr>`).join("")}
      </tbody></table></div></div>
    <div class="card"><h2>Tasks <span class="hint">${list.total} match${list.total > 200 ? ", first 200 shown" : ""}</span></h2>
      <form id="tf" class="row filters">
        <select name="assignee"><option value="">everyone</option>${people.map(p => `<option value="${esc(p.handle)}"${p.handle === filters.assignee ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
        <select name="project"><option value="">all projects</option>${projects.map(p => `<option${p === filters.project ? " selected" : ""}>${esc(p)}</option>`).join("")}</select>
        <select name="status">${["open", "todo", "in_progress", "review", "done", "all"].map(s => `<option${s === filters.status ? " selected" : ""}>${s}</option>`).join("")}</select>
        <span class="sevs">${SEVERITIES.map(s => `<label><input type="checkbox" name="severity" value="${s}"${sev.includes(s) ? " checked" : ""}> ${s}</label>`).join("")}</span>
        <input class="grow" name="q" placeholder="search title, description, key" value="${esc(filters.q || "")}">
        <label class="hint">sort <select name="sort">${["priority", "due", "severity", "estimate", "key"].map(s => `<option${s === filters.sort ? " selected" : ""}>${s}</option>`).join("")}</select></label>
        <button class="primary">Filter</button></form>
      ${taskRows(list.tasks)}</div>
    <div class="card"><h2>Work graph: people, their most important open tasks, what waits for what, who meets whom</h2>
      <div id="plan-graph" class="graph-box"></div>
      <p class="hint">Task size = priority score; arrows of dependency are dashed; a line between two people = meetings together this week. Double-click to open a person.</p></div>`;
  document.getElementById("tf").onsubmit = ev => {
    ev.preventDefault();
    const f = new FormData(ev.target), p = new URLSearchParams();
    for (const [k, v] of f.entries()) if (v) p.append(k, String(v));
    go("#/plan?" + p);
  };
  document.getElementById("reload-team").onclick = ev => loadPlannerDataset(ev.target, document.getElementById("team-msg"));
  planGraph(document.getElementById("plan-graph"), g);
}

function weekView(plan) {
  const H0 = 9 * 60, H1 = 18 * 60, pct = t => { const [h, m] = t.split(":").map(Number); return (100 * (h * 60 + m - H0) / (H1 - H0)).toFixed(2); };
  const block = (cls, a, b, label, title) => `<div class="blk ${cls}" style="top:${pct(a)}%;height:${(pct(b) - pct(a)).toFixed(2)}%" title="${esc(title)}">${esc(label)}</div>`;
  return `<div class="week">${plan.days.map(d => `<div class="day${d.off ? " off" : ""}"><div class="dh"><b>${esc(dayName(d.date))}</b>
      <span class="m">${d.off ? "day off" : `${hours(d.focus_minutes)} tasks · ${hours(d.meeting_minutes)} meetings`}</span></div>
      <div class="col">${[10, 11, 12, 13, 14, 15, 16, 17].map(h => `<i class="hr" style="top:${pct(`${h}:00`)}%"><span>${h}</span></i>`).join("")}
        <div class="blk lunch" style="top:${pct("13:00")}%;height:${(pct("14:00") - pct("13:00")).toFixed(2)}%"></div>
        ${d.meetings.map(m => block("meet", m.start, m.end, m.title, `${m.start}–${m.end} ${m.title}`)).join("")}
        ${d.items.map(i => block("task " + i.severity, i.start, i.end, `${i.key} ${i.title}`, `${i.start}–${i.end} ${i.key} ${i.title} (${i.severity})`)).join("")}
      </div></div>`).join("")}</div>`;
}

const AI_HINTS = ["Incidents and security first, then deadlines", "Unblock my colleagues first", "I am off on Friday", "Finish what I started before new work"];

async function pagePerson(handle, q) {
  const days = Math.min(10, Math.max(1, Number(q.get("days")) || 5));
  const [base, g] = await Promise.all([get(`/planner/plan/${encodeURIComponent(handle)}`, { days }), get("/planner/graph", { handle })]);
  const e = base.employee;
  view.innerHTML = `<p class="crumbs"><a href="#/plan">Plan</a> / ${esc(e.team)}</p>
    <div class="row"><h1 class="grow">${esc(e.name)} <span class="hint">@${esc(e.handle)} · ${esc(e.role)} · ${e.capacity_hours} focus h/day</span></h1>
      <label class="hint">days <select id="days">${[5, 10].map(n => `<option${n === days ? " selected" : ""}>${n}</option>`).join("")}</select></label></div>
    <div class="card ai"><h2>Re-plan with AI</h2>
      <p class="hint">The model re-orders the open tasks following your instruction and may mark days off; the rules then check it: dependencies first,
        meetings and focus hours respected. Without a model the plan stays the rules' plan.</p>
      <form id="aif" class="row"><input class="grow" name="instruction" maxlength="500" placeholder="e.g. ${esc(AI_HINTS[0])}">
        <button class="primary">Re-plan with AI</button><button type="button" id="rules">Rules' plan</button></form>
      <div class="row hints">${AI_HINTS.map(h => `<button type="button" class="sugg small-btn">${esc(h)}</button>`).join("")}</div></div>
    <div id="plan-out"></div>
    <div class="card"><h2>Work graph of ${esc(e.name)}: tasks, what they wait for, who waits for them, who they meet</h2>
      <div id="plan-graph" class="graph-box small"></div></div>`;
  const out = document.getElementById("plan-out");
  const show = plan => {
    out.innerHTML = `<div class="card summary ${plan.source}"><div class="row"><h2 class="grow">${plan.source === "model" ? `AI plan <span class="chip score">${esc(plan.model)}</span>` : "Plan by the rules"}</h2>
        ${plan.source === "model" ? `<span class="hint">${plan.changed} of ${plan.order.length} positions changed${plan.days_off.length ? ` · off: ${plan.days_off.map(esc).join(", ")}` : ""}</span>` : ""}</div>
        <p>${esc(plan.summary)}</p>${plan.fallback ? `<p class="hint error">${esc(plan.fallback)}</p>` : ""}
        ${plan.warnings.length ? `<ul class="warn">${plan.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}</div>
      <div class="card"><h2>Week</h2>${weekView(plan)}
        <p class="hint"><span class="sev blocker">blocker</span> <span class="sev critical">critical</span> <span class="sev major">major</span>
          <span class="sev minor">minor</span> tasks · grey: meetings · lunch 13–14</p></div>
      <div class="card"><h2>Order of work <span class="hint">${plan.tasks.length} open tasks${plan.source === "model" ? ", in the model's order" : ", by priority"}</span></h2>
        ${taskRows(plan.tasks, { rank: true, person: true, notes: plan.notes, finishes: plan.finishes })}</div>
      ${plan.unscheduled.length ? `<div class="card"><h2>Does not fit</h2><ul class="list">${plan.unscheduled.map(u =>
        `<li><b>${esc(u.key)}</b> ${esc(u.title)} ${sevChip(u.severity)} <div class="m">${esc(u.reason)}</div></li>`).join("")}</ul></div>` : ""}`;
    out.querySelectorAll("select.status").forEach(s => {
      s.onchange = async () => {
        s.disabled = true;
        try { await api(`/planner/tasks/${encodeURIComponent(s.dataset.key)}/status`, { method: "POST", body: JSON.stringify({ status: s.value }) }); route(); }
        catch (err) { s.disabled = false; alert(err.message); }
      };
    });
  };
  show(base);
  const form = document.getElementById("aif"), btn = form.querySelector("button.primary");
  form.onsubmit = async ev => {
    ev.preventDefault();
    btn.disabled = true; btn.textContent = "Thinking…";
    try {
      show(await api(`/planner/plan/${encodeURIComponent(handle)}/ai`, { method: "POST",
        body: JSON.stringify({ instruction: String(new FormData(form).get("instruction") || ""), days }) }));
    } catch (err) { out.insertAdjacentHTML("afterbegin", `<p class="error">${esc(err.message)}</p>`); }
    finally { btn.disabled = false; btn.textContent = "Re-plan with AI"; }
  };
  document.getElementById("rules").onclick = () => show(base);
  document.querySelectorAll(".hints .sugg").forEach(b => { b.onclick = () => { form.instruction.value = b.textContent; }; });
  document.getElementById("days").onchange = ev => go(`#/plan/${encodeURIComponent(handle)}?days=${ev.target.value}`);
  planGraph(document.getElementById("plan-graph"), g);
}

// ------------------------------------------------------------------ router
const routes = { "": pageAnalyze, search: pageSearch, write: pageWrite, post: pagePost, tag: pageTag, author: pageAuthor, graph: pageGraph, chat: pageChat, plan: pagePlan };

async function route() {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, ...rest] = path.split("/");
  let arg = rest.join("/");
  try { arg = decodeURIComponent(arg); } catch { /* a malformed %-sequence: use it as typed */ }
  if (activeStream) { activeStream.abort(); activeStream = null; }
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.route === name));
  const page = routes[name] || pageAnalyze;
  view.innerHTML = `<p class="empty">loading…</p>`;
  window.scrollTo(0, 0);
  try { await page(arg, new URLSearchParams(query || "")); } catch (e) { fail(e); }
}

document.getElementById("quick-search").onsubmit = ev => {
  ev.preventDefault();
  const q = document.getElementById("quick-q").value.trim();
  if (q) go("#/search?" + new URLSearchParams({ q }));
};
window.addEventListener("hashchange", route);
route();
