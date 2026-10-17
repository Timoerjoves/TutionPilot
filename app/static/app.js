"use strict";
/* TuitionPilot UI: a guided story with a live agent panel. Plain JavaScript, no libraries.
   Every number comes from the server's rules engine. The parent's signing key is created and kept in this
   browser (WebCrypto Ed25519, not extractable); the server only ever receives the public key and signatures. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let V = null;                         // session view from the server
let view = store.get("tp.view", "welcome");
let side = store.get("tp.side", "live");
let busy = false;
let seenSeq = Number(store.get("tp.seen", "0"));
let device = null;                    // {privateKey, publicKey, keyId} from IndexedDB
let pin = "";
let labList = null, labResults = {};
let wf = null, wfTimer = null;
let payProgress = null;               // steps shown while a payment runs

const STEPS = [
  { id: "welcome", title: "Welcome", sub: "How your data is used" },
  { id: "invoice", title: "Invoice", sub: "Read and verify" },
  { id: "questions", title: "A few questions", sub: "Asks, never guesses" },
  { id: "route", title: "Best route", sub: "Every rupee explained" },
  { id: "sign", title: "Review & sign", sub: "Parent approves" },
  { id: "receipt", title: "Receipt", sub: "Proof of payment" },
];
const SAMPLES = {
  valid_us: ["good", "Genuine invoice", "Northbridge · USA · USD 20,000"],
  valid_uk: ["good", "Genuine invoice", "Eastholm · UK · GBP 12,000"],
  missing_due_date: ["good", "Missing due date", "Agent must ask, not guess"],
  over_cap: ["good", "Large invoice", "USD 60,000 · above the cap"],
  tampered_bank: ["bad", "Changed bank details", "Classic tuition fraud"],
  injected: ["bad", "Hidden instructions", "Prompt injection in the text"],
  unknown_payee: ["bad", "Look-alike university", "Self-made certificate"],
  revoked_key: ["bad", "Revoked key", "Signed with a leaked old key"],
  unsigned: ["bad", "Unsigned invoice", "No university signature"],
};
const QUESTION_ORDER = ["remitter_name", "pan", "relationship", "funding", "prior_inr", "prior_usd", "prior_other"];

/* ---------- formatting ---------- */
function inr(v, paise = false) {
  if (v === null || v === undefined || v === "") return "–";
  const n = Number(v), neg = n < 0;
  const [w, p] = Math.abs(n).toFixed(2).split(".");
  let head = w.slice(0, -3), groups = [];
  const tail = w.slice(-3);
  while (head.length > 2) { groups.unshift(head.slice(-2)); head = head.slice(0, -2); }
  if (head) groups.unshift(head);
  return `${neg ? "−" : ""}Rs ${[...groups, tail].join(",")}${p !== "00" || paise ? "." + p : ""}`;
}
const money = (v, cur) => `${cur} ${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const usd = (v) => "USD " + Math.round(Number(v)).toLocaleString("en-US");
const tier = (t) => `<span class="tier ${esc(t)}">${esc(t)}</span>`;
const short = (h, n = 12) => (h || "").replace(/^sha256:/, "").slice(0, n) + "…";

/* ---------- crypto helpers (browser side) ---------- */
const utf8 = (s) => new TextEncoder().encode(s);
const b64 = (bytes) => btoa(String.fromCharCode(...bytes));
async function sha256hex(data) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", typeof data === "string" ? utf8(data) : data));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function canon(v) {  // same bytes as Python json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
}
async function planHashHere(plan) {
  const body = { ...plan };
  delete body.plan_hash;
  return "sha256:" + await sha256hex(canon(body));
}
function isoNow() {
  const d = new Date(), off = -d.getTimezoneOffset(), sign = off >= 0 ? "+" : "-";
  const pad = (n) => String(Math.abs(n)).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.trunc(off / 60))}:${pad(off % 60)}`;
}

const idb = {
  open() {
    return new Promise((res, rej) => {
      const r = indexedDB.open("tuitionpilot", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("keys");
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  },
  async run(mode, fn) {
    const db = await this.open();
    return new Promise((res, rej) => {
      const req = fn(db.transaction("keys", mode).objectStore("keys"));
      req.onsuccess = () => res(req.result);
      req.onerror = () => rej(req.error);
    });
  },
  get(k) { return this.run("readonly", (s) => s.get(k)); },
  put(k, v) { return this.run("readwrite", (s) => s.put(v, k)); },
  del(k) { return this.run("readwrite", (s) => s.delete(k)); },
};
async function loadDevice() { try { device = (await idb.get("parent")) || null; } catch { device = null; } }
const deviceRegistered = () => device && V && V.policy.parent_keys.includes(device.keyId);

async function setUpDevice(pinValue) {
  if (!device) {
    const kp = await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"]);
    const raw = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
    device = { privateKey: kp.privateKey, publicKey: b64(raw), keyId: "ed25519:" + (await sha256hex(raw)).slice(0, 16) };
  }
  const r = await api("POST", "/api/parent_key", { pin: pinValue, public_key: device.publicKey, label: "this browser" });
  if (!r.result.allowed) throw new Error(r.result.reason);
  await idb.put("parent", device);
  await refresh();
  return r.result;
}

async function signApproval(plan) {
  const approval = {
    type: "approval", contract_version: "1.1",
    approval_id: "APR-" + (await sha256hex(plan.plan_hash + device.keyId)).slice(0, 12).toUpperCase(),
    plan_id: plan.plan_id, plan_hash: plan.plan_hash, tier: plan.max_tier,
    approver: { role: "parent" }, decision: "approved", method: "pin", decided_at: isoNow(),
  };
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, device.privateKey, utf8(canon(approval))));
  approval.signature = { alg: "Ed25519", key_id: device.keyId, value: b64(sig) };
  return approval;
}

/* ---------- server ---------- */
async function api(method, path, body) {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
async function refresh() { V = (await api("GET", `/api/session/${V.id}`)).view; }

async function act(action, body = {}, { advance = true, quiet = false } = {}) {
  if (busy || !V) return null;
  busy = true;
  const before = progressIndex();
  try {
    const r = await api("POST", `/api/session/${V.id}/${action}`, body);
    if (r.view) V = r.view;
    if (!quiet && r.result && r.result.ok === false) toast(r.result.reason, true);
    if (advance && progressIndex() > before) go(autoStep(), false);
    wf = null;
    render();
    return r;
  } catch (e) {
    toast(e.message, true);
    return null;
  } finally { busy = false; }
}

async function start() {
  await loadDevice();
  const sid = store.get("tp.session");
  if (sid) { try { V = (await api("GET", `/api/session/${sid}`)).view; } catch { V = null; } }
  if (!V) {
    V = (await api("POST", "/api/session", { role: "parent" })).view;
    store.set("tp.session", V.id);
    seenSeq = 0;
    view = "welcome";
  }
  render();
}

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("bad", bad);
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 4500);
}

/* ---------- navigation ---------- */
function progressIndex() {
  if (!V.consent) return 0;
  if (!V.invoice) return 1;
  if (V.question || !V.ranked) return 2;
  if (V.receipt) return 5;
  return 4;
}
function autoStep() { return ["welcome", "invoice", "questions", "route", "route", "receipt"][progressIndex()]; }
function reachable(id) {
  if (id === "lab") return true;
  const i = STEPS.findIndex((s) => s.id === id), p = progressIndex();
  if (id === "receipt") return !!V.receipt;
  return i <= p || (p >= 4 && i <= 4);
}
function go(id, rerender = true) {
  if (!reachable(id)) return;
  view = id;
  store.set("tp.view", id);
  if (rerender) { render(); $("#stage").focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: "smooth" }); }
}

/* ---------- render ---------- */
function render() {
  if (!V) return;
  if (!reachable(view)) view = autoStep();
  $$("[data-role]").forEach((b) => b.classList.toggle("on", b.dataset.role === V.role));
  $$("[data-side]").forEach((b) => b.classList.toggle("on", b.dataset.side === side));
  const chip = $("#device-chip");
  chip.className = "chip-status " + (deviceRegistered() ? "ok" : "warn");
  chip.textContent = deviceRegistered() ? "🔑 Parent device ready" : "🔑 Device not set up";
  renderRail();
  const views = { welcome: vWelcome, invoice: vInvoice, questions: vQuestions, route: vRoute, sign: vSign, receipt: vReceipt, lab: vLab };
  const entering = view !== render.last;  // animate only when moving to another step, not on every update
  render.last = view;
  $("#stage").innerHTML = `<div class="view stack ${entering ? "enter" : ""}">${globalBanners()}${views[view]()}</div>`;
  renderSide();
  after();
}

function renderRail() {
  const p = progressIndex();
  $("#steps").innerHTML = STEPS.map((s, i) => {
    const done = s.id === "receipt" ? !!V.receipt : (i < p && !(s.id === "route" && p === 4)) || (s.id === "route" && !!V.approval) || (s.id === "sign" && !!V.receipt);
    const blocked = s.id === "sign" && (V.escalations || []).length > 0;
    return `<li class="${done ? "done" : ""} ${blocked ? "blocked" : ""}">
      <button class="step-btn ${view === s.id ? "cur" : ""}" data-go="${s.id}" ${reachable(s.id) ? "" : "disabled"}>
        <span class="step-dot">${done ? "✓" : blocked ? "!" : i + 1}</span>
        <span class="step-txt"><b>${s.title}</b><small>${s.sub}</small></span></button></li>`;
  }).join("");
  $("#nav-lab").classList.toggle("cur", view === "lab");
}

function globalBanners() {
  const b = [];
  if (V.policy.emergency_stop) b.push(["deny", "Emergency stop is ON", "Every money action is denied until a parent turns it off in Settings."]);
  if (V.policy.frozen) b.push(["deny", "The agent is frozen", "Too many denied attempts in a row. A parent can reset it in Settings with the PIN."]);
  return b.map(([k, t, d]) => `<div class="banner ${k}"><b>⛔ ${esc(t)}</b><span class="body">${esc(d)}</span></div>`).join("");
}

/* ---------- 1. welcome ---------- */
function vWelcome() {
  return `<section class="card hero">
    <div class="eyebrow">Cross-border student finance</div>
    <h1 style="margin:8px 0 10px">Pay the university abroad, with every rupee explained and nothing moving without you.</h1>
    <p class="lead">TuitionPilot reads the fee invoice, checks it was really signed by the university, works out the yearly LRS limit,
      tax collected at source (TCS) and the true cost of each route, then pays only after a parent signs the exact plan.</p>
    <div class="promises">
      <div class="promise"><span class="ico">🧮</span><b>Code computes</b><span class="muted small">Every number comes from tested rules with sources. The AI only explains, and its numbers are checked.</span></div>
      <div class="promise"><span class="ico">✍️</span><b>Everyone signs</b><span class="muted small">Universities sign invoices; the parent's device signs the plan. The agent can't change either.</span></div>
      <div class="promise"><span class="ico">🏦</span><b>Sandbox only</b><span class="muted small">A simulated bank, synthetic data. No real money ever moves.</span></div>
    </div>
    ${V.consent ? `<div class="row"><button class="btn primary big" data-go="${autoStep() === "welcome" ? "invoice" : autoStep()}">Continue →</button><span class="badge ok">Consent given</span></div>` : `
    <label class="toggle-row"><input type="checkbox" class="sr" id="c1"><span class="switch"></span>
      <span><b>Financial data</b><br><span class="muted small">Use the invoice, the sender's details and this year's earlier payments to work out limits, tax and cost.</span></span></label>
    <label class="toggle-row"><input type="checkbox" class="sr" id="c2"><span class="switch"></span>
      <span><b>AI processing, masked</b><br><span class="muted small">PAN, passport, Aadhaar, account numbers, emails and phones become tokens before any AI sees text. You can see exactly what it saw.</span></span></label>
    <div class="row" style="margin-top:16px"><button class="btn primary big" data-act="consent" id="consent-btn" disabled>Agree and start</button>
      <span class="muted small">You can delete your data at any time.</span></div>`}
  </section>`;
}

/* ---------- 2. invoice ---------- */
function vInvoice() {
  const gallery = (kind) => Object.entries(SAMPLES).filter(([, v]) => v[0] === kind).map(([k, [tag, t, d]]) =>
    `<button class="sample" data-sample="${k}"><span class="tag ${tag}">${tag === "good" ? "Genuine" : "Attack"}</span><b>${esc(t)}</b><small>${esc(d)}</small></button>`).join("");
  const picker = `<section class="card">
      <div class="row between"><h2>${V.invoice ? "Use another invoice" : "Add the university's invoice"}</h2><span class="muted small">Synthetic samples</span></div>
      <div class="drop" id="drop" style="margin:14px 0">
        <div style="font-size:26px">📄</div><b>Drop an invoice file here</b>
        <div class="muted small">or <label class="link" style="cursor:pointer">choose a file<input type="file" id="file" accept=".txt,text/plain" hidden></label>
        · <button class="link" data-act="paste">paste text</button></div>
      </div>
      <h3 style="margin:6px 0 10px">Genuine invoices</h3><div class="samples">${gallery("good")}</div>
      <h3 style="margin:18px 0 10px">Attacks to try</h3><div class="samples">${gallery("bad")}</div>
    </section>`;
  if (!V.invoice) return picker;
  const t = V.trust || { chain: [], verified: false };
  const inv = V.invoice, p = inv.payee || {}, b = p.bank || {}, a = inv.amount || {};
  const unc = new Set(V.uncertain || []);
  const f = (k, label, val) => `<div class="field" ${unc.has(k) ? 'style="border-color:var(--warn)"' : ""}><small>${esc(label)}</small><b>${val ? esc(val) : '<span class="badge warn">missing</span>'}</b></div>`;
  const chain = t.chain.map((c, i) => `<div class="link-node ${c.ok ? "ok" : "bad"}" style="animation-delay:${i * 260}ms">
      <span class="node">${c.ok ? "✓" : "✕"}</span><div><b>${esc(c.step)}</b><small>${esc(c.detail)}</small></div></div>`).join("");
  const flags = (V.flags || []).map((x) => `<div class="banner warn"><b>⚠ Ignored instructions</b><span class="body">The ${esc(x.source)} contained text that looks like ${esc(x.categories)}. Documents can't instruct the agent.</span></div>`).join("");
  return `<div class="grid-2">
      <section class="card">
        <div class="row between"><h2>Signature check</h2>${t.verified ? '<span class="badge ok">✓ Verified</span>' : '<span class="badge deny">✕ Not verified</span>'}</div>
        <p class="muted small">The agent trusts one root key, not a list. It checks every link below.</p>
        <div class="chain" style="margin-top:14px">${chain}</div>
        ${t.verified ? "" : `<div class="banner deny"><b>Will not pay.</b><span class="body">${esc(t.reason || "")}. Paying an unverified payee is tier T4: never allowed.</span></div>`}
      </section>
      <section class="card">
        <div class="row between"><h2>What the agent read</h2><span class="muted small">${t.verified ? "from the signed data" : "from the printed text"}</span></div>
        <div class="fields" style="margin-top:12px">
          ${f("payee", "Payee", p.name)}${f("invoice_id", "Invoice", inv.invoice_id)}
          ${f("amount", "Amount", a.value ? money(a.value, a.currency) : "")}${f("due_on", "Due", inv.due_on)}
          ${f("bank", "Bank account", b.account_masked)}${f("swift", "SWIFT", b.swift)}
          ${f("student", "Student", (inv.student || {}).name)}${f("country", "Country", p.country)}
        </div>
        <div class="row" style="margin-top:18px"><button class="btn primary" data-go="${V.question ? "questions" : V.ranked ? "route" : "questions"}">Continue →</button></div>
      </section>
    </div>${flags}${picker}`;
}

/* ---------- 3. questions ---------- */
function vQuestions() {
  const q = V.question;
  const chat = `<details class="more" ${q ? "" : "open"}><summary>Conversation</summary><div>
      <div class="chatlog" id="chatlog">${V.chat.map((m) => `<div class="msg ${esc(m.who)} ${esc(m.tone || "")}">${esc(m.text)}</div>`).join("")}</div>
      <form class="ask" id="ask" autocomplete="off"><input id="ask-in" placeholder="Ask why, about tax, or about your limit…" aria-label="Ask TuitionPilot">
        <button class="btn">Ask</button></form></div></details>`;
  if (!q) {
    return `<section class="card qcard"><div style="font-size:40px">✅</div><h2>All set, no guessing needed.</h2>
      <p class="muted">The agent has what it needs to compare routes.</p>
      <button class="btn primary big" data-go="route" style="margin-top:12px">See the best route →</button></section>${chat}`;
  }
  const idx = QUESTION_ORDER.indexOf(q.field);
  const dots = idx >= 0 ? `<div class="qprogress">${QUESTION_ORDER.map((_, i) => `<i class="${i <= idx ? "on" : ""}"></i>`).join("")}</div>` : `<div class="qprogress"><i class="on"></i></div>`;
  const last = [...V.chat].reverse().find((m) => m.who === "agent");
  const hint = last && last.text !== q.text ? `<p class="small" style="color:var(--warn)">${esc(last.text)}</p>` : "";
  const choices = q.kind === "choice"
    ? `<div class="choices">${q.options.map((o) => `<button class="choice" data-answer="${esc(o)}">${esc(o)}</button>`).join("")}</div>`
    : `<form class="answer-row" id="answer" autocomplete="off">
        <input id="answer-in" ${q.kind === "date" ? 'type="date"' : ""} placeholder="${q.field === "pan" ? "e.g. ABCDE1234F (synthetic)" : q.kind === "number" ? "e.g. 6 lakh or 600000" : "Type your answer"}" aria-label="Answer">
        <button class="btn primary">Next</button></form>
      ${q.options ? `<div class="choices" style="margin-top:10px">${q.options.map((o) => `<button class="choice" data-answer="${esc(o)}">${esc(o)}</button>`).join("")}</div>` : ""}`;
  return `<section class="card qcard">${dots}<div class="qtext">${esc(q.text)}</div>${hint}${choices}
      <p class="faint tiny" style="margin-top:16px">${q.field === "pan" ? "Your PAN is masked immediately and never shown to the AI." : "The agent asks instead of guessing."}</p></section>${chat}`;
}

/* ---------- 4. route ---------- */
function vRoute() {
  if (!V.ranked) return empty("Finish the questions first", "The routes appear once the agent has everything it needs.", "questions");
  const chosen = V.ranked.find((r) => r.quote.quote_id === V.chosen_quote_id) || V.ranked[0];
  const best = V.ranked[0], ex = V.explanation;
  const extra = (r) => {
    const g = (label) => Number((r.lines.find((l) => l.label === label) || {}).amount_inr || 0);
    return { markup: Math.max(0, Number(r.markup ? r.markup.amount_inr : 0)), fee: g("Provider fee"), gst: g("GST on fee"), corr: g("Correspondent charges"), tcs: g("TCS") };
  };
  const maxExtra = Math.max(...V.ranked.map((r) => Object.values(extra(r)).reduce((x, y) => x + y, 0)));
  const COLORS = { markup: ["--c-markup", "Hidden FX markup"], fee: ["--c-fee", "Provider fee"], gst: ["--c-gst", "GST on fee"], corr: ["--c-corr", "Correspondent"], tcs: ["--c-tcs", "TCS (tax)"] };
  const bars = V.ranked.map((r) => {
    const e = extra(r), sum = Object.values(e).reduce((x, y) => x + y, 0);
    const segs = Object.entries(e).filter(([, v]) => v > 0).map(([k, v]) =>
      `<span class="seg-b" style="width:${(v / maxExtra) * 100}%;background:var(${COLORS[k][0]})" title="${esc(COLORS[k][1])}: ${esc(inr(v))}"></span>`).join("");
    return `<div class="bar-row ${r.quote.quote_id === V.chosen_quote_id ? "chosen" : ""}" data-route="${esc(r.quote.quote_id)}" role="button" tabindex="0">
      <span class="name"><b>${esc(r.route)}</b><small>#${r.rank}${r.rank === 1 ? " · cheapest" : ""}</small></span>
      <span class="bar">${segs}</span>
      <span class="tot num" style="text-align:right"><b>${esc(r.total_display)}</b><br><small class="muted">+${esc(inr(sum))} on top</small></span></div>`;
  }).join("");
  const why = (ex.why || []).map((w) => {
    const v = Number(w.amount_inr);
    return `<div class="why-row"><span>${esc(w.label)}${w.unverified.length ? ' <span class="badge warn">unverified</span>' : ""}</span>
      <span class="v ${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "saves" : "costs"} ${esc(inr(Math.abs(v)))}</span></div>`;
  }).join("");
  const banners = [...(V.escalations || []).map((e) => `<div class="banner deny"><b>Needs a human</b><span class="body">${esc(e.text)}</span></div>`),
    ...(V.warnings || []).map((w) => `<div class="banner warn"><b>Check</b><span class="body">${esc(w)}</span></div>`)].join("");
  const prior = V.prior_used && Number(V.prior_used.paid_here_inr) > 0
    ? `<span class="badge info">Includes ${esc(inr(V.prior_used.paid_here_inr))} you paid here this year</span>` : "";
  return `${banners}
    <section class="card hero">
      <div class="eyebrow">Recommended route</div>
      <div class="headline" style="margin-top:6px"><span class="big-amount num" data-count="${esc(chosen.total_inr)}">${esc(chosen.total_display)}</span>
        <span><b style="font-size:18px">${esc(chosen.route)}</b><br><span class="muted small">${esc(chosen.quote.provider)} · rate ${esc(chosen.quote.fx_rate)} INR per ${esc(chosen.quote.foreign_amount.currency)}</span></span></div>
      <p style="margin-top:12px">${esc(ex.summary)}</p>
      <div class="row">${ex.source === "model" ? '<span class="badge ok" title="Every number the AI wrote matched the rules engine">✓ AI wording · every number checked</span>' : '<span class="badge warn">AI text rejected · engine wording shown</span>'}
        ${prior}${chosen.quote.quote_id !== best.quote.quote_id ? '<span class="badge warn">Not the cheapest: you chose this</span>' : ""}</div>
    </section>
    <section class="card">
      <div class="row between"><h2>What you pay on top of the real exchange value</h2><button class="btn sm ghost" data-act="refresh">↻ New quotes</button></div>
      <p class="muted small">Tap a route to choose it. The bar is everything above the mid-market value of the amount you send.</p>
      <div class="chart" style="margin-top:12px">${bars}</div>
      <div class="legend" style="margin-top:12px">${Object.values(COLORS).map(([c, l]) => `<span><i style="background:var(${c})"></i>${esc(l)}</span>`).join("")}</div>
    </section>
    <div class="grid-2">
      <section class="card"><h2>Why ${esc(best.route)} wins</h2><div class="why" style="margin-top:12px">${why || '<p class="muted">Only one route.</p>'}</div>
        ${chosen.markup ? `<div class="callout" style="margin-top:12px">🔎 <b>Hidden markup ${esc(inr(chosen.markup.amount_inr))}</b><br>${esc(chosen.markup.text)}</div>` : ""}</section>
      <section class="card">${gauge()}</section>
    </div>
    <section class="card whatif">
      <div class="row between"><h2>What if…</h2><span class="badge info">Try it: your plan does not change</span></div>
      <div class="grid-2" style="margin-top:12px">
        <div class="stack">
          <div class="ctrl"><label for="wf-prior">Already sent abroad this year: <span id="wf-prior-v" class="num"></span></label>
            <input type="range" id="wf-prior" min="0" max="4000000" step="50000"></div>
          <div class="ctrl"><label>Paid from</label><div class="seg"><button class="seg-btn" data-wf-funding="self">Own money</button><button class="seg-btn" data-wf-funding="loan">Education loan</button></div></div>
          <div class="ctrl"><label>Sender has a PAN</label><div class="seg"><button class="seg-btn" data-wf-pan="1">Yes</button><button class="seg-btn" data-wf-pan="0">No</button></div></div>
        </div>
        <div id="wf-out"><div class="empty"><span class="spinner"></span></div></div>
      </div>
    </section>
    <details class="more"><summary>Every rupee of ${esc(chosen.route)}, with the rules used</summary><div>
      <ul class="lines">${chosen.lines.map((l) => `<li><span>${esc(l.label)} ${l.unverified.length ? `<span class="badge warn" title="${esc(l.unverified.join(", "))}">unverified rule</span>` : ""}</span>
        <b class="num">${esc(inr(l.amount_inr))}</b>${l.label !== "Total" ? `<small>${esc(l.text)}</small>` : ""}</li>`).join("")}</ul></div></details>
    <div class="row"><button class="btn primary big" data-go="sign">Review &amp; sign →</button><span class="muted small">Tax figures are not tax advice. Rules marked unverified still need checking against RBI / Income Tax sources.</span></div>`;
}

function gauge() {
  const l = V.lrs;
  if (!l) return "";
  const cap = Number(l.cap_usd), before = Number(l.headroom_before_usd), amount = Number(l.amount_usd);
  const used = Math.max(0, cap - before), L = Math.PI * 80;
  const usedLen = Math.min(L, used / cap * L), thisLen = Math.max(0, Math.min(L - usedLen, amount / cap * L));
  const fits = l.within_cap;
  return `<div class="row between"><h2>Yearly LRS limit</h2><span class="badge ${fits ? "ok" : "deny"}">${fits ? "Within limit" : "Over: stopped"}</span></div>
    <div class="gauge-wrap" style="margin-top:8px">
      <svg class="gauge" viewBox="0 0 180 104" role="img" aria-label="LRS limit used">
        <path d="M10 94 A80 80 0 0 1 170 94" fill="none" stroke="var(--surface-2)" stroke-width="16" stroke-linecap="round"/>
        <path d="M10 94 A80 80 0 0 1 170 94" fill="none" stroke="var(--t0)" stroke-width="16" stroke-dasharray="${usedLen} ${L}"/>
        <path d="M10 94 A80 80 0 0 1 170 94" fill="none" stroke="${fits ? "var(--accent)" : "var(--deny)"}" stroke-width="16" stroke-dasharray="0 ${usedLen} ${thisLen} ${L}"/>
        <text x="90" y="82" text-anchor="middle">${Math.round((used + amount) / cap * 100)}%</text>
        <text x="90" y="100" text-anchor="middle" class="lbl">of USD ${(cap / 1000).toFixed(0)}k used</text>
      </svg>
      <div class="small"><p><span class="badge muted">Earlier</span> ${usd(used)}</p><p><span class="badge info">This payment</span> ${usd(amount)}${l.estimated ? " (est.)" : ""}</p>
        <p><b>Left after: ${usd(l.headroom_after_usd)}</b></p><p class="faint tiny">Cap rule is marked unverified in the rule pack.</p></div>
    </div>`;
}

async function whatif() {
  if (!V || !V.ranked || view !== "route") return;
  if (!wf) {
    wf = { prior: Number(V.prior_used ? V.prior_used.total_inr : 0), funding: V.answers_funding || null, has_pan: null, base: null };
  }
  const slider = $("#wf-prior");
  if (slider && !slider.dataset.init) { slider.value = String(wf.prior); slider.dataset.init = "1"; }
  $("#wf-prior-v").textContent = inr(wf.prior);
  try {
    const body = { prior_inr: String(wf.prior) };
    if (wf.funding) body.funding = wf.funding;
    if (wf.has_pan !== null) body.has_pan = wf.has_pan;
    const r = (await api("POST", `/api/session/${V.id}/whatif`, body)).result;
    if (!wf.base) wf.base = Object.fromEntries(V.ranked.map((x) => [x.route, Number(x.total_inr)]));
    wf.funding = r.inputs.funding;
    wf.has_pan = r.inputs.has_pan;
    $$("[data-wf-funding]").forEach((b) => b.classList.toggle("on", b.dataset.wfFunding === wf.funding));
    $$("[data-wf-pan]").forEach((b) => b.classList.toggle("on", (b.dataset.wfPan === "1") === wf.has_pan));
    $("#wf-out").innerHTML = `<table class="wf-table"><thead><tr><th>Route</th><th>TCS</th><th>Total</th><th>vs now</th></tr></thead><tbody>
      ${r.routes.map((x) => { const d = Number(x.total_inr) - (wf.base[x.route] || 0);
        return `<tr><td>${esc(x.route)}${x.route === r.cheapest ? ' <span class="badge ok">best</span>' : ""}</td><td class="num">${esc(inr(x.tcs_inr))}</td>
          <td class="num"><b>${esc(inr(x.total_inr))}</b></td><td class="num delta ${d > 0 ? "up" : d < 0 ? "down" : ""}">${d === 0 ? "–" : (d > 0 ? "+" : "−") + esc(inr(Math.abs(d)).replace("Rs ", "Rs "))}</td></tr>`; }).join("")}
      </tbody></table><p class="small" style="margin-top:10px">${esc(r.tcs_sentence)}</p>
      ${r.warnings.map((w) => `<p class="small" style="color:var(--warn)">⚠ ${esc(w)}</p>`).join("")}`;
  } catch (e) { $("#wf-out").innerHTML = `<p class="muted small">${esc(e.message)}</p>`; }
}

/* ---------- 5. sign ---------- */
function vSign() {
  if (!V.plan) return empty("No plan yet", "The plan appears once the routes are compared.", "route");
  const p = V.plan, approved = V.approval && V.approval.plan_hash === V.plan_hash_now, voided = V.approval && !approved;
  const steps = p.steps.map((s) => `<li><span class="pn">${s.n}</span><span>${esc(s.action)}<br><span class="faint mono">${esc(s.tool)}</span></span>${tier(s.tier)}</li>`).join("");
  const plan = `<section class="card">
      <div class="row between"><h2>The plan</h2>${approved ? '<span class="badge ok">✓ Signed</span>' : voided ? '<span class="badge deny">Signature void: plan changed</span>' : '<span class="badge muted">Waiting for the parent</span>'}</div>
      <ul class="plan-steps" style="margin-top:8px">${steps}</ul>
      <h3 style="margin:14px 0 6px">What the parent signs</h3>
      <div class="hashbox">${esc(V.plan_hash_now)}</div>
      <p class="small" id="hash-check"><span class="spinner"></span> Your device is recomputing the plan hash…</p>
      <p class="faint tiny">T0 read · T1 compute and draft · T2 save or share · T3 sandbox payment (PIN + device signature) · T4 never allowed.</p>
    </section>`;
  let panel;
  if (payProgress) panel = `<section class="card"><h2>Sending in the sandbox…</h2><ul class="progress-list" style="margin-top:12px">${payProgress.map((x, i) =>
      `<li class="${x.ok ? "" : "bad"}" style="animation-delay:${i * 380}ms"><span class="ic">${x.ok ? "✓" : "✕"}</span><span><b>${esc(x.t)}</b><br><span class="muted small">${esc(x.d)}</span></span></li>`).join("")}</ul></section>`;
  else if (V.receipt) panel = `<section class="card"><h2>Paid ✓</h2><p class="muted">This plan was signed and paid in the sandbox.</p><button class="btn primary" data-go="receipt">See the receipt →</button></section>`;
  else if (V.role !== "parent") panel =`<section class="card"><h2>Parent approval needed</h2><p>You're viewing as the <b>student</b>. You can review everything; only the parent's device can sign a payment.</p>
      <button class="btn" data-role="parent">Switch to parent</button></section>`;
  else if (p.max_tier === "T4") panel = `<section class="card"><h2>Cannot be signed</h2><div class="banner deny"><b>T4: never allowed.</b><span class="body">This plan would pay an unverified payee. No PIN or signature can allow it. Confirm the university's details by phone, using a number from its official website.</span></div>
      <button class="btn danger" data-act="force-approve" style="margin-top:12px">Try to approve anyway</button></section>`;
  else if ((V.escalations || []).length) panel = `<section class="card"><h2>Needs a human first</h2>${V.escalations.map((e) => `<div class="banner deny" style="margin-top:10px"><span class="body">${esc(e.text)}</span></div>`).join("")}</section>`;
  else if (approved) panel = `<section class="card"><div class="row between"><h2>Signed by the parent</h2>${tier("T3")}</div>
      <p class="muted small">Key <span class="mono">${esc(V.approval.signature.key_id)}</span> signed plan <span class="mono">${esc(short(V.approval.plan_hash))}</span>. The agent can't change the plan without breaking this signature.</p>
      <button class="btn primary big" data-act="pay" style="margin-top:12px">Send payment (sandbox)</button>
      <p class="faint tiny" style="margin-top:8px">Balance ${esc(inr(V.balance_inr))}</p></section>
      <section class="card" style="border-style:dashed"><div class="row between"><h3>Attack demo</h3><span class="badge warn">for judges</span></div>
      <p class="small muted">Change the amount in the plan after it was signed, as a compromised agent might.</p><button class="btn sm danger" data-act="tamper_plan">Tamper with the plan</button></section>`;
  else if (!deviceRegistered()) panel = `<section class="card"><div class="row between"><h2>Set up the parent's device</h2>${tier("T2")}</div>
      <p class="muted small">This browser makes a signing key that never leaves it. The agent only learns the public half. Enter the parent PIN to register it.</p>
      ${pinPad("Register this device")}</section>`;
  else panel = `<section class="card"><div class="row between"><h2>Sign &amp; approve</h2>${tier("T3")}</div>
      <p class="muted small">Your device signs this exact plan with its key. ${voided ? "<b>The plan changed, so sign again.</b>" : ""}</p>
      ${pinPad("Sign & approve")}</section>`;
  return `<div class="signing"><div class="stack">${plan}${draftCard()}</div><div class="stack">${panel}</div></div>`;
}

function pinPad(label) {
  return `<div class="pin-dots">${[0, 1, 2, 3].map((i) => `<i class="${i < pin.length ? "on" : ""}"></i>`).join("")}</div>
    <div class="pinpad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button data-pin="${n}">${n}</button>`).join("")}
      <button data-pin="back" aria-label="Delete">⌫</button><button data-pin="0">0</button><button data-pin="ok" aria-label="${esc(label)}">✓</button></div>
    <button class="btn primary big" data-pin="ok" style="width:100%;margin-top:12px" ${pin.length < 4 ? "disabled" : ""}>${esc(label)}</button>
    <p class="faint tiny" style="text-align:center;margin-top:8px">Demo PIN is in the README · you can also type it</p>`;
}

function draftCard() {
  const d = V.draft;
  if (!d) return "";
  const st = { ready: ["ok", "Ready"], needs_information: ["warn", "Needs information"], blocked: ["deny", "Blocked"] }[d.status] || ["muted", d.status];
  const s = d.sections;
  const sec = (title, obj) => `<h4 class="eyebrow" style="margin:14px 0 6px;color:var(--muted)">${esc(title)}</h4><dl class="kv">${Object.entries(obj).map(([k, v]) =>
    `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${v === null || v === undefined ? '<span class="badge warn">missing</span>' : esc(v)}</dd>`).join("")}</dl>`;
  return `<details class="more"><summary>A2-style form draft · <span class="badge ${st[0]}">${esc(st[1])}</span> · ${d.missing_documents.length} documents missing</summary><div>
    <p class="faint tiny">${d.labels.map(esc).join(" · ")}</p>
    ${sec("Remitter", s.remitter)}${sec("Beneficiary", s.beneficiary)}${sec("Remittance", s.remittance)}
    ${sec("Purpose", { code: s.purpose.code + " (unverified)", description: s.purpose.description })}
    <h4 class="eyebrow" style="margin:14px 0 6px;color:var(--muted)">Documents</h4>
    ${d.checklist.map((c) => `<label class="toggle-row" style="padding:8px 0"><input type="checkbox" class="sr" data-doc="${esc(c.key)}" ${c.status === "have" ? "checked" : ""}><span class="switch"></span><span class="small">${esc(c.item)}</span></label>`).join("")}
    <p class="faint tiny">Typical list; confirm with your bank. Unverified: ${esc(d.needs_verification.join(", "))}</p></div></details>`;
}

/* ---------- 6. receipt ---------- */
function vReceipt() {
  if (!V.receipt) return empty("No payment yet", "Sign and send the plan first.", "sign");
  const r = V.receipt;
  return `<section class="card receipt-hero">
      <div class="check-anim"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
      <div class="eyebrow">Paid in the sandbox</div>
      <div class="big-amount num" style="margin:8px 0">${esc(inr(V.txn.debit_inr))}</div>
      <p class="muted">${esc(r.inputs_masked.amount)} to ${esc(r.inputs_masked.payee)} via ${esc(r.route)}</p>
    </section>
    <section class="card" id="receipt">
      <div class="row between"><h2>Decision receipt</h2><span class="badge ok">✓ Verifiable</span></div>
      <dl class="kv" style="margin-top:12px">
        <dt>Receipt</dt><dd class="mono">${esc(r.receipt_id)}</dd><dt>Transaction</dt><dd class="mono">${esc(r.txn_id)}</dd>
        <dt>University</dt><dd>${esc(r.inputs_masked.payee)} · certificate <span class="mono">${esc(r.payee_certificate)}</span></dd>
        <dt>Signed by parent</dt><dd><span class="mono">${esc(r.approval.signed_by)}</span> · PIN · ${esc(r.approval.decided_at)}</dd>
        <dt>Signature</dt><dd class="mono">${esc(short(r.approval.signature, 32))}</dd>
        <dt>Plan hash</dt><dd class="mono">${esc(r.plan_hash)}</dd><dt>Audit entry</dt><dd class="mono">${esc(r.audit_entry_hash)}</dd>
        <dt>Remitter PAN</dt><dd>${esc(r.inputs_masked.remitter_pan)}</dd>
        <dt>Rules used</dt><dd>${r.rules_used.map((u) => `${esc(u.rule_id)} <span class="badge ${u.status === "unverified" ? "warn" : "muted"}">${esc(u.status)}</span>`).join("<br>")}</dd>
      </dl>
      <p class="faint tiny" style="margin-top:12px">${r.labels.map(esc).join(" · ")}</p>
      <div class="row no-print" style="margin-top:12px"><button class="btn" data-act="print">Print</button>
        <button class="btn" data-act="pay">Send again (test: pays once)</button><button class="btn primary" data-go="invoice">Pay another invoice</button></div>
    </section>`;
}

/* ---------- attack lab ---------- */
function vLab() {
  if (!labList) {
    api("GET", "/api/lab").then((r) => { labList = r.attacks; render(); }).catch((e) => toast(e.message, true));
    return `<div class="empty"><span class="spinner"></span></div>`;
  }
  const done = Object.values(labResults).filter((x) => x && x !== "running");
  const stopped = done.filter((x) => x.stopped).length;
  return `<section class="card hero"><div class="eyebrow">Attack lab</div><h1 style="margin:6px 0">Try to break TuitionPilot</h1>
      <p class="lead">Each attack runs against a fresh, separate copy of the agent and bank, never your session. You see which defence stopped it.</p>
      <div class="row" style="margin-top:12px"><button class="btn primary big" data-act="lab-all">Run all ${labList.length} attacks</button>
        ${done.length ? `<span class="badge ${stopped === done.length ? "ok" : "deny"}">${stopped} of ${done.length} stopped</span>` : ""}</div></section>
    <div class="lab-grid">${labList.map((a) => {
      const r = labResults[a.id];
      const res = r === "running" ? `<div class="res"><span class="spinner"></span> Attacking…</div>`
        : r ? `<div class="res ${r.stopped ? "ok" : "bad"}"><span class="shield">${r.stopped ? "🛡" : "⚠"}</span> <b>${r.stopped ? "Stopped by" : "NOT stopped:"} ${esc(r.defence)}</b><br><span class="muted">${esc(r.actual)}</span></div>` : "";
      return `<div class="attack ${r && r !== "running" && r.stopped ? "stopped" : ""}"><span class="who">Attacker tries</span><b>${esc(a.attack)}</b>
        <span class="muted small">Defence: ${esc(a.defence)}</span>${res}
        <button class="btn sm" data-lab="${esc(a.id)}" ${r === "running" ? "disabled" : ""}>${r ? "Run again" : "Run attack"}</button></div>`;
    }).join("")}</div>`;
}

function empty(t, d, goTo) {
  return `<section class="card" style="text-align:center;padding:50px 20px"><h2>${esc(t)}</h2><p class="muted">${esc(d)}</p><button class="btn" data-go="${goTo}">Go back</button></section>`;
}

/* ---------- live panel ---------- */
const EV = {
  session_started: "Session started", consent: "Consent", role_switched: "Role switched", plan_built: "Plan built",
  approved: "Parent signature accepted", approval_refused: "Approval refused", approval_void: "Approval voided",
  payment_executed: "Payment executed (sandbox)", receipt_written: "Receipt written", escalated: "Escalated to a human",
  route_chosen: "Route chosen", document_marked: "Document marked", duplicate_click: "Duplicate click ignored",
  bank_refused: "Bank refused", plan_tampered_demo: "Plan tampered (demo)", payment_refused: "Payment refused",
  untrusted_text_flagged: "Untrusted text flagged",
};
function describe(e) {
  const d = e.data || {};
  if (e.event === "policy_decision") return [`${d.allowed ? "Allowed" : "Denied"} · ${d.action}`, `${d.tier} · ${d.reason}`, d.allowed ? "allow" : "deny"];
  if (e.event === "tool_call") {
    if (d.tool === "check_payee") return [`Signature chain ${d.verified ? "verified" : "failed"}`, (d.chain || []).join(" → ") + (d.reason ? ` · ${d.reason}` : ""), d.verified ? "sig" : "deny"];
    return [`Tool · ${d.tool}`, [d.tier, d.cheapest && "cheapest " + d.cheapest, d.grounded !== undefined && "grounded " + d.grounded].filter(Boolean).join(" · "), ""];
  }
  if (e.event === "untrusted_text_flagged") return [EV[e.event], `${d.source}: ${(d.findings || []).map((f) => f.category).join(", ")}`, "flag"];
  if (e.event === "plan_built") return [EV[e.event], `${d.plan_id} · max ${d.max_tier} · ${short(d.plan_hash)}`, ""];
  if (["approval_refused", "bank_refused", "payment_refused", "approval_void", "escalated"].includes(e.event)) return [EV[e.event], d.reason || (d.codes || []).join(", "), "deny"];
  if (["approved", "payment_executed", "receipt_written"].includes(e.event)) return [EV[e.event], d.key_id || d.txn_id || d.receipt_id || "", e.event === "approved" ? "sig" : "allow"];
  return [EV[e.event] || e.event, Object.entries(d).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "), ""];
}
function renderSide() {
  let html = "";
  if (side === "live") {
    const pipe = `<ul class="pipe">${V.timeline.map((s) => `<li class="${s.status}"><i></i>${s.n}. ${esc(s.name)}</li>`).join("")}</ul>`;
    const evs = [...V.events].reverse();
    let fresh = 0;
    html = pipe + (evs.length ? evs.map((e) => {
      const [t, m, cls] = describe(e);
      const isNew = e.seq > seenSeq;
      const delay = isNew ? (fresh++) * 0 : 0;
      return `<div class="ev ${cls} ${isNew ? "new" : ""}" style="animation-delay:${delay}ms"><span class="p"></span><div><div class="t">${esc(t)}</div><div class="m">${esc(m)}</div><div class="m mono">#${e.seq} · ${esc(e.at)}</div></div></div>`;
    }).join("") : `<div class="empty">Agent steps and policy decisions stream here.</div>`);
    if (evs.length) { seenSeq = Math.max(seenSeq, evs[0].seq); store.set("tp.seen", String(seenSeq)); }
  } else if (side === "rules") {
    const chosen = (V.ranked || []).find((r) => r.quote.quote_id === V.chosen_quote_id);
    const rows = [...(chosen ? chosen.trace : []), ...(V.lrs ? V.lrs.trace : [])];
    html = rows.length ? `<div class="side-pad">${rows.map((t) => {
      const src = /^https?:\/\//.test(t.source) ? `<a href="${esc(t.source)}" target="_blank" rel="noopener noreferrer">source ↗</a>` : esc(t.source);
      return `<div class="trace-row"><div class="row between"><b>${esc(t.rule_id)}</b><span class="badge ${t.status === "unverified" ? "warn" : "muted"}">${esc(t.status)}</span></div>
        <div class="mono">${esc(t.value)}</div><div class="muted tiny">from ${esc(t.effective_from || "date not set")} · pack ${esc(t.pack_version)} · ${src}</div></div>`;
    }).join("")}</div>` : `<div class="empty">Every rule behind the numbers, with its source, appears here.</div>`;
  } else if (side === "model") {
    html = V.model_saw.length ? `<div class="side-pad saw">${[...V.model_saw].reverse().map((m) => `<span class="badge info">${esc(m.purpose)}</span><pre>${esc(m.text)}</pre>`).join("<br>")}
      <p class="faint tiny">Model: ${esc(V.model)}. Identifiers are tokens before anything is sent.</p></div>` : `<div class="empty">Exactly what the AI saw, after masking, appears here.</div>`;
  } else {
    const a = V.audit;
    html = `<div class="side-pad stack"><div class="row between"><b>Hash-chained audit log</b>${a.ok ? '<span class="badge ok">✓ intact</span>' : `<span class="badge deny">✕ tampered at #${esc(a.first_bad_seq)}</span>`}</div>
      <p class="small muted">${a.entries} entries. Each entry includes the hash of the one before, so any edit breaks the chain.</p>
      <div class="hashbox">head ${esc(a.head)}…</div>
      <div class="row"><button class="btn sm" data-act="verify-audit">Verify chain</button><button class="btn sm danger" data-act="tamper-audit">Tamper (demo)</button></div>
      <p class="faint tiny">Command line: python -m app.audit verify FILE</p></div>`;
  }
  $("#side").innerHTML = html;
}

/* ---------- after render: async bits ---------- */
function after() {
  const el = $(".big-amount[data-count]");
  if (el && !el.dataset.done) countUp(el);
  if (view === "route") whatif();
  if (view === "sign" && V.plan && $("#hash-check")) {
    planHashHere(V.plan).then((h) => {
      const ok = h === V.plan_hash_now && h === V.plan.plan_hash;
      $("#hash-check").innerHTML = ok ? `<span class="badge ok">✓ Matches</span> <span class="muted">Your device computed the same hash from the plan it shows you.</span>`
        : `<span class="badge deny">✕ Mismatch</span> <span class="muted">The plan shown does not hash to what the agent claims. Do not sign.</span>`;
    }).catch(() => { $("#hash-check").textContent = "This browser cannot compute SHA-256."; });
  }
  const log = $("#chatlog");
  if (log) log.scrollTop = log.scrollHeight;
  const ans = $("#answer-in");
  if (ans) ans.focus({ preventScroll: true });
}
function countUp(el) {
  el.dataset.done = "1";
  const to = Number(el.dataset.count), t0 = performance.now(), dur = 700;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = inr(to * e);
    if (k < 1) requestAnimationFrame(step); else el.textContent = inr(to);
  };
  requestAnimationFrame(step);
}

/* ---------- actions ---------- */
async function pinOk() {
  if (pin.length < 4) return;
  const value = pin;
  pin = "";
  if (!deviceRegistered()) {
    try { const r = await setUpDevice(value); toast(r.reason); } catch (e) { toast(e.message, true); }
    return render();
  }
  try {
    const approval = await signApproval(V.plan);
    const r = await act("approve", { pin: value, approval });
    if (r && r.result.ok) toast("Signed. The agent can't change this plan now.");
  } catch (e) { toast("Signing failed: " + e.message, true); render(); }
}

async function pay() {
  const steps = [];
  const r = await api("POST", `/api/session/${V.id}/pay`, {}).catch((e) => ({ error: e.message }));
  if (r.error) return toast(r.error, true);
  V = r.view;
  const res = r.result;
  if (res.duplicate) { toast("Already paid: the second click did nothing."); return render(); }
  const failAt = { circuit_breaker: 0, emergency_stop: 0, over_cap: 0, unverified_payee: 0, no_approval: 1, plan_changed: 1, bad_signature: 1, pin_required: 1, role: 1, bank: 2, lrs_cap: 0 }[res.code];
  const all = [["Policy gate", "Tier T3 · not frozen · emergency stop off · within the per-payment cap"],
    ["Parent signature", "Registered device key signed exactly this plan hash"],
    ["Bank checks the university", "Certificate from the trust root · bank account matches"],
    ["Ledger updated", res.ok ? `Transaction ${res.txn.txn_id}` : ""]];
  for (let i = 0; i < all.length; i++) {
    const bad = !res.ok && failAt === i;
    steps.push({ t: all[i][0], d: bad ? res.reason : all[i][1], ok: !bad });
    if (bad) break;
  }
  payProgress = steps;
  render();
  await sleep(380 * steps.length + 900);
  payProgress = null;
  if (res.ok) { go("receipt", false); toast("Paid in the sandbox bank."); } else toast(res.reason, true);
  render();
}

async function runLab(id) {
  labResults[id] = "running";
  render();
  try { labResults[id] = (await api("POST", `/api/lab/${id}`)).result; } catch (e) { labResults[id] = { stopped: false, defence: "error", actual: e.message }; }
  render();
}

/* ---------- settings ---------- */
function renderSettings() {
  const p = V.policy;
  $("#settings-body").innerHTML = `
    <div class="setting"><label for="s-pin"><b>Parent PIN</b></label><input id="s-pin" type="password" inputmode="numeric" maxlength="6" placeholder="PIN" autocomplete="off"></div>
    <div class="setting"><b>Parent signing devices</b>
      <span class="muted small">${p.parent_keys.length ? p.parent_keys.map((k) => `<span class="mono">${esc(k)}</span>${device && device.keyId === k ? " (this browser)" : ""}`).join("<br>") : "None registered yet."}</span>
      <div class="row"><button class="btn sm" data-set="device">${device ? (deviceRegistered() ? "Re-register this browser" : "Register this browser") : "Create key in this browser"}</button>
        ${device ? '<button class="btn sm danger" data-set="forget">Forget this browser\'s key</button>' : ""}</div></div>
    <div class="setting"><b>Emergency stop</b><span class="muted small">Denies every money action at once.</span>
      <div class="row"><span class="badge ${p.emergency_stop ? "deny" : "ok"}">${p.emergency_stop ? "ON" : "off"}</span>
        <button class="btn sm ${p.emergency_stop ? "" : "danger"}" data-set="stop">${p.emergency_stop ? "Turn off" : "Turn on"}</button></div></div>
    <div class="setting"><b>Per-payment cap</b><div class="row"><span>USD</span><input id="s-cap" type="text" value="${esc(p.per_payment_cap_usd)}" style="width:120px">
      <button class="btn sm" data-set="cap">Save</button></div></div>
    <div class="setting"><b>Circuit breaker</b><span class="muted small">Freezes the agent after ${p.breaker_threshold} denied money attempts in a row.</span>
      <div class="row"><span class="badge ${p.frozen ? "deny" : "ok"}">${p.frozen ? "FROZEN" : "normal"}</span><span class="muted small">${p.denied_in_a_row} in a row</span>
        <button class="btn sm" data-set="reset" ${p.frozen || p.denied_in_a_row ? "" : "disabled"}>Reset</button></div></div>`;
}
async function changeSetting(kind) {
  const pinValue = $("#s-pin").value;
  try {
    if (kind === "device") { const r = await setUpDevice(pinValue); toast(r.reason); }
    else if (kind === "forget") { await idb.del("parent"); device = null; toast("This browser's key was deleted. Register a new one to sign."); }
    else {
      const body = { pin: pinValue };
      if (kind === "stop") body.emergency_stop = !V.policy.emergency_stop;
      if (kind === "cap") body.per_payment_cap_usd = $("#s-cap").value.replace(/,/g, "");
      if (kind === "reset") body.reset_breaker = true;
      const r = await api("POST", "/api/settings", body);
      toast(r.result.reason, !r.result.allowed);
      await refresh();
    }
  } catch (e) { toast(e.message, true); }
  render();
  renderSettings();
}

/* ---------- events ---------- */
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button, [data-route], [data-go]");
  if (!t || !V) return;
  const d = t.dataset;
  if (d.go) return go(d.go);
  if (d.role) return act("role", { role: d.role }, { advance: false });
  if (d.side) { side = d.side; store.set("tp.side", side); return render(); }
  if (d.sample) return act("invoice", { sample: d.sample }, { advance: false });
  if (d.answer) return act("answer", { field: V.question.field, value: d.answer });
  if (d.route) return d.route !== V.chosen_quote_id && act("route", { quote_id: d.route }, { advance: false });
  if (d.lab) return runLab(d.lab);
  if (d.set) return changeSetting(d.set);
  if (d.wfFunding) { wf.funding = d.wfFunding; return whatif(); }
  if (d.wfPan) { wf.has_pan = d.wfPan === "1"; return whatif(); }
  if (d.pin) {
    if (d.pin === "back") pin = pin.slice(0, -1);
    else if (d.pin === "ok") return pinOk();
    else if (pin.length < 6) pin += d.pin;
    return render();
  }
  switch (d.act) {
    case "consent": return act("consent", { accept: true });
    case "paste": {
      const text = prompt("Paste the invoice text (including any signature block):");
      if (text) act("invoice", { text }, { advance: false });
      return;
    }
    case "refresh": return act("refresh", {}, { advance: false });
    case "pay": return pay();
    case "tamper_plan": return act("tamper_plan", {}, { advance: false });
    case "force-approve": return act("approve", { pin: "" }, { advance: false });
    case "print": return window.print();
    case "lab-all": for (const a of labList) await runLab(a.id); return;
    case "verify-audit": {
      const r = await api("GET", "/api/audit");
      return toast(r.ok ? `Audit chain intact: ${r.entries} entries.` : `Tampering detected at entry ${r.first_bad_seq}: ${r.reason}.`, !r.ok);
    }
    case "tamper-audit": {
      if (!confirm("This edits an old audit entry for the rest of this server run, to show tamper detection. Continue?")) return;
      const r = await api("POST", "/api/audit/tamper");
      toast(`Verify now says: ${r.result.reason} at entry ${r.result.first_bad_seq}.`, true);
      await refresh();
      return render();
    }
  }
  switch (t.id) {
    case "nav-lab": return go("lab");
    case "open-settings": $("#settings").hidden = false; renderSettings(); return $("#s-pin").focus();
    case "close-settings": $("#settings").hidden = true; return;
    case "delete-data": {
      if (!confirm("Delete this session's data (invoice, answers, masking vault) and start over?")) return;
      try { await api("POST", `/api/session/${V.id}/delete`); } catch { /* already gone */ }
      store.del("tp.session"); store.del("tp.view"); store.set("tp.seen", "0");
      V = null; labResults = {};
      toast("Your session data was deleted.");
      return start();
    }
  }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") { $("#settings").hidden = true; return; }
  const row = ev.target.closest && ev.target.closest("[data-route]");
  if (row && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); row.click(); return; }
  if (view === "sign" && !ev.target.matches("input, textarea") && $(".pinpad")) {
    if (/^[0-9]$/.test(ev.key) && pin.length < 6) { pin += ev.key; render(); }
    else if (ev.key === "Backspace") { pin = pin.slice(0, -1); render(); }
    else if (ev.key === "Enter") pinOk();
  }
});

document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "c1" || t.id === "c2") $("#consent-btn").disabled = !($("#c1").checked && $("#c2").checked);
  if (t.dataset.doc) act("document", { key: t.dataset.doc, have: t.checked }, { advance: false, quiet: true });
  if (t.id === "file" && t.files[0]) readFile(t.files[0]);
});
document.addEventListener("input", (ev) => {
  if (ev.target.id === "wf-prior") {
    wf.prior = Number(ev.target.value);
    $("#wf-prior-v").textContent = inr(wf.prior);
    clearTimeout(wfTimer);
    wfTimer = setTimeout(whatif, 160);
  }
});
document.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (ev.target.id === "answer") {
    const v = $("#answer-in").value.trim();
    if (v) act("answer", { field: V.question.field, value: v });
  }
  if (ev.target.id === "ask") {
    const v = $("#ask-in").value.trim();
    if (v) { await act("chat", { text: v }, { advance: false }); const a = $("#ask-in"); if (a) a.focus(); }
  }
});
function readFile(f) {
  if (f.size > 64 * 1024) return toast("That file is too large for an invoice.", true);
  const reader = new FileReader();
  reader.onload = () => act("invoice", { text: String(reader.result) }, { advance: false });
  reader.readAsText(f);
}
document.addEventListener("dragover", (ev) => { const d = ev.target.closest && ev.target.closest("#drop"); if (d) { ev.preventDefault(); d.classList.add("over"); } });
document.addEventListener("dragleave", (ev) => { const d = ev.target.closest && ev.target.closest("#drop"); if (d) d.classList.remove("over"); });
document.addEventListener("drop", (ev) => { const d = ev.target.closest && ev.target.closest("#drop"); if (d) { ev.preventDefault(); d.classList.remove("over"); if (ev.dataTransfer.files[0]) readFile(ev.dataTransfer.files[0]); } });
$("#settings").addEventListener("click", (ev) => { if (ev.target.id === "settings") $("#settings").hidden = true; });

start().catch((e) => toast("Could not reach the TuitionPilot server: " + e.message, true));
