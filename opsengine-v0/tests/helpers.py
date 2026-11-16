import json
import os

os.environ["OPSENGINE_OFFLINE"] = "1"  # tests never call the Claude API
os.environ["USE_MOCK_AI"] = "false"  # tests choose mock mode explicitly; a local .env must not change results

from opsengine.knowledge import ROOT

SAMPLE = ROOT / "data" / "sample" / "liffey_interiors"
PHOTOS = ROOT / "tests" / "fixtures" / "photos"
MOCK_REPLIES = json.loads((ROOT / "data" / "sample" / "mock_ai" / "vision_replies.json").read_text())["replies"]
REPLIES = {v["sample"]: v["text"] for v in MOCK_REPLIES.values()}


def fake_claude(reply_text, calls=None, stop_reason="end_turn"):
    """A stand-in for llm.call that returns a canned Messages API response and records requests."""
    def call(body, betas=None):
        if calls is not None:
            calls.append({"body": body, "betas": betas})
        return {"model": body["model"], "stop_reason": stop_reason,
                "content": [{"type": "text", "text": reply_text}]}
    return call


def fake_claude_for(name, calls=None):
    return fake_claude(REPLIES[name], calls)


# ---------------- portal test client: signs in like a browser ----------------
import http.cookiejar
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

DEMO = {"customer": "grainne@bremore-groundworks.example.ie", "liffey": "ciara@liffey-interiors.example.ie",
        "ops": "ops@opsengine.example.ie", "reviewer": "reviewer@opsengine.example.ie"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def start_portal(state_dir, demo=True, customers=None):
    from opsengine import web
    web.Handler.portal = web.Portal(customers or web.SAMPLES, state_dir, demo=demo)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", web.Handler.portal, httpd


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.follow = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.nofollow = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)
        self.csrf = ""

    def get(self, path):
        with self.follow.open(self.base + path) as r:
            body = r.read().decode()
        m = re.search(r'name="csrf" value="([^"]*)"', body)
        if m:
            self.csrf = m.group(1)
        return body

    def post(self, path, data, csrf=True):
        """POST without following the redirect. Returns (status, location or body)."""
        data = dict(data)
        if csrf:
            data.setdefault("csrf", self.csrf)
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode(), method="POST",
                                     headers={"Referer": self.base + path})
        try:
            with self.nofollow.open(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location")
            return e.code, urllib.parse.unquote(loc) if loc else e.read().decode()

    def login(self, email, password="sample-demo-only"):
        status, loc = self.post("/login", {"email": email, "password": password}, csrf=False)
        if status == 303 and loc == "/":
            self.get("/")
        return status, loc

    def flash(self, location):
        return location.split("flash=", 1)[-1] if "flash=" in location else location
