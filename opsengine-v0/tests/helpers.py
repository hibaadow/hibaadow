import json
import os

os.environ["OPSENGINE_OFFLINE"] = "1"  # tests never call the Claude API

from opsengine.knowledge import ROOT

SAMPLE = ROOT / "data" / "sample" / "liffey_interiors"
PHOTOS = ROOT / "tests" / "fixtures" / "photos"
REPLIES = json.loads((PHOTOS / "responses.json").read_text())


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
