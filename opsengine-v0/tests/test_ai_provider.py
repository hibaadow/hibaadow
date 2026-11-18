"""Switchable AI provider: Claude API, Vertex AI (EU, service account) or mock; human fallback; no names in AI logs.

All offline: the HTTP transport and Google's token endpoint are fakes. The RSA key in
tests/fixtures/test-only-service-account-key.pem was generated for these tests only and grants nothing."""
import base64
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from opsengine import config, google_auth, llm, vision
from opsengine.engine import Engine
from opsengine.knowledge import ROOT, Knowledge

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
PHOTO = BREMORE / "incoming" / "photos" / "safe_pass_andriy_kovalenko.png"
TEST_KEY = ROOT / "tests" / "fixtures" / "test-only-service-account-key.pem"
VERTEX = {"AI_PROVIDER": "vertex", "USE_MOCK_AI": "false", "OPSENGINE_OFFLINE": "0", "VERTEX_PROJECT_ID": "opsengine-test",
          "VERTEX_REGION": "eu", "GOOGLE_APPLICATION_CREDENTIALS": ""}
REPLY = {"stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 3},
         "content": [{"type": "text", "text": "OK"}]}


class Capture:
    def __init__(self, reply=REPLY, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, url, headers, data):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(data)})
        if self.error:
            raise self.error
        return self.reply


class ProviderChoice(unittest.TestCase):
    def provider(self, **env):
        base = {"USE_MOCK_AI": "", "AI_PROVIDER": "", "ANTHROPIC_API_KEY": ""}
        with mock.patch.dict(os.environ, {**base, **env}):
            return config.ai_provider()

    def test_switching(self):
        self.assertEqual(self.provider(), "off")
        self.assertEqual(self.provider(ANTHROPIC_API_KEY="k"), "anthropic")
        self.assertEqual(self.provider(AI_PROVIDER="vertex"), "vertex")
        self.assertEqual(self.provider(AI_PROVIDER="mock"), "mock")
        self.assertEqual(self.provider(AI_PROVIDER="something-else"), "off")
        self.assertEqual(self.provider(AI_PROVIDER="vertex", USE_MOCK_AI="true"), "mock")  # mock always wins

    def test_vertex_hosts(self):
        self.assertTrue(llm.vertex_url("claude-opus-5-5", "eu", "p").startswith(
            "https://aiplatform.eu.rep.googleapis.com/v1/projects/p/locations/eu/publishers/anthropic/models/claude-opus-5-5:rawPredict"))
        self.assertIn("//aiplatform.googleapis.com/v1/projects/p/locations/global/", llm.vertex_url("m", "global", "p"))
        self.assertIn("//europe-west1-aiplatform.googleapis.com/", llm.vertex_url("m", "europe-west1", "p"))


class VertexCalls(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, VERTEX)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_request_shape_on_the_eu_multi_region(self):
        t = Capture()
        with mock.patch.dict(os.environ, {"OPSENGINE_MODEL": "claude-sonnet-5-5"}):
            out = llm.complete("Reply OK.", "Say OK.", purpose="health_check", transport=t, token=lambda: "tok123")
        self.assertEqual(out, "OK")
        sent = t.calls[0]
        self.assertTrue(sent["url"].startswith("https://aiplatform.eu.rep.googleapis.com/"))
        self.assertIn("/locations/eu/publishers/anthropic/models/claude-sonnet-5-5:rawPredict", sent["url"])
        self.assertEqual(sent["headers"]["authorization"], "Bearer tok123")
        self.assertEqual(sent["body"]["anthropic_version"], "vertex-2023-10-16")
        self.assertNotIn("model", sent["body"])
        self.assertNotIn("x-api-key", sent["headers"])

    def test_models_are_settings_read_at_each_call(self):
        t = Capture()
        with mock.patch.dict(os.environ, {"OPSENGINE_MODEL": "claude-haiku-5-5"}):
            llm.complete("s", "p", transport=t, token=lambda: "t")
        self.assertIn("/models/claude-haiku-5-5:rawPredict", t.calls[0]["url"])

    def test_photo_reader_drops_what_vertex_doesnt_support(self):
        t = Capture(reply={**REPLY, "content": [{"type": "text", "text": "{}"}]})
        with mock.patch.object(llm, "_post", t), mock.patch.object(google_auth, "access_token", lambda: "t"), \
                mock.patch.dict(os.environ, {"OPSENGINE_VISION_MODEL": "claude-opus-5-5"}):
            vision.read_photo(PHOTO, Knowledge.load(), expected_type="safe_pass")
        sent = t.calls[0]
        self.assertIn("/models/claude-opus-5-5:rawPredict", sent["url"])
        self.assertNotIn("fallbacks", sent["body"])
        self.assertNotIn("server-side-fallback", sent["headers"].get("anthropic-beta", ""))

    def test_anthropic_provider_still_works(self):
        t = Capture()
        with mock.patch.dict(os.environ, {"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}):
            llm.complete("s", "p", transport=t)
        self.assertEqual(t.calls[0]["url"], llm.API_URL)
        self.assertEqual(t.calls[0]["headers"]["x-api-key"], "test-key")
        self.assertIn("model", t.calls[0]["body"])

    def test_mock_mode_never_calls_even_when_vertex_is_set_up(self):
        t = Capture()
        with mock.patch.dict(os.environ, {"USE_MOCK_AI": "true"}):
            self.assertIsNone(llm.complete("s", "p", transport=t, token=lambda: "t"))
        self.assertEqual(t.calls, [])


class HumanFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, VERTEX)
        self.env.start()
        google_auth.clear_cache()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def ingest_with(self, **patches):
        e = Engine(BREMORE, state_dir=self.tmp, today=date(2026, 11, 11))
        e.scan()
        e.advance()
        with mock.patch.multiple(llm, **patches) if patches else mock.patch.dict(os.environ, {}):
            return e, e.ingest_photo(PHOTO, "w16")

    def test_no_credentials_means_a_person_checks(self):
        def no_metadata(*a, **k):
            raise urllib.error.URLError("not on Google Cloud")
        with mock.patch.object(google_auth, "_http", no_metadata):
            e, r = self.ingest_with()
        self.assertEqual(r["status"], "needs_review")
        rev = e.review_queue()[-1]
        self.assertIn("a person checks this photo", json.loads(rev["extraction"])["notes"] if isinstance(rev["extraction"], str) else rev["extraction"]["notes"])

    def test_server_errors_and_refusals_mean_a_person_checks(self):
        err = urllib.error.HTTPError("u", 503, "unavailable", {}, None)
        with mock.patch.object(google_auth, "access_token", lambda: "t"):
            _, r = self.ingest_with(_post=Capture(error=err))
            self.assertEqual(r["status"], "needs_review")
            _, r = self.ingest_with(_post=Capture(reply={"stop_reason": "refusal", "content": []}))
            self.assertEqual(r["status"], "needs_review")


class ServiceAccount(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.keyfile = self.tmp / "sa.json"
        self.keyfile.write_text(json.dumps({
            "type": "service_account", "client_email": "opsengine-ai@opsengine-test.iam.gserviceaccount.com",
            "private_key_id": "abc", "private_key": TEST_KEY.read_text(), "token_uri": "https://oauth2.googleapis.com/token"}))
        google_auth.clear_cache()

    def tearDown(self):
        shutil.rmtree(self.tmp)
        google_auth.clear_cache()

    def test_signed_sign_in_and_caching(self):
        seen = []

        def http(method, url, headers, data):
            seen.append((method, url, data))
            return {"access_token": "ya29.test", "expires_in": 3600}
        with mock.patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": str(self.keyfile)}):
            self.assertEqual(google_auth.access_token(http), "ya29.test")
            self.assertEqual(google_auth.access_token(http), "ya29.test")
        self.assertEqual(len(seen), 1)  # cached
        method, url, data = seen[0]
        self.assertEqual((method, url), ("POST", "https://oauth2.googleapis.com/token"))
        assertion = dict(x.split("=", 1) for x in data.decode().split("&"))["assertion"]
        head, claims, sig = assertion.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)
        body = json.loads(base64.urlsafe_b64decode(pad(claims)))
        self.assertEqual(body["iss"], "opsengine-ai@opsengine-test.iam.gserviceaccount.com")
        self.assertEqual(body["scope"], google_auth.SCOPE)
        self.assertLessEqual(body["exp"] - body["iat"], 3600)
        n, e, _ = google_auth.rsa_private_key(TEST_KEY.read_text())
        k = (n.bit_length() + 7) // 8
        em = pow(int.from_bytes(base64.urlsafe_b64decode(pad(sig)), "big"), e, n).to_bytes(k, "big")
        self.assertTrue(em.endswith(hashlib.sha256(f"{head}.{claims}".encode()).digest()))  # verifies with the public key

    def test_metadata_server_when_on_google_cloud(self):
        def http(method, url, headers, data):
            self.assertEqual(headers, {"Metadata-Flavor": "Google"})
            return {"access_token": "ya29.meta", "expires_in": 3600}
        with mock.patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": ""}):
            self.assertEqual(google_auth.access_token(http), "ya29.meta")

    def test_bad_key_file_gives_a_plain_reason_without_secrets(self):
        self.keyfile.write_text(json.dumps({"type": "authorized_user", "refresh_token": "SECRET"}))
        with mock.patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": str(self.keyfile)}):
            with self.assertRaises(google_auth.AuthError) as err:
                google_auth.access_token(lambda *a: {})
        self.assertNotIn("SECRET", str(err.exception))


class KeepingNamesOut(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, VERTEX)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_translation_never_sends_names_and_puts_them_back(self):
        t = Capture(reply={**REPLY, "content": [{"type": "text", "text": "Cześć [[P1]], twoja karta wygasa."}]})
        out = llm.translate("Hi Mantas, your card expires.", "Polish", names=["Mantas Petrauskas"], transport=t, token=lambda: "t")
        self.assertNotIn("Mantas", json.dumps(t.calls[0]["body"], ensure_ascii=False))
        self.assertEqual(out, "Cześć Mantas, twoja karta wygasa.")

    def test_a_lost_placeholder_means_a_person_translates(self):
        t = Capture(reply={**REPLY, "content": [{"type": "text", "text": "Cześć, twoja karta wygasa."}]})
        self.assertIsNone(llm.translate("Hi Mantas, your card expires.", "Polish", names=["Mantas Petrauskas"],
                                        transport=t, token=lambda: "t"))

    def test_drafts_never_send_names(self):
        t = Capture(reply={**REPLY, "content": [{"type": "text", "text": "# DRAFT RAMS\nBriefed: [[P1]], [[P2]]"}]})
        facts = {"workers": [{"name": "Gintaras Jonaitis", "role": "groundworker"}, {"name": "Paddy Walsh", "role": "operator"}]}
        out = llm.draft("rams", facts, names=["Gintaras Jonaitis", "Paddy Walsh"], transport=t, token=lambda: "t")
        sent = json.dumps(t.calls[0]["body"], ensure_ascii=False)
        self.assertNotIn("Gintaras", sent)
        self.assertNotIn("Walsh", sent)
        self.assertIn("Gintaras Jonaitis", out)

    def test_ai_logs_are_metadata_only(self):
        t = Capture()
        with self.assertLogs("opsengine.ai", level=logging.INFO) as logs:
            llm.translate("Hi Mantas Petrauskas, card SP-SAMPLE-70016 expires.", "Polish", names=["Mantas Petrauskas"],
                          transport=t, token=lambda: "t")
        text = "\n".join(logs.output)
        for leak in ("Mantas", "SP-SAMPLE", "expires", "card"):
            self.assertNotIn(leak, text)
        entry = json.loads(text.split("ai call ", 1)[1])
        self.assertEqual((entry["provider"], entry["purpose"], entry["input_tokens"]), ("vertex", "translate", 12))


if __name__ == "__main__":
    unittest.main()
