"""The web server: static files, the JSON API, and a full payment through HTTP."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from agent.agent import CONFIG, Agent
from app.server import make_handler
from scenarios import fixtures as fx


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

    def test_full_payment_over_http(self):
        code, r = self.post("/api/session", {"role": "parent"})
        sid = r["view"]["id"]
        self.assertEqual(self.post(f"/api/session/{sid}/invoice", {"sample": "valid_us"})[0], 400)  # consent first
        self.post(f"/api/session/{sid}/consent", {"accept": True})
        self.post(f"/api/session/{sid}/invoice", {"sample": "valid_us"})
        for field, value in [("remitter_name", "Ravi Parent"), ("pan", "No PAN"), ("relationship", "Father"),
                             ("funding", "Own money"), ("prior_inr", "0")]:
            code, r = self.post(f"/api/session/{sid}/answer", {"field": field, "value": value})
        plan = r["view"]["plan"]
        code, r = self.post(f"/api/session/{sid}/approve", {"pin": CONFIG["demo_pin"], "approval": fx.parent_approval(plan)})
        self.assertEqual(r["result"]["code"], "no_parent_key")  # no device enrolled yet
        code, r = self.post("/api/parent_key", {"pin": CONFIG["demo_pin"], "public_key": fx.PARENT_PUBLIC})
        self.assertTrue(r["result"]["allowed"])
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
