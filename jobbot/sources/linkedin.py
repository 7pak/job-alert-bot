from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlencode

from ..http import Http
from ..models import Job
from ..text import html_to_text, parse_dt

log = logging.getLogger(__name__)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"

_ID = re.compile(r"urn:li:jobPosting:(\d+)")
_TITLE = re.compile(r'base-search-card__title[^>]*>(.*?)</h3>', re.S)
_COMPANY = re.compile(r'base-search-card__subtitle[^>]*>(.*?)</h4>', re.S)
_LOCATION = re.compile(r'job-search-card__location[^>]*>(.*?)</span>', re.S)
_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', re.S)
_DESC = re.compile(r'show-more-less-html__markup[^>]*>(.*?)</div>', re.S)
_AGO = re.compile(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", re.I)
_DESC_LOCATION = re.compile(r"(?:^|\n)\s*(?:job\s+)?location\s*[:\-]\s*([^\n]{2,60})", re.I)


def _clean(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip().replace("  ", " ")


def _ago_to_dt(text: str, fallback: datetime | None) -> datetime | None:
    m = _AGO.search(text or "")
    if not m:
        return fallback
    n, unit = int(m.group(1)), m.group(2).lower()
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n),
             "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
    return datetime.now(timezone.utc) - delta


class LinkedInSource:
    """LinkedIn public guest search. Fragile and rate limited, so:

    - one search query per run (round robin over `queries`),
    - detail pages only for jobs that pass the title check (the runner calls enrich),
    - a slow per-host rate, and the runner backs off for a long time on HTTP 429.
    """

    name = "linkedin"

    def __init__(self, queries: list[dict], http: Http, interval: float, time_window: str = "r86400",
                 min_interval: float = 8.0, city_fix: dict | None = None):
        self.queries = queries
        self.http = http
        self.interval = interval
        self.time_window = time_window
        self.min_interval = min_interval
        self._next = 0
        fix = city_fix or {}
        self._suspect = re.compile("|".join(map(re.escape, fix["suspect"])), re.I) if fix.get("suspect") else None
        self._cities = (re.compile(r"\b(?:" + "|".join(map(re.escape, fix["cities"])) + r")\b")
                        if fix.get("cities") else None)

    def fetch(self) -> Iterable[Job]:
        q = self.queries[self._next % len(self.queries)]
        self._next += 1
        params = {"keywords": q["keywords"], "location": q["location"], "f_TPR": self.time_window,
                  "sortBy": "DD", "start": 0}
        page = self.http.get_text(f"{SEARCH}?{urlencode(params)}", min_interval=self.min_interval)
        jobs = list(self.parse_search(page))
        log.info("linkedin '%s' in %s: %d cards", q["keywords"], q["location"], len(jobs))
        return jobs

    def parse_search(self, page: str) -> Iterable[Job]:
        for card in page.split("<li>")[1:]:
            m = _ID.search(card)
            title = _TITLE.search(card)
            if not m or not title:
                continue
            company = _COMPANY.search(card)
            location = _LOCATION.search(card)
            t = _TIME.search(card)
            posted = _ago_to_dt(_clean(t.group(2)), parse_dt(t.group(1))) if t else None
            job_id = m.group(1)
            yield Job(
                source=self.name,
                company=_clean(company.group(1)) if company else "Unknown",
                external_id=job_id,
                title=_clean(title.group(1)),
                url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                location=_clean(location.group(1)) if location else "",
                posted_at=posted,
                needs_detail=True,
            )

    def enrich(self, job: Job) -> None:
        page = self.http.get_text(DETAIL.format(id=job.external_id), min_interval=self.min_interval)
        m = _DESC.search(page)
        job.description = html_to_text(m.group(1)) if m else ""
        # LinkedIn often shows a wrong city. Trust "Location: X" in the description.
        loc = _DESC_LOCATION.search(job.description)
        if loc:
            job.location = loc.group(1).strip(" .")
        elif self._suspect and self._suspect.search(job.location) and self._cities:
            # A city LinkedIn shows by mistake (city_fix.suspect): use a real one named in the post.
            city = self._cities.search(job.description)
            if city:
                job.location = f"{city.group(0)} (LinkedIn said {job.location.split(',')[0].strip()})"
        job.needs_detail = False
