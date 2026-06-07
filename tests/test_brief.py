"""Tests for the Brief model and the guarded fetcher.

Standard-library ``unittest`` only. The Brief model needs ``pydantic`` and
the fetcher needs ``requests``; those test cases are skipped (not failed)
when the dependency is not installed.
"""

from __future__ import annotations

import unittest

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_PYDANTIC = False

try:
    import requests  # noqa: F401

    HAS_REQUESTS = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_REQUESTS = False

HAS_DEPS = HAS_PYDANTIC and HAS_REQUESTS

if HAS_DEPS:
    from rapid_agent.brief import (
        Brief,
        BriefItem,
        _extract_title,
        _strip_html,
        fetch_source,
    )
    from rapid_agent.governance import EgressAllowlist, EgressDenied


@unittest.skipUnless(HAS_DEPS, "requires pydantic and requests")
class BriefModelTests(unittest.TestCase):
    def test_roundtrips_through_json(self):
        b = Brief(
            topic="t",
            items=[
                BriefItem(
                    url="https://example.com",
                    title="ex",
                    summary="s",
                    key_points=["a", "b"],
                )
            ],
            overall_takeaway="ok",
        )
        blob = b.model_dump_json()
        again = Brief.model_validate_json(blob)
        self.assertEqual(again.items[0].url, "https://example.com")

    def test_key_points_default_empty(self):
        item = BriefItem(url="https://x", title="x", summary="s")
        self.assertEqual(item.key_points, [])


@unittest.skipUnless(HAS_DEPS, "requires pydantic and requests")
class HtmlHelperTests(unittest.TestCase):
    def test_strip_html_removes_tags_and_collapses_whitespace(self):
        html = "<p>Hello   <b>world</b>!\n  Next line.</p>"
        self.assertEqual(_strip_html(html), "Hello world ! Next line.")

    def test_strip_html_unescapes_entities(self):
        self.assertEqual(_strip_html("<p>a &amp; b</p>"), "a & b")

    def test_extract_title_finds_title_or_uses_fallback(self):
        page = "<html><head><title>Real Title</title></head><body></body></html>"
        self.assertEqual(_extract_title(page, fallback="https://x"), "Real Title")
        self.assertEqual(_extract_title("<html></html>", fallback="https://x"), "https://x")


@unittest.skipUnless(HAS_DEPS, "requires pydantic and requests")
class FetchSourceTests(unittest.TestCase):
    def test_blocks_disallowed_host_without_network(self):
        allow = EgressAllowlist(allowed_hosts=["example.com"])

        class FailSession:
            def get(self, *a, **kw):  # pragma: no cover - must not be reached
                raise AssertionError("network call should not happen")

        with self.assertRaises(EgressDenied):
            fetch_source("https://evil.test/path", allow, session=FailSession())

    def test_fetches_allowed_host_and_cleans_html(self):
        allow = EgressAllowlist(allowed_hosts=["example.com"])

        class _Resp:
            text = (
                "<html><head><title>Hi</title></head>"
                "<body><p>Body   text.</p></body></html>"
            )

            def raise_for_status(self):
                return None

        class OkSession:
            def get(self, url, timeout=None, headers=None):
                return _Resp()

        src = fetch_source("https://example.com/x", allow, session=OkSession())
        self.assertEqual(src.title, "Hi")
        self.assertIn("Body text.", src.text)
        self.assertNotIn("<p>", src.text)


if __name__ == "__main__":
    unittest.main()
