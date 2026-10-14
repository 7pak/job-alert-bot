from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    # Greenhouse sends the HTML entity-escaped, so unescape once before parsing.
    parser = _TextParser()
    parser.feed(html.unescape(raw))
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def time_ago(dt: datetime | None, now: datetime | None = None, date_only: bool = False) -> str:
    if dt is None:
        return "posted time unknown"
    now = now or datetime.now(timezone.utc)
    if date_only:
        days = (now.date() - dt.date()).days
        return "posted today" if days <= 0 else ("posted yesterday" if days == 1 else f"posted {days} d ago")
    mins = max(0, int((now - dt).total_seconds() // 60))
    if mins < 60:
        return f"posted {mins} min ago"
    if mins < 48 * 60:
        return f"posted {mins // 60} h ago"
    return f"posted {mins // 1440} d ago"
