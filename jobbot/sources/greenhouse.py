from __future__ import annotations

from typing import Iterable

from ..http import NOT_MODIFIED
from ..models import Job
from ..text import html_to_text, parse_dt
from . import BoardSource

API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseSource(BoardSource):
    """List: /v1/boards/{token}/jobs (no content, small). Detail per job only when needed."""

    name = "greenhouse"

    def list_jobs(self, company: dict) -> Iterable[Job]:
        token = company["token"]
        data = self.http.get_json(f"{API}/{token}/jobs", cache=True, min_interval=0.3)
        if data is NOT_MODIFIED:
            return
        for j in data.get("jobs", []):
            yield Job(
                source=self.name,
                company=self.company_name(company),
                external_id=str(j["id"]),
                title=(j.get("title") or "").strip(),
                url=j.get("absolute_url") or "",
                location=((j.get("location") or {}).get("name") or "").strip(),
                posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
                language=j.get("language"),
                needs_detail=True,
                meta={"token": token},
            )

    def enrich(self, job: Job) -> None:
        j = self.http.get_json(f"{API}/{job.meta['token']}/jobs/{job.external_id}", min_interval=0.3)
        job.description = html_to_text(j.get("content"))
        offices = [o.get("location") or o.get("name") for o in j.get("offices") or []]
        extra = [o for o in offices if o and o not in job.location]
        if extra:
            job.location = "; ".join([job.location, *extra]) if job.location else "; ".join(extra)
        job.needs_detail = False
