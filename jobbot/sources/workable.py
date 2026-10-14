from __future__ import annotations

import logging
from typing import Iterable
from urllib.parse import urlencode

from ..http import NOT_MODIFIED, Http, RateLimited
from ..models import Job
from ..text import html_to_text, parse_dt
from . import BoardSource

log = logging.getLogger(__name__)


class WorkableAccountsSource(BoardSource):
    """Per company: https://apply.workable.com/api/v1/widget/accounts/{token}?details=true

    Many big names exist as empty placeholder accounts, so 0 jobs does not mean the token is wrong.
    """

    name = "workable"

    def list_jobs(self, company: dict) -> Iterable[Job]:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{company['token']}?details=true"
        data = self.http.get_json(url, cache=True, min_interval=1.0)
        if data is NOT_MODIFIED:
            return
        for j in data.get("jobs", []):
            locs = j.get("locations") or [{"city": j.get("city"), "country": j.get("country")}]
            location = "; ".join(", ".join(p for p in (loc.get("city"), loc.get("country")) if p) for loc in locs)
            if str(j.get("telecommuting")).lower() == "true":
                location = f"Remote, {location}" if location else "Remote"
            yield Job(
                source=self.name,
                company=self.company_name(company),
                external_id=j["shortcode"],
                title=(j.get("title") or "").strip(),
                url=j.get("url") or j.get("shortlink") or "",
                location=location,
                description=html_to_text(j.get("description")),
                posted_at=parse_dt(j.get("published_on") or j.get("created_at")),
                date_only=True,
            )


class WorkableSearchSource:
    """Cross-company search: https://jobs.workable.com/api/v1/jobs?query=...&location=...

    Finds Workable employers we have never heard of.
    """

    name = "workable_search"

    def __init__(self, queries: list[str], locations: list[str], http: Http, interval: float, pages: int = 2):
        self.queries = queries
        self.locations = locations
        self.http = http
        self.interval = interval
        self.pages = pages

    def enrich(self, job: Job) -> None:
        pass

    def fetch(self) -> Iterable[Job]:
        for location in self.locations:
            for query in self.queries:
                token = None
                for _ in range(self.pages):
                    params = {"query": query, "location": location}
                    if token:
                        params["pageToken"] = token
                    try:
                        data = self.http.get_json("https://jobs.workable.com/api/v1/jobs?" + urlencode(params), min_interval=2.0)
                    except RateLimited:
                        raise
                    except Exception as exc:
                        log.warning("workable search '%s' in %s failed: %s", query, location, exc)
                        break
                    for j in data.get("jobs", []):
                        yield self._job(j)
                    token = data.get("nextPageToken")
                    if not token:
                        break

    def _job(self, j: dict) -> Job:
        location = "; ".join(j.get("locations") or [])
        if not location:
            loc = j.get("location") or {}
            location = ", ".join(p for p in (loc.get("city"), loc.get("countryName")) if p)
        workplace = (j.get("workplace") or "").replace("_", "-")
        if workplace == "remote" and "remote" not in location.lower():
            location = f"Remote, {location}"
        parts = [f"Workplace: {workplace}", html_to_text(j.get("description")),
                 html_to_text(j.get("requirementsSection")), html_to_text(j.get("benefitsSection"))]
        return Job(
            source=self.name,
            company=((j.get("company") or {}).get("title") or "Unknown").strip(),
            external_id=j["id"],
            title=(j.get("title") or "").strip(),
            url=j.get("url") or "",
            location=location,
            description="\n".join(p for p in parts if p),
            posted_at=parse_dt(j.get("created")),
            language=j.get("language"),
        )
