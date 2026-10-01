/* Receptionist console — vanilla JS, no build. Talks to api_server.py. */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

const store = {
  load() {
    return {
      url: localStorage.getItem("rx_api_url") || "http://127.0.0.1:8090",
      token: localStorage.getItem("rx_api_token") || "",
    };
  },
  save(url, token) {
    localStorage.setItem("rx_api_url", url);
    localStorage.setItem("rx_api_token", token);
  },
};

async function api(path) {
  const { url, token } = store.load();
  const res = await fetch(url.replace(/\/$/, "") + path, {
    headers: token ? { Authorization: "Bearer " + token } : {},
  });
  if (!res.ok) throw new Error(`API ${res.status} on ${path}`);
  return res.json();
}

function setConn(state, text) {
  $("conn-dot").className = "dot " + state;
  $("conn-text").textContent = text;
}

function show(view) {
  document.querySelectorAll("#nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === "view-" + view));
  ({ overview: loadOverview, calls: loadCalls, messages: loadMessages,
     config: loadConfig, spend: loadSpend }[view] || (() => {}))();
}

const fmtDur = (s) =>
  s == null ? "—" : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
};

async function loadOverview() {
  try {
    const [st, calls, spend] = await Promise.all([
      api("/api/status"), api("/api/calls?limit=5"), api("/api/spend"),
    ]);
    setConn("ok", "Connected");
    const bal = spend.balance != null
      ? `$${spend.balance.toFixed(2)} ${esc(spend.currency || "")}` : "—";
    $("overview-cards").innerHTML = [
      [st.calls_recorded, "Calls recorded"],
      [st.messages_recorded, "Messages taken"],
      [bal, "Twilio balance"],
      [fmtDate(st.last_call_at), "Last call"],
    ].map(([v, l]) =>
      `<div class="card"><div class="stat">${esc(v)}</div><div class="stat-label">${esc(l)}</div></div>`
    ).join("");
    $("overview-recent").innerHTML = calls.calls.length
      ? `<table><tr><th>Caller</th><th>Start</th><th>Duration</th><th>Outcome</th></tr>${
        calls.calls.map((c) =>
          `<tr><td>${esc(c.caller)}</td><td>${esc(fmtDate(c.start))}</td><td>${esc(fmtDur(c.duration_seconds))}</td><td>${esc((c.outcomes || []).join(", "))}</td></tr>`
        ).join("")}</table>`
      : `<p class="muted">No calls yet.</p>`;
  } catch (e) {
    setConn("err", "Connection failed");
    $("overview-cards").innerHTML =
      `<div class="card"><span class="error">${esc(e.message)}</span> — check Settings.</div>`;
    $("overview-recent").innerHTML = "";
  }
}

async function loadCalls() {
  const list = $("calls-list");
  try {
    const { calls } = await api("/api/calls?limit=50");
    setConn("ok", "Connected");
    list.innerHTML = calls.length ? "" : `<p class="muted">No calls yet.</p>`;
    calls.forEach((c) => {
      const el = document.createElement("div");
      el.className = "call-item";
      el.innerHTML = `<div><strong>${esc(c.caller || "?")}</strong> · ${esc(fmtDur(c.duration_seconds))}</div>
        <div class="meta">${esc(fmtDate(c.start))} · ${esc((c.outcomes || []).join(", "))}${c.message_taken ? " · message" : ""}</div>`;
      el.onclick = () => {
        list.querySelectorAll(".call-item").forEach((x) => x.classList.remove("selected"));
        el.classList.add("selected");
        loadCallDetail(c.call_id);
      };
      list.appendChild(el);
    });
  } catch (e) {
    setConn("err", "Connection failed");
    list.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

async function loadCallDetail(callId) {
  const box = $("call-detail");
  box.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const { metadata, segments } = await api("/api/calls/" + encodeURIComponent(callId));
    box.innerHTML =
      `<p class="meta muted">${esc(metadata.caller_phone || "")} · ${esc(fmtDate(metadata.start_ts))} · ${esc(fmtDur(metadata.duration_seconds))}</p>` +
      (segments.map((s) =>
        `<p class="seg ${s.role === "user" ? "user" : "agent"}"><span class="who">${s.role === "user" ? "Caller" : "Agent"}</span><br>${esc(s.text)}</p>`
      ).join("") || `<p class="muted">No segments.</p>`);
  } catch (e) {
    box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

async function loadMessages() {
  const box = $("messages-list");
  try {
    const { messages } = await api("/api/messages?limit=50");
    setConn("ok", "Connected");
    box.innerHTML = messages.length ? messages.map((m) =>
      `<div class="card msg-card"><div class="head"><span><strong>${esc(m.caller_name || "?")}</strong> · ${esc(m.callback_number || "")}</span><span>${esc(fmtDate(m.timestamp))}</span></div><div>${esc(m.message)}</div></div>`
    ).join("") : `<p class="muted">No messages taken yet. They appear here when a caller leaves one.</p>`;
  } catch (e) {
    setConn("err", "Connection failed");
    box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

async function loadConfig() {
  const box = $("config-list");
  try {
    const c = await api("/api/config");
    setConn("ok", "Connected");
    const rows = [
      ["Business", `${c.business} (${c.type})`],
      ["Timezone", c.timezone],
      ["Voice model", c.model],
      ["Voice", c.voice],
      ["Languages", (c.languages || []).join(", ")],
      ["FAQs", c.faqs],
      ["Transfer targets", c.transfers],
      ["Greeting", c.greeting],
    ];
    box.innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  } catch (e) {
    setConn("err", "Connection failed");
    box.innerHTML = `<dt>Error</dt><dd class="error">${esc(e.message)}</dd>`;
  }
}

async function loadSpend() {
  const box = $("spend-body");
  try {
    const s = await api("/api/spend");
    setConn("ok", "Connected");
    if (s.error) { box.innerHTML = `<p class="error">${esc(s.error)}</p>`; return; }
    box.innerHTML =
      `<div class="cards"><div class="card"><div class="stat">$${esc(s.balance.toFixed(2))}</div><div class="stat-label">Twilio balance (${esc(s.currency)})</div></div></div>
      <h2>This month</h2>` +
      (s.month_categories.length
        ? `<table><tr><th>Category</th><th>Used</th><th>Cost</th></tr>${s.month_categories.map((c) =>
          `<tr><td>${esc(c.category)}</td><td>${esc(c.used)} ${esc(c.unit)}</td><td>$${esc(Number(c.price).toFixed(4))}</td></tr>`
        ).join("")}</table>`
        : `<p class="muted">No usage recorded.</p>`);
  } catch (e) {
    setConn("err", "Connection failed");
    box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

document.querySelectorAll("#nav button").forEach((b) =>
  b.addEventListener("click", () => show(b.dataset.view)));
$("btn-refresh").addEventListener("click", loadOverview);
$("btn-calls-refresh").addEventListener("click", loadCalls);
$("btn-msg-refresh").addEventListener("click", loadMessages);
$("btn-cfg-refresh").addEventListener("click", loadConfig);
$("btn-spend-refresh").addEventListener("click", loadSpend);

$("settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  store.save($("set-url").value.trim(), $("set-token").value.trim());
  $("settings-msg").textContent = "Saved. Connecting…";
  try {
    await api("/api/status");
    $("settings-msg").textContent = "Connected.";
    show("overview");
  } catch (e) {
    $("settings-msg").textContent = "Failed: " + e.message;
    setConn("err", "Connection failed");
  }
});

// Init
(() => {
  const { url, token } = store.load();
  $("set-url").value = url;
  $("set-token").value = token;
  if (token) show("overview");
  else { show("settings"); setConn("idle", "Set API token first"); }
})();
