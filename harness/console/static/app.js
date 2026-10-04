// air-harness console — vanilla JS, no build step. Talks to harness/console/server.py.
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let STATE = null, PROMPTS = [], spec = null;

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Console": "1" }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ---------------------------------------------------------------- tabs
function show(tab) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === tab));
  history.replaceState(null, "", "#" + tab);
  if (tab === "api" && !spec) loadApi();
  if (tab === "guides" && !$("#files").children.length) loadFiles();
}
$$("#tabs button").forEach((b) => (b.onclick = () => show(b.dataset.tab)));

// ---------------------------------------------------------------- markdown (just enough for reports and guides)
function md(src) {
  const lines = String(src || "").split("\n"), out = [];
  let i = 0;
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, a, h) => /^https?:/.test(h) ? `<a href="${h}" target="_blank" rel="noopener">${a}</a>` : a);
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith("```")) { const buf = []; i++; while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]); i++; out.push(`<pre>${esc(buf.join("\n"))}</pre>`); continue; }
    const h = l.match(/^(#{1,4})\s+(.*)/);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (l.trim().startsWith("|")) {
      const rows = []; while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      out.push("<table>" + body.map((r, n) => "<tr>" + cells(r).map((c) => n ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`).join("") + "</tr>").join("") + "</table>");
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      const items = []; while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      out.push("<ul>" + items.map((t) => `<li>${inline(t)}</li>`).join("") + "</ul>"); continue;
    }
    if (l.trim()) out.push(`<p>${inline(l)}</p>`);
    i++;
  }
  return out.join("\n");
}

// ---------------------------------------------------------------- state
async function loadState() {
  STATE = await api("/api/state");
  $("#version").textContent = STATE.version ? "v" + STATE.version : "";
  const v = STATE.verdict ? STATE.verdict.split(" ")[0] : "no report";
  $("#verdict").textContent = "harness: " + v;
  $("#verdict").className = "pill " + v;
  $("#ov-verdict").innerHTML = `<span class="${v}">${esc(v)}</span>`;
  const blocking = STATE.sensors.filter((s) => s.blocking).length;
  const proven = STATE.sensors.filter((s) => s.selftest === "proven").length;
  $("#ov-sensors").textContent = `${STATE.sensors.length} sensors (${blocking} blocking) · ${proven} proven by seeded defects`;
  $("#gw-link").href = STATE.gateway; $("#gw-link").textContent = STATE.gateway;
  $("#docs-link").href = STATE.gateway + "/docs"; $("#prom-link").href = STATE.prometheus;
  $("#ov-agent").innerHTML = STATE.agent.available
    ? `<span class="ok">ready</span>: <code>${esc(STATE.agent.cmd)}</code>`
    : `<span class="none">not installed</span> — install Claude Code (or set <code>AGENT_CMD</code>) to run it from here; you can still copy prompts.`;
  renderActions(); renderSensors(); renderReport(); renderTimeline(); renderAgentNote();
  $$("button.act").forEach((b) => (b.disabled = STATE.running !== null));
}

async function loadHealth() {
  try {
    const h = await api("/api/health");
    $("#health").innerHTML = ["gateway", "prometheus"].map((k) => {
      const x = h[k]; const ok = x.ok;
      return `<div><span class="${ok ? "ok" : "down"}">●</span> ${k} — ${ok ? `up (${x.ms} ms)` : esc(x.error || "down")}</div>`;
    }).join("");
  } catch (e) { $("#health").textContent = e.message; }
}

// ---------------------------------------------------------------- harness tab
function renderActions() {
  $("#actions").innerHTML = STATE.actions.map((a) =>
    `<button class="act" data-action="${a.id}" title="${esc(a.cmd)} — ${esc(a.help)}">${esc(a.label)}</button>`).join("");
  $$("button.act").forEach((b) => (b.onclick = () => runAction(b.dataset.action)));
}

function renderSensors() {
  const rows = STATE.sensors.map((s, n) => {
    const last = s.last ? `<span class="${s.last.status}">${s.last.status}</span> <span class="muted small">${s.last.stage} · ${s.last.rev}</span>` : `<span class="none">not run</span>`;
    const st = s.selftest ? `<span class="${s.selftest}">${s.selftest}</span>` : `<span class="none">—</span>`;
    return `<tr class="sensor" data-n="${n}"><td><b>${esc(s.id)}</b><div class="muted small">${esc(s.kind)} · ${esc(s.plane)}</div></td>
      <td>${s.stages.map(esc).join(", ")}</td><td>${s.blocking ? "yes" : "no"}</td><td>${last}</td><td>${st}</td>
      <td class="small">${s.stats.runs} runs · ${s.stats.fired} fired</td></tr>
      <tr class="detail hidden" id="d${n}"><td colspan="6"><div class="small"><b>run:</b> <code>${esc(s.run)}</code></div>
      ${s.fix_hint ? `<div class="small"><b>how to fix:</b> ${esc(s.fix_hint)}</div>` : ""}
      <div class="small"><b>guides:</b> ${s.pairs_with.map(esc).join(", ")}</div>
      ${s.output ? `<pre>${esc(s.output)}</pre>` : ""}</td></tr>`;
  }).join("");
  $("#sensors").innerHTML = `<tr><th>sensor</th><th>stages</th><th>blocking</th><th>last result</th><th>selftest</th><th>history</th></tr>` + rows;
  $$("#sensors tr.detail").forEach((r) => (r.style.display = "none"));
  $$("#sensors tr.sensor").forEach((r) => (r.onclick = () => {
    const d = $("#d" + r.dataset.n); d.style.display = d.style.display === "none" ? "" : "none";
  }));
}

function renderReport() {
  $("#report").innerHTML = STATE.report ? md(STATE.report) : `<p class="muted">No report yet — run the fast loop.</p>`;
  $("#eval-link").innerHTML = STATE.has_eval ? `Search eval: <a href="#" onclick="openFile('.harness/eval-report.md');show('guides');return false">.harness/eval-report.md</a>` : "";
}

// ---------------------------------------------------------------- jobs
let polling = null;
async function runAction(action) {
  try { follow(await api("/api/run", { action })); } catch (e) { alert(e.message); }
}
function follow(job) {
  $("#drawer").classList.remove("hidden");
  $("#job-title").textContent = job.label; $("#job-cmd").textContent = job.cmd;
  $("#job-log").textContent = ""; let since = 0;
  $$("button.act, #run-agent").forEach((b) => (b.disabled = true));
  clearInterval(polling);
  const tick = async () => {
    const j = await api(`/api/jobs/${job.id}?since=${since}`);
    if (j.lines.length) { $("#job-log").textContent += j.lines.join("\n") + "\n"; $("#job-log").scrollTop = 1e9; }
    since = j.next;
    const done = j.finished !== null;
    $("#job-status").textContent = done ? (j.rc === 0 ? "done" : `exit ${j.rc}`) : "running…";
    $("#job-status").className = "pill " + (done ? (j.rc === 0 ? "GREEN" : "RED") : "");
    if (done) { clearInterval(polling); await loadState(); $("#run-agent").disabled = !STATE.agent.available; }
  };
  polling = setInterval(tick, 700); tick();
}
$("#drawer-close").onclick = () => $("#drawer").classList.add("hidden");

// ---------------------------------------------------------------- API tab (generated from the gateway's OpenAPI)
function example(schema, root) {
  if (!schema) return undefined;
  if (schema.$ref) return example(root.components.schemas[schema.$ref.split("/").pop()], root);
  if (schema.example !== undefined) return schema.example;
  if (schema.examples) return Array.isArray(schema.examples) ? schema.examples[0] : Object.values(schema.examples)[0]?.value;
  if (schema.default !== undefined) return schema.default;
  if (schema.type === "object" || schema.properties) {
    const o = {}; for (const [k, v] of Object.entries(schema.properties || {})) o[k] = example(v, root); return o;
  }
  if (schema.type === "array") return [example(schema.items, root)].filter((x) => x !== undefined);
  return { string: "", integer: 1, number: 1, boolean: false }[schema.type];
}

async function loadApi() {
  $("#api-src").textContent = "loading " + (STATE?.gateway || "") + "/openapi.json…";
  try {
    const r = await fetch("/gw/openapi.json");
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    spec = await r.json();
  } catch (e) { $("#api-src").innerHTML = `<span class="down">${esc(e.message)}</span> — start the stack (Overview → Start stack)`; return; }
  $("#api-src").textContent = `${spec.info?.title || "API"} ${spec.info?.version || ""} · ${STATE.gateway}`;
  const ops = [];
  for (const [path, item] of Object.entries(spec.paths)) for (const [method, op] of Object.entries(item)) ops.push({ path, method: method.toUpperCase(), op });
  $("#ops").innerHTML = ops.map((o, n) => {
    const params = (o.op.parameters || []).map((p) => {
      const ex = p.example ?? p.schema?.example ?? p.schema?.default ?? "";
      return `<label>${esc(p.name)} <span class="muted small">${p.in}${p.required ? ", required" : ""}</span></label>
              <input data-p="${esc(p.name)}" data-in="${p.in}" value="${esc(ex)}" placeholder="${esc(p.schema?.type || "")}${p.schema?.pattern ? " " + esc(p.schema.pattern) : ""}">`;
    }).join("");
    const rb = o.op.requestBody?.content?.["application/json"];
    const body = rb ? `<label class="small muted">JSON body</label><textarea data-body rows="8">${esc(JSON.stringify(rb.examples ? Object.values(rb.examples)[0]?.value : (rb.example ?? example(rb.schema, spec)), null, 2))}</textarea>` : "";
    return `<details class="op" data-filter="${esc((o.method + " " + o.path + " " + (o.op.summary || "")).toLowerCase())}">
      <summary><span class="method ${o.method}">${o.method}</span><code>${esc(o.path)}</code><span class="muted">${esc(o.op.summary || "")}</span></summary>
      <div class="body" data-n="${n}">${params ? `<div class="params">${params}</div>` : ""}${body}
        <div class="actions"><button class="primary send">Send</button><button class="curl">Copy curl</button></div>
        <div class="resp"></div></div></details>`;
  }).join("");
  $$("#ops .body").forEach((el) => {
    const o = ops[el.dataset.n];
    const build = () => {
      let path = o.path; const q = new URLSearchParams();
      $$("input[data-p]", el).forEach((i) => {
        if (i.dataset.in === "path") path = path.replace(`{${i.dataset.p}}`, encodeURIComponent(i.value));
        else if (i.value !== "") q.append(i.dataset.p, i.value);
      });
      const qs = q.toString(); return { url: path + (qs ? "?" + qs : ""), body: $("textarea[data-body]", el)?.value };
    };
    $(".send", el).onclick = async () => {
      const { url, body } = build(); const t = performance.now();
      const opts = { method: o.method, headers: { "Content-Type": "application/json", "X-Console": "1" } };
      if (body !== undefined && o.method !== "GET") opts.body = body;
      const r = await fetch("/gw" + url, opts); const text = await r.text(); let pretty = text;
      try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch (_) { /* not JSON */ }
      $(".resp", el).innerHTML = `<div><b class="${r.ok ? "ok" : "fail"}">${r.status}</b> ${esc(o.method)} <code>${esc(url)}</code>
        <span class="muted small">${r.headers.get("X-Upstream-Ms") || Math.round(performance.now() - t)} ms</span></div><pre>${esc(pretty)}</pre>`;
    };
    $(".curl", el).onclick = () => {
      const { url, body } = build();
      navigator.clipboard.writeText(`curl -s -X ${o.method} '${STATE.gateway}${url}'` + (body !== undefined && o.method !== "GET" ? ` -H 'Content-Type: application/json' -d '${body.replace(/\s+/g, " ")}'` : ""));
    };
  });
}
$("#op-filter").oninput = (e) => $$("#ops .op").forEach((d) => (d.style.display = d.dataset.filter.includes(e.target.value.toLowerCase()) ? "" : "none"));

// ---------------------------------------------------------------- agent tab
async function loadPrompts() {
  PROMPTS = await api("/api/prompts");
  $("#prompt-pick").innerHTML = PROMPTS.map((p, n) => `<option value="${n}">${esc(p.title)}</option>`).join("");
  const task = PROMPTS.findIndex((p) => p.id === "task");
  $("#prompt-pick").value = task >= 0 ? task : 0;
  pickPrompt();
}
async function pickPrompt() {
  const p = PROMPTS[$("#prompt-pick").value];
  $("#prompt-when").textContent = p.when ? "When: " + p.when : "";
  $("#task-row").style.display = p.id === "task" ? "" : "none";
  if (p.id === "task" || p.id === "fix-red") {
    const r = await api("/api/prompt", { name: p.id, task: $("#task").value || "<describe the task>" });
    $("#prompt-text").value = r.text;
  } else $("#prompt-text").value = p.text;
}
$("#prompt-pick").onchange = pickPrompt;
let taskTimer = null;
$("#task").oninput = () => { clearTimeout(taskTimer); taskTimer = setTimeout(pickPrompt, 300); };
$("#copy-prompt").onclick = () => navigator.clipboard.writeText($("#prompt-text").value);
$("#copy-cmd").onclick = () => {
  const p = PROMPTS[$("#prompt-pick").value];
  navigator.clipboard.writeText(p.id === "task" ? `claude "$(./help.sh prompt task ${JSON.stringify($("#task").value)})"` : p.id === "fix-red" ? `./help.sh prompt fix-red | claude -p` : p.command);
};
$("#run-agent").onclick = async () => {
  try { follow(await api("/api/agent", { prompt: $("#prompt-text").value })); } catch (e) { alert(e.message); }
};
function renderAgentNote() {
  $("#agent-cmd").innerHTML = `Runs <code>${esc(STATE.agent.cmd)} "&lt;prompt&gt;"</code> in the repository. The agent follows AGENTS.md,
    runs the harness itself, and its Stop hook sends it back while the static sensors are RED.
    Claude Code applies this repository's allowed commands (<code>make harness-*</code>) only after the folder is trusted:
    run <code>claude</code> here once and accept the trust prompt.`;
  $("#run-agent").disabled = !STATE.agent.available || STATE.running !== null;
  $("#agent-note").innerHTML = STATE.agent.available ? "" :
    `The agent CLI <code>${esc(STATE.agent.cmd.split(" ")[0])}</code> is not on this machine's PATH. Install Claude Code, or start the console with
     <code>AGENT_CMD="your-agent --flags" make console</code>. Meanwhile, copy the prompt into any agent.`;
}

function renderTimeline() {
  const runs = [];
  for (const r of STATE.ledger) {
    const last = runs[runs.length - 1];
    const same = last && last.rev === r.rev && last.stage === r.stage && Math.abs(r.ts - last.ts) < 300
      && !last.rows.some((x) => x.id === r.id);                 // a sensor seen twice starts a new run
    if (same) last.rows.push(r);
    else runs.push({ rev: r.rev, stage: r.stage, ts: r.ts, rows: [r] });
  }
  const html = runs.slice(-15).reverse().map((run) => {
    const red = run.rows.some((r) => r.blocking && ["fail", "unavailable", "timeout"].includes(r.status));
    const when = new Date(run.ts * 1000).toLocaleString();
    return `<div class="run ${red ? "RED" : "GREEN"}"><b>${red ? "RED" : "GREEN"}</b> · ${esc(run.stage)} · <code>${esc(run.rev)}</code>
      <span class="muted small">${when}</span><div class="chips">${run.rows.map((r) => `<span class="chip ${r.status}" title="${r.seconds}s">${esc(r.id)}: ${r.status}</span>`).join("")}</div></div>`;
  }).join("");
  $("#timeline").innerHTML = html || `<p class="muted">No runs yet. Run the fast loop, or let an agent work: every harness run it makes shows up here.</p>`;
}

// ---------------------------------------------------------------- guides
async function loadFiles() {
  const files = await api("/api/files"); let group = "";
  $("#files").innerHTML = files.map((f) => {
    const g = f.includes("/") ? f.split("/").slice(0, -1).join("/") : "repository";
    const head = g !== group ? `<li class="group">${esc((group = g))}</li>` : "";
    return head + `<li data-f="${esc(f)}">${esc(f.split("/").pop())}</li>`;
  }).join("");
  $$("#files li[data-f]").forEach((li) => (li.onclick = () => openFile(li.dataset.f)));
}
async function openFile(path) {
  const r = await api("/api/file?path=" + encodeURIComponent(path));
  $("#file-title").textContent = r.path;
  $("#file").innerHTML = r.path.endsWith(".md") ? md(r.text) : `<pre>${esc(r.text)}</pre>`;
  $$("#files li").forEach((li) => li.classList.toggle("active", li.dataset.f === path));
}

// ---------------------------------------------------------------- start
(async () => {
  await loadState(); loadHealth(); loadPrompts();
  setInterval(loadHealth, 15000);
  show(location.hash.slice(1) || "overview");
  if (STATE.running !== null) follow({ id: STATE.running, label: "running job", cmd: "" });
})();
