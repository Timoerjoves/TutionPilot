"""The web server: static files, the JSON API, and a full payment through HTTP."""
import base64
import http.cookiejar
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from agent.agent import CONFIG, Agent
from app.family import SIGN_IN_CONTEXT
from app.server import make_handler
from scenarios import fixtures as fx
from security.pki import sign_bytes


class TestServer(unittest.TestCase):
    def setUp(self):
        cls = self
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Agent()))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req) as r:  # keeps the session cookie, like a browser
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers, e.read()

    def post(self, path, body=None):
        code, _, data = self.call("POST", path, body or {})
        return code, json.loads(data)

    def test_static_files_and_security_headers(self):
        code, headers, data = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"TuitionPilot", data)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.call("GET", "/app.js")[0], 200)
        self.assertEqual(self.call("GET", "/../agent/agent.py")[0], 404)

    def test_pages(self):
        for path, marker in [("/", b"Sign in"), ("/signin", b"signin.js"), ("/app", b"app.js"), ("/assistant", b"app.js")]:
            code, _, data = self.call("GET", path)
            self.assertEqual(code, 200, path)
            self.assertIn(marker, data, path)
        code, headers, _ = self.call("GET", "/fonts/Manrope.woff2")
        self.assertEqual((code, headers["Content-Type"]), (200, "font/woff2"))

    def test_full_payment_over_http(self):
        code, r = self.post("/api/session", {"role": "parent"})  # a guest asking to be the parent gets a student view
        self.assertEqual(r["view"]["role"], "student")
        self.assertEqual(self.post(f"/api/session/{r['view']['id']}/role", {"role": "parent"})[0], 403)
        box = base64.b64encode(os.urandom(32)).decode()
        code, r = self.post("/api/devices", {"pin": "0000", "role": "parent", "public_key": fx.PARENT_PUBLIC, "box_key": box})
        self.assertFalse(r["result"]["allowed"])
        code, r = self.post("/api/devices", {"pin": CONFIG["demo_pin"], "role": "parent", "public_key": fx.PARENT_PUBLIC, "box_key": box})
        self.assertTrue(r["result"]["allowed"])
        self.assertEqual(self.post("/api/parent_key", {"pin": CONFIG["demo_pin"], "public_key": fx.PARENT_PUBLIC})[0], 404)
        other = base64.b64encode(os.urandom(32)).decode()  # a second device: PIN alone is no longer enough
        code, r2 = self.post("/api/devices", {"pin": CONFIG["demo_pin"], "role": "parent", "public_key": other, "box_key": box})
        self.assertEqual(r2["result"]["code"], "stale_request")
        self.post("/api/settings", {"pin": CONFIG["demo_pin"], "reset_breaker": True})  # those refusals count as denials
        kid = r["devices"][0]["key_id"]
        nonce = self.post("/api/auth/challenge")[1]["nonce"]
        sig = sign_bytes(fx.PARENT_SECRET, SIGN_IN_CONTEXT + nonce.encode())
        code, r = self.post("/api/auth/sign_in", {"nonce": nonce, "key_id": kid, "signature": sig})
        self.assertEqual((code, r["view"]["role"], r["view"]["device"]), (200, "parent", kid))
        self.assertEqual(self.post("/api/auth/sign_in", {"nonce": nonce, "key_id": kid, "signature": sig})[0], 403)  # replay
        sid = r["view"]["id"]
        self.assertEqual(self.post(f"/api/session/{sid}/invoice", {"sample": "valid_us"})[0], 403)  # consent first
        self.post(f"/api/session/{sid}/consent", {"accept": True})
        self.post(f"/api/session/{sid}/invoice", {"sample": "valid_us"})
        for field, value in [("remitter_name", "Ravi Parent"), ("pan", fx.SYN_PAN), ("relationship", "Father"),
                             ("funding", "Own money"), ("source_of_funds", "Savings"), ("prior_inr", "0")]:
            code, r = self.post(f"/api/session/{sid}/answer", {"field": field, "value": value})
        plan = r["view"]["plan"]
        code, r = self.post(f"/api/session/{sid}/approve", {"pin": "0000", "approval": fx.parent_approval(plan)})
        self.assertFalse(r["result"]["ok"])
        code, r = self.post(f"/api/session/{sid}/approve", {"pin": CONFIG["demo_pin"], "approval": fx.parent_approval(plan)})
        self.assertTrue(r["result"]["ok"], r["result"])
        code, r = self.post(f"/api/session/{sid}/pay")
        self.assertTrue(r["result"]["ok"], r["result"])
        self.assertIsNotNone(r["view"]["receipt"])
        self.assertTrue(r["view"]["audit"]["ok"])
        code, r = self.post(f"/api/session/{sid}/delete")
        self.assertEqual(self.call("GET", f"/api/session/{sid}")[0], 401)  # deleted, and its cookie is void

    def test_cross_site_requests_refused(self):  # risk R20
        def raw(method, headers, body=b"{}"):
            req = urllib.request.Request(self.base + "/api/session", method=method, data=body if method == "POST" else None,
                                         headers=headers)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                with e:
                    return e.code
        json_ct = {"Content-Type": "application/json"}
        self.assertEqual(raw("POST", {**json_ct, "Origin": "https://evil.example"}), 403)
        self.assertEqual(raw("POST", {"Content-Type": "text/plain"}), 403)  # a form-style "simple" request
        self.assertEqual(raw("POST", {**json_ct, "Host": "attacker.example:80"}), 403)  # DNS rebinding
        self.assertEqual(raw("GET", {"Host": "attacker.example:80"}), 403)
        self.assertEqual(raw("POST", {**json_ct, "Origin": self.base}), 200)
        self.assertEqual(raw("POST", json_ct), 200)  # no Origin: a script or curl on this computer

    def test_session_needs_its_own_cookie(self):  # risk R25
        code, headers, data = self.call("POST", "/api/session", {})
        sid = json.loads(data)["view"]["id"]
        cookie = headers["Set-Cookie"]
        for flag in ("tp_session=", "HttpOnly", "SameSite=Strict", "Path=/api"):
            self.assertIn(flag, cookie)
        self.assertEqual(self.call("GET", f"/api/session/{sid}")[0], 200)
        other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def as_other(method, path):
            req = urllib.request.Request(self.base + path, method=method, data=b"{}" if method == "POST" else None,
                                         headers={"Content-Type": "application/json"})
            try:
                with other.open(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                with e:
                    return e.code, json.loads(e.read())
        self.assertEqual(as_other("GET", f"/api/session/{sid}")[0], 401)  # the session id alone is not enough
        self.assertEqual(as_other("POST", f"/api/session/{sid}/consent")[0], 401)
        own = as_other("POST", "/api/session")[1]["view"]["id"]  # its own session works with its own cookie
        self.assertEqual(as_other("GET", f"/api/session/{own}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/session/{own}")[0], 401)  # but not with the first browser's cookie

    def test_idle_session_expires_and_is_deleted(self):
        agent = Agent()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(agent, idle_seconds=-1))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            self.base = f"http://127.0.0.1:{httpd.server_address[1]}"
            sid = self.post("/api/session")[1]["view"]["id"]
            code, r = self.post(f"/api/session/{sid}/consent", {"accept": True})
            self.assertEqual(code, 401)
            self.assertIn("expired", r["error"])
            self.assertNotIn(sid, agent.sessions)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_bad_requests(self):
        self.assertEqual(self.post("/api/session/000000000000/pay")[0], 401)  # no session cookie: refused first
        code, _, _ = self.call("GET", "/api/sample/../../secrets")
        self.assertEqual(code, 404)
        code, r = self.post("/api/settings", {"pin": "0000", "emergency_stop": True})
        self.assertFalse(r["result"]["allowed"])


if __name__ == "__main__":
    unittest.main()
