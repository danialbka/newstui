from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

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


async def fetch_feed(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


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
        articles.append(
            Article(
                title=title,
                link=link,
                author=author,
                published=published,
                summary=summary,
                source=source_name,
            )
        )
    return articles
