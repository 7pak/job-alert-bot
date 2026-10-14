from __future__ import annotations

import hashlib
import logging
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import urlencode

from ..http import Http, RateLimited
from ..models import Job
from ..text import html_to_text

log = logging.getLogger(__name__)


class CareerjetSource:
    """Aggregator (covers boards we cannot fetch, like Bayt). Legacy public API.

    It needs a Referer header and may be retired without notice. Careerjet may ask for an
    affiliate id (free, from careerjet.com/partners), set it as `affiliate_id`. Descriptions are
    snippets, so hidden walls (years, nationality) are often not visible.
    """

    name = "careerjet"
    API = "http://public.api.careerjet.net/search"

    def __init__(self, queries: list[str], locales: list[str], http: Http, interval: float,
                 affiliate_id: str = ""):
        self.queries = queries
        self.affiliate_id = affiliate_id
        self.locales = locales
        self.http = http
        self.interval = interval
        self._broken_warned = False

    def enrich(self, job: Job) -> None:
        pass

    def fetch(self) -> Iterable[Job]:
        for locale in self.locales:
            for q in self.queries:
                params = {"locale_code": locale, "keywords": q, "sort": "date", "pagesize": 50,
                          "user_ip": "127.0.0.1", "user_agent": "Mozilla/5.0"}
                if self.affiliate_id:
                    params["affid"] = self.affiliate_id
                try:
                    data = self.http.get_json(f"{self.API}?{urlencode(params)}", min_interval=3.0,
                                              headers={"Referer": "http://www.example.com/jobs"})
                except RateLimited:
                    raise
                except Exception as exc:
                    log.warning("careerjet '%s' %s failed: %s", q, locale, exc)
                    continue
                if data.get("type") == "ERROR":
                    if not self._broken_warned:
                        log.warning("careerjet refused: %s", data.get("error"))
                        self._broken_warned = True
                    return
                for j in data.get("jobs", []):
                    yield self._job(j)

    def _job(self, j: dict) -> Job:
        key = "|".join(str(j.get(k, "")) for k in ("title", "company", "locations", "date"))
        try:
            posted = parsedate_to_datetime(j["date"]) if j.get("date") else None
        except (TypeError, ValueError):
            posted = None
        return Job(
            source=self.name,
            company=(j.get("company") or "Unknown").strip(),
            external_id=hashlib.sha1(key.encode()).hexdigest()[:16],
            title=html_to_text(j.get("title") or ""),
            url=j.get("url") or "",
            location=(j.get("locations") or "").strip(),
            description=html_to_text(j.get("description")),
            posted_at=posted,
            date_only=True,
            snippet_only=True,
        )
