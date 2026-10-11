"use strict";
// DataSage dashboard. No framework, no build step. All server data is rendered with
// textContent / createElementNS only (no HTML string sinks), so result values cannot inject markup.
(function () {
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  let apiKey = sessionStorage.getItem("datasage-key") || "";

  function el(tag, text, cls) {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  }
  function svg(tag, attrs) {
    const n = document.createElementNS(SVG, tag);
    for (const k in attrs) n.setAttribute(k, String(attrs[k]));
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  async function api(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (apiKey) headers["X-API-Key"] = apiKey;
    const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let msg = data.detail;
      if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
      if (res.status === 401) $("keybar").classList.remove("hidden");
      throw new Error((msg || res.statusText) + " (HTTP " + res.status + ")");
    }
    return data;
  }

  function showError(msg) {
    const box = $("error");
    box.textContent = msg;
    box.classList.toggle("hidden", !msg);
  }

  function fmt(v) {
    if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return v === null ? "NULL" : String(v);
  }

  function renderTable(columns, rows) {
    const t = $("results");
    clear(t);
    const head = el("tr");
    columns.forEach((c) => head.appendChild(el("th", c)));
    const thead = el("thead"); thead.appendChild(head); t.appendChild(thead);
    const tb = el("tbody");
    rows.forEach((r) => {
      const tr = el("tr");
      r.forEach((v) => tr.appendChild(el("td", fmt(v), typeof v === "number" ? "num" : "")));
      tb.appendChild(tr);
    });
    t.appendChild(tb);
  }

  function renderChart(chart, columns, rows) {
    const box = $("chart");
    clear(box);
    $("charttitle").textContent = chart ? chart.title : "Chart";
    if (!chart || chart.type === "table" || !rows.length) {
      box.appendChild(el("p", "No chart for this result shape - see the table.", "muted"));
      return;
    }
    const yi = columns.indexOf(chart.y);
    if (chart.type === "metric") {
      box.appendChild(el("div", fmt(rows[0][yi]), "metric"));
      box.appendChild(el("div", chart.y, "muted"));
      return;
    }
    const xi = columns.indexOf(chart.x);
    const vals = rows.map((r) => Number(r[yi]) || 0);
    const labels = rows.map((r) => String(r[xi]));
    const W = 640, H = 260, L = 60, B = 50, T = 10;
    const max = Math.max(...vals, 0) || 1, min = Math.min(...vals, 0);
    const y = (v) => T + (H - T - B) * (1 - (v - min) / (max - min || 1));
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
    s.appendChild(svg("line", { x1: L, y1: y(0), x2: W, y2: y(0), stroke: "#33414f" }));
    [max, (max + min) / 2, min].forEach((v) => {
      const t = svg("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = fmt(Math.round(v)); s.appendChild(t);
    });
    const step = (W - L) / vals.length;
    const every = Math.ceil(vals.length / 12);
    if (chart.type === "bar") {
      vals.forEach((v, i) => {
        const r = svg("rect", { x: L + i * step + step * 0.15, y: Math.min(y(v), y(0)), width: step * 0.7, height: Math.abs(y(0) - y(v)), fill: "#4cc2ff", rx: 2 });
        const tip = svg("title", {}); tip.textContent = labels[i] + ": " + fmt(v); r.appendChild(tip);
        s.appendChild(r);
      });
    } else {
      const pts = vals.map((v, i) => `${L + i * step + step / 2},${y(v)}`).join(" ");
      s.appendChild(svg("polyline", { points: pts, fill: "none", stroke: "#4cc2ff", "stroke-width": 2 }));
      vals.forEach((v, i) => {
        const c = svg("circle", { cx: L + i * step + step / 2, cy: y(v), r: 3, fill: "#4cc2ff" });
        const tip = svg("title", {}); tip.textContent = labels[i] + ": " + fmt(v); c.appendChild(tip);
        s.appendChild(c);
      });
    }
    labels.forEach((lab, i) => {
      if (i % every) return;
      const t = svg("text", { x: L + i * step + step / 2, y: H - B + 16, "text-anchor": "middle" });
      t.textContent = lab.length > 12 ? lab.slice(0, 11) + "..." : lab;
      s.appendChild(t);
    });
    box.appendChild(s);
  }

  function renderResult(data, summary) {
    showError("");
    $("answer").classList.remove("hidden");
    $("summary").textContent = summary;
    const ul = $("insights"); clear(ul);
    (data.insights || []).forEach((i) => ul.appendChild(el("li", i)));
    renderChart(data.chart, data.columns, data.rows);
    renderTable(data.columns, data.rows);
    $("meta").textContent = `${data.rows.length} rows${data.truncated ? " (truncated)" : ""} - ${data.elapsed_ms.toFixed(1)} ms`;
    $("sql").textContent = data.sql;
    const at = $("attempts"); clear(at);
    const tries = data.attempts || [];
    if (tries.length > 1) {
      tries.forEach((a, i) => {
        const d = el("div", `Attempt ${i + 1}: ${a.error ? "rejected - " + a.error : "accepted"}`, "attempt " + (a.error ? "bad" : "good"));
        at.appendChild(d);
      });
    }
  }

  async function busy(btn, fn) {
    btn.disabled = true;
    try { await fn(); } catch (e) { showError(e.message); } finally { btn.disabled = false; }
  }

  async function ask(q) {
    $("question").value = q;
    const btn = document.querySelector("#askform button");
    await busy(btn, async () => {
      const data = await api("POST", "/api/ask", { question: q });
      renderResult(data, data.summary);
      history.replaceState(null, "", "#q=" + encodeURIComponent(q));
    });
  }

  async function loadSchema() {
    const data = await api("GET", "/api/schema");
    const box = $("schema"); clear(box);
    data.tables.forEach((t) => {
      const d = el("div", null, "tbl");
      d.appendChild(el("b", t.name));
      d.appendChild(el("span", ` (${t.row_count} rows${t.uploaded ? ", uploaded" : ""})`, "muted"));
      d.appendChild(el("div", t.columns.map((c) => c.name + " " + c.type).join(", "), "muted"));
      box.appendChild(d);
    });
  }

  async function init() {
    const cfg = await api("GET", "/api/config");
    $("mode").textContent = `${cfg.access_mode} - provider: ${cfg.provider} - v${cfg.version}`;
    if (cfg.auth_required) $("keybar").classList.remove("hidden");
    $("savekey").addEventListener("click", () => {
      apiKey = $("apikey").value.trim();
      sessionStorage.setItem("datasage-key", apiKey);
      boot();
    });
    $("askform").addEventListener("submit", (e) => { e.preventDefault(); ask($("question").value.trim()); });
    $("runsql").addEventListener("click", (e) => busy(e.target, async () => {
      const data = await api("POST", "/api/sql", { sql: $("rawsql").value });
      renderResult(data, "Raw SQL result");
    }));
    $("upload").addEventListener("click", (e) => busy(e.target, async () => {
      const f = $("dsfile").files[0];
      if (!f) throw new Error("choose a CSV file first");
      if (f.size > cfg.max_upload_bytes) throw new Error("file is larger than " + cfg.max_upload_bytes + " bytes");
      const up = await api("POST", "/api/datasets", { name: $("dsname").value.trim(), csv: await f.text() });
      $("uploadmsg").textContent = `Loaded ${up.name}: ${up.row_count} rows. Try "show ${up.name}".`;
      await loadSchema();
    }));
    $("reset").addEventListener("click", (e) => busy(e.target, async () => {
      await api("DELETE", "/api/datasets");
      $("uploadmsg").textContent = "Workspace reset to the sample dataset.";
      await loadSchema();
    }));
    $("runeval").addEventListener("click", (e) => busy(e.target, async () => {
      const r = await api("POST", "/api/eval");
      $("evalmsg").textContent = `${r.provider}: ${r.passed}/${r.total} correct (${(r.accuracy * 100).toFixed(0)}% execution accuracy)`;
    }));
    boot();
  }

  async function boot() {
    try {
      const ex = await api("GET", "/api/examples");
      const chips = $("examples"); clear(chips);
      ex.examples.forEach((q) => {
        const b = el("button", q); b.type = "button";
        b.addEventListener("click", () => ask(q));
        chips.appendChild(b);
      });
      await loadSchema();
      const m = location.hash.match(/^#q=(.+)$/);
      if (m) ask(decodeURIComponent(m[1]));
    } catch (e) { showError(e.message); }
  }

  init().catch((e) => showError(e.message));
})();
