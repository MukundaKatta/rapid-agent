"""Tests for the stub client and the default-client selector.

Standard-library ``unittest`` only. The client module depends only on the
standard library, so these tests run without any third-party packages.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from rapid_agent.client import (
    PRICE_INPUT_PER_1K_USD,
    PRICE_OUTPUT_PER_1K_USD,
    LLMResponse,
    StubClient,
    get_default_client,
)


class StubClientTests(unittest.TestCase):
    def test_returns_valid_brief_json(self):
        stub = StubClient()
        prompt = (
            "TOPIC: testing topic\n"
            "### SOURCE 1\nURL: https://example.com/a\nTITLE: Page A\nTEXT: hello\n"
        )
        resp = stub.complete(prompt)
        payload = json.loads(resp.text)
        self.assertEqual(payload["topic"], "testing topic")
        self.assertEqual(payload["items"][0]["url"], "https://example.com/a")
        self.assertGreater(resp.input_tokens, 0)
        self.assertGreater(resp.output_tokens, 0)

    def test_handles_multiple_sources(self):
        stub = StubClient()
        prompt = (
            "TOPIC: multi\n"
            "### SOURCE 1\nURL: https://example.com/a\nTITLE: A\nTEXT: x\n"
            "### SOURCE 2\nURL: https://example.com/b\nTITLE: B\nTEXT: y\n"
        )
        payload = json.loads(stub.complete(prompt).text)
        urls = {item["url"] for item in payload["items"]}
        self.assertEqual(urls, {"https://example.com/a", "https://example.com/b"})

    def test_records_each_call(self):
        stub = StubClient()
        stub.complete("TOPIC: t\n")
        stub.complete("TOPIC: u\n")
        self.assertEqual(len(stub.calls), 2)


class LLMResponseTests(unittest.TestCase):
    def test_usd_uses_configured_pricing(self):
        resp = LLMResponse(text="x", input_tokens=1000, output_tokens=1000)
        expected = PRICE_INPUT_PER_1K_USD + PRICE_OUTPUT_PER_1K_USD
        self.assertAlmostEqual(resp.usd, expected)

    def test_zero_tokens_is_zero_cost(self):
        resp = LLMResponse(text="", input_tokens=0, output_tokens=0)
        self.assertEqual(resp.usd, 0.0)


class GetDefaultClientTests(unittest.TestCase):
    def test_returns_stub_when_no_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            client = get_default_client()
        self.assertIsInstance(client, StubClient)

    def test_explicit_none_key_falls_back_to_stub(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            client = get_default_client(api_key=None)
        self.assertIsInstance(client, StubClient)


if __name__ == "__main__":
    unittest.main()
