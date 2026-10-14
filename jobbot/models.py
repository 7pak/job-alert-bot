from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime


def short_id(key: str) -> str:
    """12-char id for Telegram button data (callback_data is limited to 64 bytes)."""
    return hashlib.sha1(key.encode()).hexdigest()[:12]


_COMPANY_SUFFIX = re.compile(
    r"\b(?:l\.?l\.?c|fz-?llc|fze|fzco|fz|dmcc|ltd|limited|inc|corp|co|group|holding|holdings|technologies"
    r"|technology|tech|networks|middle east|me|uae|ksa|international)\b\.?"
)


@dataclass
class Job:
    source: str
    company: str
    external_id: str
    title: str
    url: str
    location: str = ""
    description: str = ""
    posted_at: datetime | None = None
    language: str | None = None
    date_only: bool = False      # source gives a day, not a time
    needs_detail: bool = False   # description not fetched yet (source.enrich fills it)
    snippet_only: bool = False   # description is a short excerpt (aggregators)
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company.lower()}:{self.external_id}"

    @property
    def fingerprint(self) -> str:
        """Same company + title from two sources (e.g. Greenhouse and LinkedIn) is one job."""
        company = _COMPANY_SUFFIX.sub(" ", self.company.lower())
        norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
        return f"{norm(company)}|{norm(self.title)}"


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    score: float = 0.0
    city: str = ""
    work_mode: str = ""
    positives: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    track: str = ""             # profile track that matched
    sponsored: str = ""         # sponsored place it passed for (locations.sponsored_targets), if any
    ai: object | None = None  # jobbot.ai.AiResult when the AI check ran


@dataclass
class Alert:
    """What a notifier needs. Channel-neutral, so other notifiers can be added."""
    job_key: str
    score: float
    title: str
    company: str
    url: str
    city: str
    work_mode: str
    posted_ago: str
    positives: list[str]
    warnings: list[str]
