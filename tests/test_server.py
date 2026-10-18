"""The web server: static files, the JSON API, and a full payment through HTTP."""
import base64
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

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
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
        for path, marker in [("/", b"Sign in"), ("/signin", b"signin.js"), ("/app", b"app.js")]:
            code, _, data = self.call("GET", path)
            self.assertEqual(code, 200, path)
            self.assertIn(marker, data, path)

    def test_full_payment_over_http(self):
        code, r = self.post("/api/session", {"role": "parent"})  # a guest asking to be the parent gets a student view
        self.assertEqual(r["view"]["role"], "student")
        self.assertEqual(self.post(f"/api/session/{r['view']['id']}/role", {"role": "parent"})[0], 403)
        box = base64.b64encode(os.urandom(32)).decode()
        code, r = self.post("/api/devices", {"pin": "0000", "role": "parent", "public_key": fx.PARENT_PUBLIC, "box_key": box})
        self.assertFalse(r["result"]["allowed"])
        code, r = self.post("/api/devices", {"pin": CONFIG["demo_pin"], "role": "parent", "public_key": fx.PARENT_PUBLIC, "box_key": box})
        self.assertTrue(r["result"]["allowed"])
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
        for field, value in [("remitter_name", "Ravi Parent"), ("pan", "No PAN"), ("relationship", "Father"),
                             ("funding", "Own money"), ("prior_inr", "0")]:
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
        self.assertEqual(self.call("GET", f"/api/session/{sid}")[0], 404)

    def test_bad_requests(self):
        self.assertEqual(self.post("/api/session/000000000000/pay")[0], 404)
        code, _, _ = self.call("GET", "/api/sample/../../secrets")
        self.assertEqual(code, 404)
        code, r = self.post("/api/settings", {"pin": "0000", "emergency_stop": True})
        self.assertFalse(r["result"]["allowed"])


if __name__ == "__main__":
    unittest.main()
