// Temporary smoke harness (not shipped): runs the EXACT inline <script>
// from dashboard/index.html with stub DOM + canned API, exercising init,
// full loadAll render, one call-detail expansion, and CSV export.
// Run from repo root (AIReceptionist): node tests/dashboard_smoke.js
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(
  require("path").join(__dirname, "..", "dashboard", "index.html"), "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const main = scripts.find((s) => s.includes("loadAll"));
if (!main) throw new Error("main inline script not found");

// ---- canned API (shapes mirror api_server.py) ----
const NOW = new Date().toISOString();
const canned = {
  "/api/status": { ok: true, business_slug: "test-itspecialists", uptime_seconds: 9,
    calls_recorded: 2, messages_recorded: 1, last_call_at: NOW },
  "/api/calls?limit=200": { calls: [
    { call_id: "c1", caller: "+15550001111", start: NOW, duration_seconds: 92,
      outcomes: ["faq"], message_taken: true, transfer_target: null },
    { call_id: "c2", caller: "+15550002222", start: NOW, duration_seconds: 45,
      outcomes: ["booking_redirect"], message_taken: false, transfer_target: null },
  ]},
  "/api/calls/c1": { metadata: { caller_phone: "+15550001111" },
    segments: [{ role: "agent", text: "Hello" }, { role: "user", text: "Hi" }] },
  "/api/messages?limit=50": { messages: [
    { caller_name: "Andrew", caller_company: "Acme Corp", callback_number: "+15550001111",
      caller_phone: "+15550009999", message: "Call me back", timestamp: NOW },
  ]},
  "/api/spend": { balance: 19.98, currency: "USD",
    month_categories: [{ category: "cat", used: "2", unit: "min", price: 0.01 }] },
  "/api/config": { business: "ITSpecialists", type: "MSP", timezone: "America/Toronto",
    model: "gpt-realtime-2.1-mini", voice: "marin", languages: ["en"],
    faqs: 16, transfers: 0, greeting: "Hello" },
};
const seenAuth = [];
async function fetchStub(url, opts) {
  const path = url.replace("https://api.test", "");
  seenAuth.push((opts && opts.headers && opts.headers.Authorization) || "");
  if (!(path in canned)) return { ok: false, status: 404, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => canned[path] };
}

// ---- stub DOM ----
function makeEl() {
  const el = {
    innerHTML: "", hidden: true, disabled: false,
    dataset: {}, style: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener(ev, fn) { (el._h = el._h || {})[ev] = fn; },
    appendChild(c) { el.children.push(c); return c; },
    setAttribute() {}, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, remove() {}, click() {}, focus() {},
  };
  el.lastChild = el;
  el.nextElementSibling = null;
  let _t = "", _v = "";
  Object.defineProperty(el, "textContent", { get: () => _t, set: (v) => { _t = String(v); } });
  Object.defineProperty(el, "value", { get: () => _v, set: (v) => { _v = String(v); } });
  return el;
}
const byId = {};
const documentStub = {
  querySelector(sel) {
    if (sel.startsWith("#") && !sel.includes(" ") && !sel.includes(".")) {
      const id = sel.slice(1);
      return (byId[id] = byId[id] || makeEl());
    }
    return null;
  },
  querySelectorAll: () => [],
  getElementById(id) { return (byId[id] = byId[id] || makeEl()); },
  createElement: () => makeEl(),
  documentElement: { _a: {}, setAttribute(k, v) { this._a[k] = String(v); }, getAttribute(k) { return this._a[k] ?? null; } },
  addEventListener(ev, fn) { documentStub._h = documentStub._h || {}; documentStub._h[ev] = fn; },
  body: makeEl(),
};
const ls = { rx_api_url: "https://api.test", rx_api_token: "test-token", rx_theme: "ledger" };

const sandbox = {
  document: documentStub,
  window: {}, // no IntersectionObserver -> exercises the guard
  localStorage: {
    getItem: (k) => (k in ls ? ls[k] : null),
    setItem: (k, v) => { ls[k] = v; },
  },
  fetch: fetchStub,
  setTimeout: (fn) => 0, clearTimeout: () => {},
  console,
};
process.on("unhandledRejection", (e) => { console.error("UNHANDLED:", e && e.message || e); });
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const assert = (cond, msg) => {
  if (!cond) { console.error("FAIL:", msg); process.exit(1); }
  console.log("ok:", msg);
};

(async () => {
  vm.runInContext(main, sandbox, { filename: "dashboard-inline.js" });
  for (let i = 0; i < 100 && byId.statusText?.textContent !== "Connected"; i++)
    await new Promise((r) => setImmediate(r));

  assert(byId.statusText.textContent === "Connected" && byId.connDot.className === "dot ok", "init+loadAll connects");
  assert(documentStub.documentElement.getAttribute("data-theme") === "ledger", "saved theme applied on init");
  assert(byId.kpiCalls.textContent === "2", "KPI calls rendered (2)");
  assert(byId.msgList.innerHTML.includes("Andrew"), "message rendered");
  assert(byId.msgList.innerHTML.includes("Acme Corp"), "message company rendered");
  assert(byId.msgList.innerHTML.includes("Called from"), "caller-ID line rendered");
  assert((byId.chart.innerHTML.match(/class="bar/g) || []).length === 5, "chart has 5 bars");
  assert(byId.feed.innerHTML.includes("Call from"), "activity feed rendered");
  assert(byId.spendBody.innerHTML.includes("19.98"), "spend rendered");
  assert(byId.configBox.innerHTML.includes("ITSpecialists"), "config rendered");
  assert(seenAuth.every((a) => a === "Bearer test-token"), "bearer token sent on all calls");

  // interaction: expand first call transcript via delegated document click
  const click = documentStub._h.click;
  const row = makeEl(); row.dataset.i = "0";
  const det = makeEl(); det.hidden = true; byId.cd0 = det;
  documentStub.querySelector = (sel) => {
    if (sel === "#cd0") return det;
    if (sel.startsWith("#") && !sel.includes(" ")) return (byId[sel.slice(1)] = byId[sel.slice(1)] || makeEl());
    return null;
  };
  click({ target: { closest: (s) => (s === "#callsList .qrow" ? row : null) } });
  for (let i = 0; i < 100 && !det.dataset.loaded; i++)
    await new Promise((r) => setImmediate(r));
  assert(det.innerHTML.includes("Caller:"), "call transcript expands");

  // interaction: CSV export must not throw (download guarded)
  byId.exportBtn._h.click();
  assert(true, "export click handled without throwing");

  console.log("SMOKE PASS");
})().catch((e) => { console.error("FAIL:", e); process.exit(1); });
