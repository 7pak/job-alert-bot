from __future__ import annotations

from typing import Iterable

from ..models import Job
from ..text import html_to_text, parse_dt
from . import BoardSource

API = "https://api.smartrecruiters.com/v1/companies"


class SmartRecruitersSource(BoardSource):
    """List per country (e.g. countries: [ae, sa]), detail call for the description.

    Note: an unknown company returns 200 with zero jobs, not 404.
    """

    name = "smartrecruiters"

    def list_jobs(self, company: dict) -> Iterable[Job]:
        token = company["token"]
        for country in company.get("countries") or [None]:
            offset = 0
            while True:
                url = f"{API}/{token}/postings?limit=100&offset={offset}" + (f"&country={country}" if country else "")
                data = self.http.get_json(url, min_interval=0.5)
                content = data.get("content") or []
                for j in content:
                    loc = j.get("location") or {}
                    location = ", ".join(p for p in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if p)
                    if loc.get("remote"):
                        location = f"Remote, {location}"
                    yield Job(
                        source=self.name,
                        company=self.company_name(company),
                        external_id=str(j["id"]),
                        title=(j.get("name") or "").strip(),
                        url=f"https://jobs.smartrecruiters.com/{(j.get('company') or {}).get('identifier', token)}/{j['id']}",
                        location=location,
                        posted_at=parse_dt(j.get("releasedDate")),
                        language=((j.get("language") or {}).get("code")),
                        needs_detail=True,
                        meta={"ref": j.get("ref") or f"{API}/{token}/postings/{j['id']}", "hybrid": loc.get("hybrid")},
                    )
                offset += len(content)
                if not content or offset >= data.get("totalFound", 0):
                    break

    def enrich(self, job: Job) -> None:
        d = self.http.get_json(job.meta["ref"], min_interval=0.5)
        sections = ((d.get("jobAd") or {}).get("sections")) or {}
        parts = ["Workplace: hybrid" if job.meta.get("hybrid") else ""]
        for key in ("jobDescription", "qualifications", "additionalInformation"):
            parts.append(html_to_text((sections.get(key) or {}).get("text")))
        job.description = "\n".join(p for p in parts if p)
        job.url = d.get("postingUrl") or job.url
        job.needs_detail = False
