"""Tests for the stub client and the default-client selector."""

from __future__ import annotations

import json
import os
from unittest import mock

from rapid_agent.client import StubClient, get_default_client


def test_stub_client_returns_valid_brief_json():
    stub = StubClient()
    prompt = (
        "TOPIC: testing topic\n"
        "### SOURCE 1\nURL: https://example.com/a\nTITLE: Page A\nTEXT: hello\n"
    )
    resp = stub.complete(prompt)
    payload = json.loads(resp.text)
    assert payload["topic"] == "testing topic"
    assert payload["items"][0]["url"] == "https://example.com/a"
    assert resp.input_tokens > 0
    assert resp.output_tokens > 0


def test_get_default_client_returns_stub_when_no_key():
    with mock.patch.dict(os.environ, {}, clear=True):
        c = get_default_client()
    assert isinstance(c, StubClient)
