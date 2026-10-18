"""TuitionPilot web app: a small JSON API around the agent plus the single-page UI in app/static/.

Run from the repo root:   python -m app.server            then open http://127.0.0.1:8000
Standard library only. Listens on 127.0.0.1 (this computer only). Each run writes its sandbox ledger,
audit log and what-the-model-saw log to data/evidence/runs/<timestamp>/.
"""
import argparse
import json
import mimetypes
import os
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.agent import CONFIG, ROOT, Agent
from app import lab

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024
MAX_VAULT_BODY = 4 * 1024 * 1024  # a sealed file or PDF invoice of up to 2 MB, base64-encoded
PAGES = {"/": "landing.html", "": "landing.html", "/signin": "signin.html", "/app": "index.html"}
LOCK = threading.Lock()
SESSION_ACTIONS = {
    "consent": lambda a, sid, b: a.consent(sid, b.get("accept")),
    "invoice": lambda a, sid, b: a.upload_invoice(sid, text=b.get("text"), sample=b.get("sample"), pdf=b.get("pdf")),
    "answer": lambda a, sid, b: a.answer(sid, b.get("field"), b.get("value")),
    "chat": lambda a, sid, b: a.chat(sid, b.get("text")),
    "route": lambda a, sid, b: a.choose_route(sid, b.get("quote_id")),
    "refresh": lambda a, sid, b: a.refresh_quotes(sid),
    "role": lambda a, sid, b: a.set_role(sid, b.get("role")),
    "vault_put": lambda a, sid, b: {"ok": True, "doc": a.vault_put(sid, b.get("doc"))},
    "document": lambda a, sid, b: a.set_document(sid, b.get("key"), b.get("have")),
    "approve": lambda a, sid, b: a.approve(sid, b.get("pin"), b.get("approval")),
    "pay": lambda a, sid, b: a.pay(sid),
    "tamper_plan": lambda a, sid, b: a.tamper_plan(sid),
}
READ_ACTIONS = {  # compute only; the session is not changed
    "whatif": lambda a, sid, b: a.whatif(sid, b.get("prior_inr"), b.get("funding"), b.get("has_pan")),
    "vault_list": lambda a, sid, b: a.vault_list(sid),
    "vault_get": lambda a, sid, b: a.vault_get(sid, b.get("doc_id")),
    "enrol_request": lambda a, sid, b: a.family.enrolment_request(b.get("code")),
    "enrol_approve": lambda a, sid, b: a.approve_device(sid, b.get("code"), b.get("signature")) or {"ok": True},
}


def make_handler(agent):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TuitionPilot/1.0"

        def log_message(self, fmt, *args):  # keep the console quiet; the audit log is the record
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > (MAX_VAULT_BODY if self.path.endswith(("/vault_put", "/invoice")) else MAX_BODY):
                raise ValueError("request too large")
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _cross_site(self, post=False):
            """Why a request looks cross-site (CSRF, DNS rebinding), or None. Browsers can't send JSON cross-origin
            without a preflight we never answer, so POSTs must be JSON; Host and Origin must be this server."""
            port = self.server.server_address[1]
            ours = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if (self.headers.get("Host") or "").lower() not in ours:
                return "unexpected Host header"
            origin = self.headers.get("Origin")
            if origin and origin.lower() not in {f"http://{h}" for h in ours}:
                return "cross-site request refused"
            if post and not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                return "requests must be JSON"
            return None

        def do_GET(self):
            path = self.path.split("?")[0]
            why = self._cross_site()
            if why:
                return self._send(403, {"error": why})
            try:
                if path.startswith("/api/"):
                    with LOCK:
                        return self._send(200, self._api_get(path))
                name = PAGES.get(path) or path.lstrip("/")
                f = (STATIC / name).resolve()
                if STATIC not in f.parents or not f.is_file():
                    return self._send(404, {"error": "not found"})
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype)
            except KeyError as e:
                return self._send(404, {"error": str(e).strip("'")})
            except ValueError as e:
                return self._send(400, {"error": str(e)})

        def _api_get(self, path):
            m = re.fullmatch(r"/api/session/([0-9a-f]{12})", path)
            if m:
                return {"view": agent.view(m.group(1))}
            m = re.fullmatch(r"/api/sample/([a-z_]+)", path)
            if m:
                f = ROOT / "data" / "invoices" / f"{m.group(1)}.txt"
                if not f.exists():
                    raise KeyError("unknown sample")
                return {"text": f.read_text(encoding="utf-8")}
            if path == "/api/audit":
                return agent.audit.verify()
            if path == "/api/lab":
                return {"attacks": lab.listing()}
            if path == "/api/devices":  # public keys only: needed to share a vault file with a device
                return {"devices": agent.family.listing(), "bootstrap": not agent.policy.parent_keys}
            if path == "/api/trust":
                return {"root": agent.trust.root, "revoked": sorted(agent.trust.revoked)}
            raise KeyError("not found")

        def do_POST(self):
            path = self.path.split("?")[0]
            why = self._cross_site(post=True)
            if why:
                return self._send(403, {"error": why})
            try:
                body = self._body()
                with LOCK:
                    if path == "/api/session":  # a guest session can only look; acting as the parent needs sign-in
                        s = agent.new_session("student")
                        return self._send(200, {"view": agent.view(s["id"])})
                    if path == "/api/auth/challenge":
                        return self._send(200, {"nonce": agent.family.challenge()})
                    if path == "/api/auth/sign_in":
                        s = agent.sign_in(body.get("nonce"), body.get("key_id"), body.get("signature"))
                        return self._send(200, {"view": agent.view(s["id"])})
                    if path == "/api/devices/request":  # a new device asks; a signed-in parent device approves
                        code = agent.request_device(body.get("role"), body.get("public_key"), body.get("box_key"),
                                                    body.get("label", "browser"))
                        return self._send(200, {"code": code})
                    if path == "/api/devices":
                        d = agent.register_device(body.get("pin"), body.get("role"), body.get("public_key"),
                                                  body.get("box_key"), body.get("label", "browser"), body.get("code"))
                        return self._send(200, {"result": d.to_dict(), "devices": agent.family.listing()})
                    if path == "/api/settings":
                        d = agent.settings(body.get("pin"), per_payment_cap_usd=body.get("per_payment_cap_usd"),
                                           emergency_stop=body.get("emergency_stop"),
                                           reset_breaker=bool(body.get("reset_breaker")))
                        return self._send(200, {"result": d.to_dict(), "policy": agent.policy.status()})
                    m = re.fullmatch(r"/api/lab/([A-Z][0-9])", path)
                    if m:
                        return self._send(200, {"result": lab.run(m.group(1))})
                    if path == "/api/audit/tamper":
                        return self._send(200, {"result": agent.tamper_audit_demo()})
                    m = re.fullmatch(r"/api/session/([0-9a-f]{12})/([a-z_]+)", path)
                    if not m:
                        return self._send(404, {"error": "not found"})
                    sid, action = m.groups()
                    if action == "delete":
                        return self._send(200, {"result": agent.delete_data(sid)})
                    if action in READ_ACTIONS:
                        return self._send(200, {"result": READ_ACTIONS[action](agent, sid, body)})
                    if action not in SESSION_ACTIONS:
                        return self._send(404, {"error": "unknown action"})
                    result = SESSION_ACTIONS[action](agent, sid, body)
                    result = result if isinstance(result, dict) and "ok" in result else {"ok": True}
                    return self._send(200, {"result": result, "view": agent.view(sid)})
            except KeyError as e:
                return self._send(404, {"error": str(e).strip("'")})
            except PermissionError as e:
                return self._send(403, {"error": str(e)})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except json.JSONDecodeError:
                return self._send(400, {"error": "body must be JSON"})

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(description="Run the TuitionPilot demo app (sandbox only).")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", CONFIG["port"])))
    p.add_argument("--evidence", default=None, help="folder for this run's logs (default data/evidence/runs/<time>)")
    args = p.parse_args(argv)
    evidence = Path(args.evidence) if args.evidence else ROOT / "data" / "evidence" / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    agent = Agent(evidence_dir=evidence)
    httpd = ThreadingHTTPServer((CONFIG["host"], args.port), make_handler(agent))
    print(f"TuitionPilot running at http://{CONFIG['host']}:{args.port}  (sandbox only, synthetic data)")
    print(f"Evidence for this run: {evidence}")
    print("Stop with Ctrl+C.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
