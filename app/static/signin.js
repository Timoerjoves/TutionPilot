"use strict";
/* Sign-in page: pick parent or student, then either sign in with this browser's enrolled key,
   or enrol this browser first. The first parent device needs only the PIN; every later device shows a code
   that a signed-in parent device approves, then finishes with the PIN. */

let role = store.get("tp.role", "parent") === "student" ? "student" : "parent";
let device = null, enrolled = false, supported = true, busy = false, bootstrap = false;
const KEY_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M14 9l2 2"/></svg>`;
const codeKey = () => "tp.enrol." + role;  // the pending enrolment code survives a reload

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("bad", bad);
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 4500);
}

async function load() {
  supported = await cryptoSupported();
  device = supported ? await loadDevice(role) : null;
  const r = supported ? await api("GET", "/api/devices") : { devices: [] };
  const devices = r.devices;
  bootstrap = !!r.bootstrap;
  if (bootstrap) ["parent", "student"].forEach((x) => store.del("tp.enrol." + x));  // codes from an earlier server run are void
  enrolled = !!device && devices.some((d) => d.key_id === device.keyId);
  render();
}

function render() {
  const tabs = `<div class="seg auth-tabs" role="tablist" aria-label="Sign in as">
      ${["parent", "student"].map((r) => `<button class="seg-btn ${r === role ? "on" : ""}" role="tab" aria-selected="${r === role}" data-pick="${r}">${r === "parent" ? "Parent" : "Student"}</button>`).join("")}</div>`;
  let body;
  if (!supported) {
    body = `<div class="banner warn"><b>This browser can't make device keys.</b><span class="body">Use a current Chrome, Edge, Firefox or Safari.${info("Sign-in needs Ed25519 and X25519 in the browser's built-in Web Crypto. Nothing is installed.")}</span></div>`;
  } else if (enrolled) {
    body = `<div class="key-card"><span class="key-ico" aria-hidden="true">${KEY_ICON}</span><div><b>${role === "parent" ? "Parent" : "Student"} key on this browser</b>
        <div class="mono faint">${esc(device.keyId)}</div></div></div>
      <button class="btn primary big wide" data-do="signin" ${busy ? "disabled" : ""}>${busy ? "Signing…" : "Sign in with this device"}</button>
      <p class="faint tiny center">Signs a one-time challenge${info("The server sends a random challenge that works once and expires in two minutes. Your browser signs it with its private key; the server checks the signature with the public key it stored when this device was enrolled.")}</p>`;
  } else if (bootstrap && role === "parent") {
    body = `<p class="muted small">Set up this browser as the first parent device.
        ${info("This browser makes two key pairs: one to sign, one to unlock vault files. Only the public halves are sent. Parent devices can sign payment plans. Only this first device is set up with the PIN alone; later devices also need this one's approval.")}</p>
      <form id="enrol" class="stack" autocomplete="off">
        <label class="field-in"><span>Device name</span><input id="label" maxlength="40" value="Parent's browser"></label>
        <label class="field-in"><span>Parent PIN</span><input id="pin" type="password" inputmode="numeric" maxlength="6" placeholder="••••" required></label>
        <button class="btn primary big wide" ${busy ? "disabled" : ""}>${busy ? "Setting up…" : "Set up & sign in"}</button>
      </form>
      <p class="faint tiny center">Demo PIN is in the README</p>`;
  } else if (bootstrap) {
    body = `<div class="banner warn"><b>No parent device yet.</b><span class="body">Set up a parent device first, then it can approve this one.</span></div>`;
  } else if (!store.get(codeKey())) {
    body = `<p class="muted small">New devices need approval from a parent device that is already signed in.
        ${info(role === "parent" ? "Parent devices can sign payment plans, so a new one needs the PIN and a signature from an existing parent device." : "Student devices can sign in, follow the payment and share files with parents. They can never approve a payment or change limits.")}</p>
      <form id="request" class="stack" autocomplete="off">
        <label class="field-in"><span>Device name</span><input id="label" maxlength="40" value="${role === "parent" ? "Parent's browser" : "Student's laptop"}"></label>
        <button class="btn primary big wide" ${busy ? "disabled" : ""}>${busy ? "Asking…" : "Ask a parent to approve"}</button>
      </form>`;
  } else {
    body = `<p class="muted small">On a signed-in parent device open <b>Settings → Approve a new device</b> and enter this code (valid 10 minutes):</p>
      <div class="key-card"><span class="key-ico" aria-hidden="true">${KEY_ICON}</span><div><b class="mono" style="font-size:22px">${esc(showCode(store.get(codeKey())))}</b>
        <div class="mono faint">${esc(device ? device.keyId : "")}</div></div></div>
      <form id="enrol" class="stack" autocomplete="off">
        <label class="field-in"><span>Parent PIN</span><input id="pin" type="password" inputmode="numeric" maxlength="6" placeholder="••••" required></label>
        <button class="btn primary big wide" ${busy ? "disabled" : ""}>${busy ? "Finishing…" : "Approved: finish & sign in"}</button>
      </form>
      <p class="faint tiny center"><button type="button" class="link" data-do="restart">Start over with a new code</button></p>`;
  }
  $("#auth").innerHTML = `<h2 class="auth-title"><b>Sign in</b> to TuitionPilot</h2>${tabs}<div class="stack" style="margin-top:20px">${body}</div>`;
}

async function signIn() {
  busy = true; render();
  try {
    const view = await signInWith(device);
    store.set("tp.session", view.id);
    store.set("tp.view", "welcome");
    location.href = "/app";
  } catch (e) { toast(e.message, true); busy = false; render(); }
}

document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-pick], [data-do]");
  if (!t || busy) return;
  if (t.dataset.pick && t.dataset.pick !== role) { role = t.dataset.pick; store.set("tp.role", role); return load(); }
  if (t.dataset.do === "signin") signIn();
  if (t.dataset.do === "restart") { store.del(codeKey()); render(); }
});
document.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (busy) return;
  busy = true;
  const pin = $("#pin") && $("#pin").value, label = $("#label") && $("#label").value.trim();
  const code = ev.target.id === "enrol" && !bootstrap ? store.get(codeKey()) : null;  // the first parent device needs no code
  render();
  try {
    if (ev.target.id === "request") {
      store.set(codeKey(), await requestEnrolment(role, label));
      device = await loadDevice(role);
      busy = false;
      return render();
    }
    device = await enrolDevice(role, pin, label, code);
    store.del(codeKey());
    enrolled = true;
    busy = false;
    await signIn();
  } catch (e) { toast(e.message, true); busy = false; render(); }
});

load().catch((e) => { $("#auth").innerHTML = `<div class="banner deny"><b>Server unreachable.</b><span class="body">${esc(e.message)}</span></div>`; });
