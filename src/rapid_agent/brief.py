"""Typed Brief model and a guarded URL fetcher."""

from __future__ import annotations

import html
import re
from typing import List, Optional

import requests
from pydantic import BaseModel, Field

from rapid_agent.governance import EgressAllowlist


class BriefItem(BaseModel):
    """One summarized source."""

    url: str
    title: str
    summary: str = Field(description="A 2-4 sentence summary in plain English.")
    key_points: List[str] = Field(
        default_factory=list, description="3-5 bullet points."
    )


class Brief(BaseModel):
    """Final structured output: a multi-source brief."""

    topic: str
    items: List[BriefItem]
    overall_takeaway: str = Field(
        description="One paragraph synthesizing all sources."
    )


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _strip_html(text: str) -> str:
    """Crude HTML to text. Good enough for hackathon demo."""
    no_tags = _TAG_RE.sub(" ", text)
    unescaped = html.unescape(no_tags)
    collapsed = _WHITESPACE_RE.sub(" ", unescaped)
    return collapsed.strip()


def _extract_title(html_text: str, fallback: str) -> str:
    m = _TITLE_RE.search(html_text)
    if not m:
        return fallback
    title = _strip_html(m.group(1))
    return title or fallback


def fetch_source(
    url: str,
    allowlist: EgressAllowlist,
    *,
    timeout: float = 10.0,
    max_chars: int = 4000,
    session: Optional[requests.Session] = None,
) -> "FetchedSource":
    """Fetch one URL under the allowlist and return cleaned text.

    Raises EgressDenied if the URL host is not on the allowlist.
    """
    allowlist.check(url)
    sess = session or requests
    resp = sess.get(url, timeout=timeout, headers={"User-Agent": "rapid-agent/0.1"})
    resp.raise_for_status()
    body = resp.text
    title = _extract_title(body, fallback=url)
    text = _strip_html(body)[:max_chars]
    return FetchedSource(url=url, title=title, text=text)


class FetchedSource(BaseModel):
    """Internal: cleaned text from one source. Not part of the final Brief."""

    url: str
    title: str
    text: str
