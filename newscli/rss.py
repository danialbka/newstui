from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

import asyncio
from urllib.parse import urlparse

import feedparser
import httpx


@dataclass(frozen=True)
class Article:
    title: str
    link: str
    author: Optional[str]
    published: Optional[dt.datetime]
    summary: str
    source: str
    content_html: Optional[str] = None


async def fetch_feed(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-SG,en;q=0.9",
        # Avoid brotli ("br") because httpx only decodes it when brotli extras
        # are installed.
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    parsed = urlparse(url)
    if parsed.netloc.endswith("mothership.sg"):
        headers["Referer"] = "https://mothership.sg/"
    elif parsed.netloc.endswith("theindependent.sg"):
        headers["Referer"] = "https://theindependent.sg/"

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        # Small retry loop for flaky feeds / simple bot blocks.
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                text = resp.text
                ctype = (resp.headers.get("content-type") or "").lower()
                if "text/html" in ctype or text.lstrip().startswith("<!doctype html") or text.lstrip().startswith("<html"):
                    raise ValueError("Got HTML instead of RSS")
                return text
            except (httpx.ReadTimeout, httpx.ConnectError) as e:
                last_exc = e
                await asyncio.sleep(0.5)
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code in (403, 429) and attempt == 0:
                    alt_headers = dict(headers)
                    alt_headers["User-Agent"] = (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                    resp2 = await client.get(url, headers=alt_headers)
                    resp2.raise_for_status()
                    return resp2.text
                break

        # Fallback: AP News via official RSS if rsshub is slow.
        if "rsshub.app/apnews" in url:
            official = "https://apnews.com/apf-topnews?output=rss"
            resp3 = await client.get(official, headers=headers)
            resp3.raise_for_status()
            return resp3.text

        assert last_exc is not None
        raise last_exc


def parse_feed(xml_text: str, source_name: str) -> List[Article]:
    feed = feedparser.parse(xml_text)
    articles: List[Article] = []
    for entry in feed.entries[:200]:
        title = str(entry.get("title", "")).strip() or "(untitled)"
        link = str(entry.get("link", "")).strip()
        author = entry.get("author") or entry.get("dc_creator") or None
        if isinstance(author, str):
            author = author.strip() or None
        published = None
        if entry.get("published_parsed"):
            published = dt.datetime(*entry.published_parsed[:6], tzinfo=dt.timezone.utc)
        summary = str(entry.get("summary", "")).strip()
        content_html = None
        content = entry.get("content")
        if isinstance(content, list) and content:
            value = content[0].get("value")
            if isinstance(value, str):
                content_html = value.strip() or None
        articles.append(
            Article(
                title=title,
                link=link,
                author=author,
                published=published,
                summary=summary,
                source=source_name,
                content_html=content_html,
            )
        )
    return articles
