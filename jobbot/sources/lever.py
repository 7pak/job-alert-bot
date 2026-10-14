from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ..http import NOT_MODIFIED
from ..models import Job
from ..text import html_to_text
from . import BoardSource


class LeverSource(BoardSource):
    """https://api.lever.co/v0/postings/{token}?mode=json (set host: api.eu.lever.co for EU boards)."""

    name = "lever"

    def list_jobs(self, company: dict) -> Iterable[Job]:
        host = company.get("host", "api.lever.co")
        data = self.http.get_json(f"https://{host}/v0/postings/{company['token']}?mode=json", cache=True,
                                  min_interval=0.5)
        if data is NOT_MODIFIED or not isinstance(data, list):
            return
        for j in data:
            cats = j.get("categories") or {}
            locations = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
            location = "; ".join(locations)
            workplace = (j.get("workplaceType") or "").lower()
            if workplace == "remote" and "remote" not in location.lower():
                location = f"Remote, {location}" if location else "Remote"

            parts = [f"Workplace: {workplace}" if workplace else ""]
            parts.append(j.get("descriptionPlain") or html_to_text(j.get("description")))
            for lst in j.get("lists") or []:
                parts.append(lst.get("text", ""))
                parts.append(html_to_text(lst.get("content")))
            parts.append(j.get("additionalPlain") or html_to_text(j.get("additional")))
            sal = j.get("salaryRange") or {}
            if sal.get("min") or sal.get("max"):
                period = "per year" if "year" in (sal.get("interval") or "") else "per month"
                parts.append(f"Salary: {sal.get('currency', '')} {sal.get('min', '')} - {sal.get('max', '')} {period}")

            created = j.get("createdAt")
            yield Job(
                source=self.name,
                company=self.company_name(company),
                external_id=j["id"],
                title=(j.get("text") or "").strip(),
                url=j.get("hostedUrl") or "",
                location=location,
                description="\n".join(p for p in parts if p),
                posted_at=datetime.fromtimestamp(created / 1000, timezone.utc) if created else None,
            )
