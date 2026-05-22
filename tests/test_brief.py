"""Tests for the Brief model and the guarded fetcher."""

from __future__ import annotations

import pytest

from rapid_agent.brief import Brief, BriefItem, _extract_title, _strip_html, fetch_source
from rapid_agent.governance import EgressAllowlist, EgressDenied


def test_brief_roundtrips_through_json():
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
    assert again.items[0].url == "https://example.com"


def test_strip_html_removes_tags_and_collapses_whitespace():
    html = "<p>Hello   <b>world</b>!\n  Next line.</p>"
    assert _strip_html(html) == "Hello world ! Next line."


def test_extract_title_finds_title_or_uses_fallback():
    page = "<html><head><title>Real Title</title></head><body></body></html>"
    assert _extract_title(page, fallback="https://x") == "Real Title"
    assert _extract_title("<html></html>", fallback="https://x") == "https://x"


def test_fetch_source_blocks_disallowed_host_without_network():
    allow = EgressAllowlist(allowed_hosts=["example.com"])

    class FailSession:
        def get(self, *a, **kw):  # pragma: no cover  - must not be reached
            raise AssertionError("network call should not happen")

    with pytest.raises(EgressDenied):
        fetch_source("https://evil.test/path", allow, session=FailSession())
