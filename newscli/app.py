from __future__ import annotations

import asyncio
import datetime as dt
import webbrowser
from typing import List, Optional

import httpx
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, ListItem, ListView, Static

from .article import fetch_article_text
from .analysis import analyze_tone
from .config import Source, load_sources
from .rss import Article, fetch_feed, parse_feed


class SourceSelected(Message):
    def __init__(self, source: Source) -> None:
        super().__init__()
        self.source = source


class ArticleSelected(Message):
    def __init__(self, article: Article) -> None:
        super().__init__()
        self.article = article


class SourcesList(ListView):
    def __init__(self, sources: List[Source], **kwargs) -> None:
        super().__init__(**kwargs)
        self.sources = sources

    def on_mount(self) -> None:
        for src in self.sources:
            self.append(ListItem(Static(src.name)))
        if self.sources:
            self.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        self.post_message(SourceSelected(self.sources[idx]))


class ArticlesList(ListView):
    articles: List[Article] = reactive([])

    BINDINGS = [
        Binding("enter", "open", "Read"),
        Binding("o", "open", show=False),
    ]

    def set_articles(self, articles: List[Article]) -> None:
        self.articles = articles
        self.clear()
        for art in articles:
            author = f" — {art.author}" if art.author else ""
            self.append(ListItem(Static(f"{art.title}{author}")))
        if articles:
            self.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        if 0 <= idx < len(self.articles):
            self.post_message(ArticleSelected(self.articles[idx]))

    def action_open(self) -> None:
        idx = self.index or 0
        if 0 <= idx < len(self.articles):
            self.app.post_message(ArticleSelected(self.articles[idx]))
            if hasattr(self.app, "open_reader"):
                self.app.open_reader(self.articles[idx])

class ArticleReader(ModalScreen):
    BINDINGS = [
        Binding("q", "close", "Close"),
        Binding("escape", "close", show=False),
        Binding("b", "browser", "Browser"),
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("down", "scroll_down", show=False),
        Binding("up", "scroll_up", show=False),
    ]

    def __init__(self, article: Article) -> None:
        super().__init__()
        self.article = article
        self.body: Static | None = None
        self.scroll: VerticalScroll | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="reader_scroll"):
            yield Static("Loading...", id="reader_body")
        yield Footer()

    async def on_mount(self) -> None:
        self.scroll = self.query_one("#reader_scroll", VerticalScroll)
        self.body = self.query_one("#reader_body", Static)
        self.scroll.styles.height = "1fr"
        self.scroll.styles.padding = (1, 2)
        try:
            content = await fetch_article_text(self.article.link)
            title = content.title or self.article.title
            byline = content.byline or (self.article.author or "unknown")
            text = content.text or self.article.summary
            self.body.update(  # type: ignore[union-attr]
                "\n".join(
                    [
                        f"[b]{title}[/b]",
                        f"Author: {byline}",
                        f"Source: {self.article.source}",
                        f"Link: {self.article.link}",
                        "",
                        text,
                    ]
                )
            )
        except Exception as e:
            self.body.update(  # type: ignore[union-attr]
                "\n".join(
                    [
                        f"[b]{self.article.title}[/b]",
                        f"Failed to fetch full article: {e}",
                        "",
                        self.article.summary or "",
                        "",
                        "Press 'b' to open in browser.",
                    ]
                )
            )

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_browser(self) -> None:
        if self.article.link:
            webbrowser.open(self.article.link)

    def action_scroll_down(self) -> None:
        if self.scroll:
            self.scroll.scroll_down()

    def action_scroll_up(self) -> None:
        if self.scroll:
            self.scroll.scroll_up()


class ArticleDetail(Static):
    article: Optional[Article] = reactive(None)
    show_author_links: bool = reactive(False)

    def set_article(self, article: Optional[Article]) -> None:
        self.article = article
        self.show_author_links = False
        self.refresh()

    def toggle_author_links(self) -> None:
        self.show_author_links = not self.show_author_links
        self.refresh()

    def render(self) -> str:
        if not self.article:
            return "Select an article."

        art = self.article
        published = art.published.isoformat() if art.published else "unknown"
        author = art.author or "unknown"
        tone = analyze_tone(f"{art.title}\n{art.summary}")

        lines = [
            f"[b]{art.title}[/b]",
            f"Source: {art.source}",
            f"Author: {author}",
            f"Published: {published}",
            f"Link: {art.link}",
            "",
        ]

        if tone:
            lines += [
                "[b]Tone (content-based)[/b]",
                f"Sentiment: {tone.sentiment:+.2f} (pos {tone.pos:.2f} / neu {tone.neu:.2f} / neg {tone.neg:.2f})",
                tone.subjectivity_hint,
                "",
            ]

        if art.summary:
            lines += ["[b]Summary[/b]", art.summary.strip(), ""]

        if self.show_author_links and art.author:
            q = art.author.replace(" ", "+")
            lines += [
                "[b]Author research links (you open manually)[/b]",
                f"DuckDuckGo: https://duckduckgo.com/?q={q}+journalist",
                f"Google: https://www.google.com/search?q={q}+journalist",
                f"Wikipedia: https://en.wikipedia.org/wiki/Special:Search?search={q}",
                "",
                "Note: This app does not scrape personal profiles.",
            ]

        return "\n".join(lines)

class StatusBar(Horizontal):
    """Bottom bar showing Singapore weather and local time."""

    weather_text: str = reactive("Weather: …")
    time_text: str = reactive("Time: …")

    def compose(self) -> ComposeResult:
        yield Static("", id="sb_left")
        yield Static("", id="sb_spacer")
        yield Static("", id="sb_right")

    def on_mount(self) -> None:
        self.query_one("#sb_spacer", Static).styles.width = "1fr"
        # Seed initial content so the bar isn't blank on first paint.
        self.query_one("#sb_left", Static).update(self.weather_text)
        self.query_one("#sb_right", Static).update(self.time_text)
        self.set_interval(1.0, self._update_time)
        self.set_interval(600.0, self._schedule_weather, pause=False)
        self._update_time()
        self.call_after_refresh(self._schedule_weather)

    def watch_weather_text(self, value: str) -> None:
        self.query_one("#sb_left", Static).update(value)

    def watch_time_text(self, value: str) -> None:
        self.query_one("#sb_right", Static).update(value)

    def _update_time(self) -> None:
        try:
            tz = ZoneInfo("Asia/Singapore")
        except ZoneInfoNotFoundError:
            tz = dt.timezone(dt.timedelta(hours=8))
        now = dt.datetime.now(tz)
        self.time_text = f"{now:%a %d %b %H:%M:%S} SGT"

    def _schedule_weather(self) -> None:
        asyncio.create_task(self._refresh_weather())

    async def _refresh_weather(self) -> None:
        # Open-Meteo current weather for Singapore (no API key).
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=1.3521&longitude=103.8198"
            "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
            "&timezone=Asia%2FSingapore"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            current = data.get("current") or {}
            temp = current.get("temperature_2m")
            hum = current.get("relative_humidity_2m")
            code = current.get("weather_code")
            wind = current.get("wind_speed_10m")
            desc = _WEATHER_CODES.get(int(code), "Unknown") if code is not None else "Unknown"
            parts = []
            if temp is not None:
                parts.append(f"{temp:.0f}°C")
            if hum is not None:
                parts.append(f"{hum:.0f}% RH")
            if wind is not None:
                parts.append(f"{wind:.0f} km/h")
            detail = " · ".join(parts)
            self.weather_text = f"SG Weather: {desc}" + (f" ({detail})" if detail else "")
        except Exception:
            # Keep last known value on failure.
            if self.weather_text == "Weather: …":
                self.weather_text = "SG Weather: unavailable"


_WEATHER_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Heavy showers",
    82: "Violent showers",
    95: "Thunderstorm",
    96: "Thunderstorm + hail",
    99: "Severe thunderstorm + hail",
}


class NewsApp(App):
    CSS = """
    Screen {
        layout: vertical;
        background: #000000;
        color: #e8ffe8;
    }

    Header, Footer, StatusBar, #status_bar {
        background: #050505;
        color: #e8ffe8;
    }

    #body { height: 1fr; }
    #sources { width: 30%; border: tall #9fe870; }
    #articles { width: 40%; border: tall #9fe870; }
    #detail { width: 1fr; border: tall #9fe870; padding: 1 2; overflow: auto; }

    StatusBar, #status_bar {
        height: 2;
        padding: 0 1;
        border-top: heavy #9fe870;
        dock: bottom;
        width: 100%;
    }

    ListView:focus > ListItem.--highlight {
        background: #0f2410;
        color: #e8ffe8;
    }

    ListItem { color: #e8ffe8; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "author_links", "Author links"),
        Binding("enter", "open_link", "Read"),
        Binding("b", "open_browser", "Browser"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    sources: List[Source]
    current_source: Optional[Source]
    current_articles: List[Article]
    current_article: Optional[Article]

    def __init__(self) -> None:
        super().__init__()
        self.sources = load_sources()
        self.current_source = None
        self.current_articles = []
        self.current_article = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield SourcesList(self.sources, id="sources")
            yield ArticlesList(id="articles")
            yield ArticleDetail(id="detail")
        yield StatusBar(id="status_bar")

    async def on_mount(self) -> None:
        if self.sources:
            await self.load_source(self.sources[0])

    async def load_source(self, source: Source) -> None:
        self.current_source = source
        detail = self.query_one(ArticleDetail)
        detail.set_article(None)
        articles_view = self.query_one(ArticlesList)
        articles_view.set_articles([])
        self.title = f"newscli — {source.name}"
        try:
            xml = await fetch_feed(source.url)
            articles = parse_feed(xml, source.name)
        except Exception as e:
            articles = []
            detail.update(f"Failed to load feed: {e}")

        self.current_articles = articles
        articles_view.set_articles(articles)
        if articles:
            self.current_article = articles[0]
            detail.set_article(articles[0])

    async def on_source_selected(self, msg: SourceSelected) -> None:
        await self.load_source(msg.source)

    def on_article_selected(self, msg: ArticleSelected) -> None:
        self.current_article = msg.article
        self.query_one(ArticleDetail).set_article(msg.article)

    async def action_refresh(self) -> None:
        if self.current_source:
            await self.load_source(self.current_source)

    def action_open_link(self) -> None:
        if self.current_article:
            self.open_reader(self.current_article)

    def action_open_browser(self) -> None:
        if self.current_article and self.current_article.link:
            webbrowser.open(self.current_article.link)

    def action_author_links(self) -> None:
        self.query_one(ArticleDetail).toggle_author_links()

    def open_reader(self, article: Article) -> None:
        self.push_screen(ArticleReader(article))


def run() -> None:
    NewsApp().run()
