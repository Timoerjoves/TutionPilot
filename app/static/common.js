"use strict";
/* Shared by the landing, sign-in and app pages. Plain JavaScript, no libraries.
   Device keys are made and kept in this browser (IndexedDB; the private halves are not extractable):
   an Ed25519 key that signs (sign-in challenges, payment approvals) and an X25519 key that unlocks vault files.
   The server only ever receives the public halves and signatures. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const info = (text) => `<button type="button" class="i-btn" data-tip="${esc(text)}" aria-label="${esc(text)}">i</button>`;

/* ---------- bytes and hashing ---------- */
const utf8 = (s) => new TextEncoder().encode(s);
function b64(bytes) {  // chunked: spreading a whole file into fromCharCode would overflow the stack
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function sha256hex(data) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", typeof data === "string" ? utf8(data) : data));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function canon(v) {  // same bytes as Python json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
}

/* ---------- server ---------- */
async function api(method, path, body) {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* ---------- device keys (one record per role, so one browser can demo both) ---------- */
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

const SIGN_IN_CONTEXT = "tuitionpilot-sign-in:";  // must match app/family.py

async function cryptoSupported() {
  try {
    await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign"]);
    await crypto.subtle.generateKey({ name: "X25519" }, false, ["deriveBits"]);
    return true;
  } catch { return false; }
}
async function loadDevice(role) {
  try { const d = await idb.get(role); return d && d.boxPrivate ? d : null; } catch { return null; }
}
async function makeDevice(role) {
  const sig = await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"]);
  const box = await crypto.subtle.generateKey({ name: "X25519" }, false, ["deriveBits"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", sig.publicKey));
  return { role, privateKey: sig.privateKey, publicKey: b64(raw), keyId: "ed25519:" + (await sha256hex(raw)).slice(0, 16),
    boxPrivate: box.privateKey, boxPublic: b64(new Uint8Array(await crypto.subtle.exportKey("raw", box.publicKey))) };
}
/* Enrol this browser for a role. Only the first parent device enrols with the PIN alone; every later device
   first asks for a code (requestEnrolment), a signed-in parent device signs that request, then this browser
   finishes with the PIN and the code. */
async function enrolDevice(role, pin, label, code) {
  const d = (await loadDevice(role)) || await makeDevice(role);
  const body = code ? { pin, code } : { pin, role, public_key: d.publicKey, box_key: d.boxPublic, label };
  const r = await api("POST", "/api/devices", body);
  if (!r.result.allowed) throw new Error(r.result.reason);
  await idb.put(role, d);
  return d;
}
async function requestEnrolment(role, label) {
  const d = (await loadDevice(role)) || await makeDevice(role);
  await idb.put(role, d);  // kept now: the finish step must use the same key the parent signed for
  return (await api("POST", "/api/devices/request", { role, public_key: d.publicKey, box_key: d.boxPublic, label })).code;
}
const ENROL_CONTEXT = "tuitionpilot-enrol-device:";  // must match app/family.py
async function signEnrolment(d, req) {  // a parent device approves exactly this role, keys, label and nonce
  const msg = canon({ role: req.role, public_key: req.public_key, box_key: req.box_key, label: req.label, nonce: req.nonce });
  return b64(new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, d.privateKey, utf8(ENROL_CONTEXT + msg))));
}
const showCode = (c) => c.slice(0, 4) + "-" + c.slice(4);
/* Passwordless sign-in: sign the server's one-time challenge. Returns the new session view. */
async function signInWith(d) {
  const { nonce } = await api("POST", "/api/auth/challenge", {});
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, d.privateKey, utf8(SIGN_IN_CONTEXT + nonce)));
  return (await api("POST", "/api/auth/sign_in", { nonce, key_id: d.keyId, signature: b64(sig) })).view;
}

/* ---------- info tips: hover or keyboard focus shows the detail, kept inside the viewport ---------- */
function tipFor(ev) {
  const tip = $("#tip");
  if (!tip) return;
  const el = ev.target.closest && ev.target.closest("[data-tip]");
  if (!el) { tip.hidden = true; return; }
  tip.textContent = el.dataset.tip;
  tip.hidden = false;
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
  tip.style.top = (r.bottom + 8 + h > innerHeight ? r.top - h - 8 : r.bottom + 8) + "px";
}
document.addEventListener("mouseover", tipFor);
document.addEventListener("focusin", tipFor);
document.addEventListener("scroll", () => { const t = $("#tip"); if (t) t.hidden = true; }, true);
document.addEventListener("click", (ev) => { if (ev.target.closest(".i-btn")) ev.preventDefault(); }, true);
