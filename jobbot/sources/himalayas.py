from __future__ import annotations

import ast
import logging
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlencode

from ..http import Http, RateLimited
from ..models import Job
from ..text import html_to_text

log = logging.getLogger(__name__)


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return []
    return []


class HimalayasSource:
    """Remote jobs open to a country: https://himalayas.app/jobs/api/search?q=...&country=AE&sort=recent"""

    name = "himalayas"

    def __init__(self, queries: list[str], country: str, http: Http, interval: float):
        self.queries = queries
        self.country = country
        self.http = http
        self.interval = interval

    def enrich(self, job: Job) -> None:
        pass

    def fetch(self) -> Iterable[Job]:
        for q in self.queries:
            url = "https://himalayas.app/jobs/api/search?" + urlencode({"q": q, "country": self.country, "sort": "recent"})
            try:
                data = self.http.get_json(url, min_interval=2.0)
            except RateLimited:
                raise
            except Exception as exc:
                log.warning("himalayas '%s' failed: %s", q, exc)
                continue
            for j in data.get("jobs", []):
                yield self._job(j)

    def _job(self, j: dict) -> Job:
        regions = _as_list(j.get("locationRestrictions"))
        location = "Remote, " + (", ".join(map(str, regions)) if regions else "Worldwide")
        parts = [html_to_text(j.get("description"))]
        if j.get("minSalary") or j.get("maxSalary"):
            period = {"hourly": "per hour", "monthly": "per month"}.get(j.get("salaryPeriod") or "", "per year")
            parts.append(f"Salary: {j.get('currency') or 'USD'} {j.get('minSalary') or ''} - {j.get('maxSalary') or ''} {period}")
        pub = j.get("pubDate")
        return Job(
            source=self.name,
            company=(j.get("companyName") or "Unknown").strip(),
            external_id=j.get("guid") or j.get("applicationLink"),
            title=(j.get("title") or "").strip(),
            url=j.get("applicationLink") or j.get("guid") or "",
            location=location,
            description="\n".join(p for p in parts if p),
            posted_at=datetime.fromtimestamp(int(pub), timezone.utc) if pub else None,
        )
