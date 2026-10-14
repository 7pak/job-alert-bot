from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Protocol

import requests

from ..http import Http, RateLimited
from ..models import Job

log = logging.getLogger(__name__)


class Source(Protocol):
    name: str
    interval: float  # seconds between fetches

    def fetch(self) -> Iterable[Job]:
        """Yield every job currently listed. A failing company must not stop the rest."""
        ...

    def enrich(self, job: Job) -> None:
        """Fill in the description for a job with needs_detail=True."""
        ...


class BoardSource:
    """A source that polls one ATS board per company (Greenhouse, Lever, ...)."""

    name = ""

    def __init__(self, companies: list[dict], http: Http, interval: float, workers: int = 6):
        self.companies = companies
        self.http = http
        self.interval = interval
        self.workers = workers
        self._dead: set[str] = set()

    def list_jobs(self, company: dict) -> Iterable[Job]:
        raise NotImplementedError

    def enrich(self, job: Job) -> None:
        pass

    def fetch(self) -> Iterable[Job]:
        """Several boards at once (the Http per-host gap still spaces out request starts)."""
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix=self.name) as pool:
            futures = [pool.submit(self._list_safely, c) for c in self.companies]
            for fut in as_completed(futures):
                yield from fut.result()

    def _list_safely(self, company: dict) -> list[Job]:
        token = company["token"]
        try:
            jobs = list(self.list_jobs(company))
        except RateLimited:
            raise
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status == 404:
                if token not in self._dead:  # warn once, keep retrying quietly
                    log.warning("%s board '%s' not found (404). Token may be stale.", self.name, token)
                    self._dead.add(token)
            else:
                log.warning("%s %s: HTTP %s", self.name, token, status)
            return []
        except Exception as exc:
            log.warning("%s %s failed: %s", self.name, token, exc)
            return []
        self._dead.discard(token)
        return jobs

    @staticmethod
    def company_name(company: dict) -> str:
        return company.get("name") or company["token"]
