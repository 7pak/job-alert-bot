from __future__ import annotations

from typing import Iterable

from ..http import NOT_MODIFIED
from ..models import Job
from ..text import html_to_text, parse_dt
from . import BoardSource


class AshbySource(BoardSource):
    """https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"""

    name = "ashby"

    def list_jobs(self, company: dict) -> Iterable[Job]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company['token']}?includeCompensation=true"
        data = self.http.get_json(url, cache=True, min_interval=0.5)
        if data is NOT_MODIFIED:
            return
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
            country = (((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry")) or ""
            location = "; ".join(loc for loc in locs if loc)
            if country and country.lower() not in location.lower():
                location = f"{location}, {country}" if location else country
            if j.get("isRemote") and "remote" not in location.lower():
                location = f"Remote, {location}" if location else "Remote"

            comp = j.get("compensation") or {}
            summary = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary")
            parts = [
                f"Workplace: {j.get('workplaceType') or ''}",
                j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                f"Salary: {summary}" if summary else "",
            ]
            yield Job(
                source=self.name,
                company=self.company_name(company),
                external_id=j["id"],
                title=(j.get("title") or "").strip(),
                url=j.get("jobUrl") or "",
                location=location,
                description="\n".join(p for p in parts if p),
                posted_at=parse_dt(j.get("publishedAt")),
            )
