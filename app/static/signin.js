"use strict";
/* Sign-in page: pick parent or student, then either sign in with this browser's enrolled key,
   or enrol this browser first (needs the parent's PIN). */

let role = store.get("tp.role", "parent") === "student" ? "student" : "parent";
let device = null, enrolled = false, supported = true, busy = false;

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
  const devices = supported ? (await api("GET", "/api/devices")).devices : [];
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
    body = `<div class="key-card"><span class="key-ico" aria-hidden="true">🔑</span><div><b>${role === "parent" ? "Parent" : "Student"} key on this browser</b>
        <div class="mono faint">${esc(device.keyId)}</div></div></div>
      <button class="btn primary big wide" data-do="signin" ${busy ? "disabled" : ""}>${busy ? "Signing…" : "Sign in with this device"}</button>
      <p class="faint tiny center">Signs a one-time challenge${info("The server sends a random challenge that works once and expires in two minutes. Your browser signs it with its private key; the server checks the signature with the public key it stored when this device was enrolled.")}</p>`;
  } else {
    body = `<p class="muted small">${role === "parent" ? "Set up this browser as a parent device." : "Ask a parent to enter their PIN to approve this device."}
        ${info(role === "parent" ? "This browser makes two key pairs: one to sign, one to unlock vault files. Only the public halves are sent. Parent devices can sign payment plans." : "Student devices can sign in, follow the payment and share files with parents. They can never approve a payment or change limits.")}</p>
      <form id="enrol" class="stack" autocomplete="off">
        <label class="field-in"><span>Device name</span><input id="label" maxlength="40" value="${role === "parent" ? "Parent's browser" : "Student's laptop"}"></label>
        <label class="field-in"><span>Parent PIN</span><input id="pin" type="password" inputmode="numeric" maxlength="6" placeholder="••••" required></label>
        <button class="btn primary big wide" ${busy ? "disabled" : ""}>${busy ? "Setting up…" : "Set up & sign in"}</button>
      </form>
      <p class="faint tiny center">Demo PIN is in the README</p>`;
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
});
document.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (busy) return;
  busy = true;
  const pin = $("#pin").value, label = $("#label").value.trim();
  render();
  try {
    device = await enrolDevice(role, pin, label);
    enrolled = true;
    busy = false;
    await signIn();
  } catch (e) { toast(e.message, true); busy = false; render(); }
});

load().catch((e) => { $("#auth").innerHTML = `<div class="banner deny"><b>Server unreachable.</b><span class="body">${esc(e.message)}</span></div>`; });
