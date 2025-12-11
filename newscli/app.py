from __future__ import annotations

import asyncio
import webbrowser
from typing import List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
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
    ]

    def __init__(self, article: Article) -> None:
        super().__init__()
        self.article = article
        self.body = Static("Loading...", id="reader_body")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield self.body
        yield Footer()

    async def on_mount(self) -> None:
        self.body.styles.overflow = "auto"
        self.body.styles.height = "1fr"
        try:
            content = await fetch_article_text(self.article.link)
            title = content.title or self.article.title
            byline = content.byline or (self.article.author or "unknown")
            text = content.text or self.article.summary
            self.body.update(
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
            self.body.update(
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
        self.body.scroll_down()

    def action_scroll_up(self) -> None:
        self.body.scroll_up()


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


class NewsApp(App):
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #sources { width: 30%; border: tall $primary; }
    #articles { width: 40%; border: tall $primary; }
    #detail { width: 1fr; border: tall $primary; padding: 1 2; overflow: auto; }
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
        yield Footer()

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
