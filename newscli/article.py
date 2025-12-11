from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ArticleContent:
    title: str
    byline: Optional[str]
    text: str


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(url, headers={"User-Agent": "newscli/0.1"})
        resp.raise_for_status()
        return resp.text


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_readable_text(html: str) -> ArticleContent:
    soup = BeautifulSoup(html, "html.parser")

    # Remove obvious boilerplate
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)

    # Try to locate main article-like area
    main = soup.find("article") or soup.find("main")
    container = main if main else soup.body or soup

    # Byline heuristics
    byline = None
    by = container.find(attrs={"class": re.compile(r"(byline|author)", re.I)})
    if by:
        byline_text = by.get_text(" ", strip=True)
        byline = byline_text or None

    # Collect paragraphs
    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    # Fallback to all text if paragraphs are scarce
    if len(paras) < 3:
        text = container.get_text("\n", strip=True)
    else:
        text = "\n\n".join(paras)

    return ArticleContent(title=title or "(untitled)", byline=byline, text=_clean_text(text))


async def fetch_article_text(url: str) -> ArticleContent:
    html = await fetch_html(url)
    return extract_readable_text(html)

