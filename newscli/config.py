from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class Source:
    name: str
    url: str


DEFAULT_SOURCES: List[Source] = [
    Source("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    Source("Reuters World", "https://feeds.reuters.com/Reuters/worldNews"),
    Source("AP News", "https://rsshub.app/apnews/topics/apf-topnews"),
    Source("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    Source("Hacker News", "https://news.ycombinator.com/rss"),
]


def config_dir() -> Path:
    return Path.home() / ".config" / "newscli"


def load_sources() -> List[Source]:
    path = config_dir() / "sources.json"
    if not path.exists():
        return DEFAULT_SOURCES
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources: List[Source] = []
        for item in raw:
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            if name and url:
                sources.append(Source(name=name, url=url))
        return sources or DEFAULT_SOURCES
    except Exception:
        return DEFAULT_SOURCES
