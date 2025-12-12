from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Comment
from urllib.parse import urlparse, urljoin


DEFAULT_HEADERS = {
    # A common desktop UA to avoid simple bot blocks.
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9",
    # Avoid brotli ("br") because httpx only decodes it when brotli extras
    # are installed. Many SG sites default to br if advertised, leading to
    # garbled text in environments without brotli.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

def mirror_on_block_enabled() -> bool:
    """Enable global mirror fallback on 403/429 via env var."""
    val = os.getenv("NEWSCLI_MIRROR_ON_403", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ArticleContent:
    title: str
    byline: Optional[str]
    text: str
    images: list[str] = field(default_factory=list)


async def fetch_html(url: str) -> str:
    parsed = urlparse(url)
    headers = dict(DEFAULT_HEADERS)
    # Some SG outlets require a plausible referer.
    if parsed.netloc.endswith("mothership.sg"):
        headers["Referer"] = "https://mothership.sg/"
    elif parsed.netloc.endswith("straitstimes.com"):
        headers["Referer"] = "https://www.straitstimes.com/"

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            text = resp.text
            if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                # If not HTML-ish, still allow if it looks like markup.
                if not text.lstrip().startswith("<"):
                    raise ValueError(f"Non-HTML content-type: {ctype}")
            return text
        except httpx.ReadTimeout:
            # One quick retry on timeouts.
            resp_retry = await client.get(url, headers=headers)
            resp_retry.raise_for_status()
            return resp_retry.text
        except httpx.HTTPStatusError as e:
            # Retry once with a slightly different UA on 403/429.
            status = e.response.status_code
            if status in (403, 429):
                retry_headers = dict(headers)
                retry_headers["User-Agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
                resp2 = await client.get(url, headers=retry_headers)
                try:
                    resp2.raise_for_status()
                    return resp2.text
                except httpx.HTTPStatusError as e2:
                    # Mothership blocks bot fetches; use an explicit mirror fallback.
                    if parsed.netloc.endswith("mothership.sg") and e2.response.status_code in (403, 429):
                        mirror_url = "https://r.jina.ai/http://" + url.removeprefix("https://").removeprefix("http://")
                        mirror_resp = await client.get(mirror_url, headers=headers)
                        mirror_resp.raise_for_status()
                        return mirror_resp.text
                    # Optional global mirror fallback for other sites.
                    if mirror_on_block_enabled() and e2.response.status_code in (403, 429):
                        mirror_url = "https://r.jina.ai/http://" + url.removeprefix("https://").removeprefix("http://")
                        mirror_resp = await client.get(mirror_url, headers=headers)
                        mirror_resp.raise_for_status()
                        return mirror_resp.text
                    raise
            raise


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _link_density(node) -> float:
    text = node.get_text(" ", strip=True) or ""
    if not text:
        return 1.0
    link_text = " ".join(a.get_text(" ", strip=True) for a in node.find_all("a"))
    return min(1.0, len(link_text) / max(1, len(text)))


def _candidate_score(node) -> float:
    # Score based on paragraph mass, penalize navigation/links.
    tag_name = getattr(node, "name", "") or ""
    classes = " ".join(node.get("class", []) or [])
    node_id = node.get("id", "") or ""
    ident = f"{classes} {node_id}".lower()

    positive_re = re.compile(r"(article|content|post|entry|story|main|body|text)", re.I)
    negative_re = re.compile(
        r"(comment|nav|footer|header|sidebar|menu|advert|promo|related|share|cookie|social|subscribe)",
        re.I,
    )

    paragraphs = node.find_all("p")
    long_paras = [p for p in paragraphs if len(p.get_text(" ", strip=True)) >= 40]
    para_text_len = sum(len(p.get_text(" ", strip=True)) for p in paragraphs)

    score = para_text_len / 100.0 + len(long_paras) * 2.0
    if tag_name in ("article", "main"):
        score += 10.0
    if positive_re.search(ident):
        score += 6.0
    if negative_re.search(ident):
        score -= 8.0

    ld = _link_density(node)
    score *= max(0.1, 1.0 - ld)
    return score


def _best_container(soup: BeautifulSoup):
    # Prefer semantic containers if they look substantial.
    semantic = soup.find("article") or soup.find("main")
    if semantic and _candidate_score(semantic) >= 5:
        return semantic

    candidates = []
    for tag in soup.find_all(["article", "main", "section", "div"]):
        try:
            candidates.append((tag, _candidate_score(tag)))
        except Exception:
            continue
    if not candidates:
        return soup.body or soup
    candidates.sort(key=lambda t: t[1], reverse=True)
    best, best_score = candidates[0]
    return best if best_score >= 3 else (soup.body or soup)


_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|bmp|tiff)(\?|#|$)", re.I)
_SKIP_IMAGE_RE = re.compile(
    r"(telegram-button|wa-button|whatsapp-button|facebook-button|twitter-button|share-button)",
    re.I,
)


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _normalize_image_url(raw_url: str, base_url: str | None) -> Optional[str]:
    url = (raw_url or "").strip()
    if not url or url.startswith("data:") or re.search(r"\s", url):
        return None
    if url.startswith("//"):
        url = "https:" + url
    if _SKIP_IMAGE_RE.search(url):
        return None
    if re.search(r"\.(svg|ico)(\?|#|$)", url, re.I):
        return None
    if base_url:
        url = urljoin(base_url, url)
    return url


def _pick_img_source(img) -> Optional[str]:
    src = (
        img.get("src")
        or img.get("data-src")
        or img.get("data-original")
        or img.get("data-lazy-src")
    )
    if not src:
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            candidates = [
                part.strip().split(" ")[0]
                for part in srcset.split(",")
                if part.strip()
            ]
            if candidates:
                src = candidates[-1]
    return src


def _is_small_image(img) -> bool:
    try:
        width = int(img.get("width") or 0)
        height = int(img.get("height") or 0)
    except Exception:
        return False
    if width and height and (width < 120 or height < 120):
        return True
    return False


def _extract_images_from_plain_text(text: str) -> list[str]:
    urls: list[str] = []
    for match in re.findall(r"https?://[^\s)]+", text):
        norm = _normalize_image_url(match, None)
        if norm and _IMAGE_EXT_RE.search(norm):
            urls.append(norm)
    return _dedupe(urls)[:5]


def _extract_images_from_html(
    soup: BeautifulSoup, container: BeautifulSoup, base_url: str | None
) -> list[str]:
    urls: list[str] = []

    def add(raw: str) -> None:
        norm = _normalize_image_url(raw, base_url)
        if norm and norm not in urls:
            urls.append(norm)

    # OG / Twitter images are usually the cover.
    for meta in soup.find_all("meta", property=re.compile(r"^og:image", re.I)):
        prop = (meta.get("property") or "").lower()
        if prop not in {"og:image", "og:image:url", "og:image:secure_url"}:
            continue
        content = meta.get("content")
        if content:
            add(content)
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:image", re.I)}):
        name = (meta.get("name") or "").lower()
        if name not in {"twitter:image", "twitter:image:src"}:
            continue
        content = meta.get("content")
        if content:
            add(content)
    link_src = soup.find("link", rel=re.compile(r"image_src", re.I))
    if link_src and link_src.get("href"):
        add(link_src["href"])

    # Inline images inside main container.
    for img in container.find_all("img"):
        if _is_small_image(img):
            continue
        src = _pick_img_source(img)
        if not src:
            continue
        add(src)

    return urls[:5]


def extract_readable_text(html: str, base_url: str | None = None) -> ArticleContent:
    # Some mirrors / sites may return odd control bytes; sanitize before parsing.
    sanitized = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", html)
    # If it doesn't look like HTML, treat as plain text.
    if "<" not in sanitized and ">" not in sanitized:
        lines = [ln.rstrip() for ln in sanitized.splitlines()]
        title = "(untitled)"
        byline = None
        # Mirrors (e.g., r.jina.ai) often prefix plain text with metadata.
        for idx, ln in enumerate(lines[:8]):
            m = re.match(r"^\s*title\s*:\s*(.+)$", ln, re.I)
            if m:
                maybe_title = m.group(1).strip()
                if maybe_title:
                    title = maybe_title
                lines[idx] = ""
                break

        filtered: list[str] = []
        for ln in lines:
            if re.match(r"^\s*(url source|published time|markdown content)\s*:", ln, re.I):
                continue
            filtered.append(ln)
        filtered_text = "\n".join(filtered)
        text = _clean_text(filtered_text)
        images = _extract_images_from_plain_text(filtered_text)
        return ArticleContent(title=title, byline=byline, text=text, images=images)

    soup = BeautifulSoup(sanitized, "html.parser")

    # Remove comments and obvious boilerplate.
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe"]):
        tag.decompose()

    # Title heuristics: prefer OG title, then h1, then <title>.
    title = ""
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    container = _best_container(soup)
    images = _extract_images_from_html(soup, container, base_url)

    # Byline heuristics: search near top of container.
    byline = None
    by = container.find(attrs={"class": re.compile(r"(byline|author|writer)", re.I)})
    if not by:
        by = soup.find(attrs={"class": re.compile(r"(byline|author|writer)", re.I)})
    if by:
        byline_text = by.get_text(" ", strip=True)
        byline = byline_text or None

    # Extract meaningful blocks.
    blocks = []
    for el in container.find_all(["p", "h2", "h3", "li", "blockquote"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h2", "h3"):
            blocks.append(txt)
            continue
        if len(txt) < 20:
            continue
        blocks.append(txt)

    if len(blocks) < 3:
        text = container.get_text("\n", strip=True)
    else:
        text = "\n\n".join(blocks)

    text = _clean_text(text)
    if len(text) < 120:
        # Fallback to OG/description if extraction is too thin.
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            desc = og_desc["content"].strip()
            if len(desc) > len(text):
                text = desc

    return ArticleContent(title=title or "(untitled)", byline=byline, text=text, images=images)


async def fetch_article_text(url: str) -> ArticleContent:
    html = await fetch_html(url)
    return extract_readable_text(html, base_url=url)
