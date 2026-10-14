from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


class RateLimited(Exception):
    """The site said slow down (HTTP 429). The source runner backs off."""

    def __init__(self, url: str, retry_after: float | None = None):
        super().__init__(f"rate limited by {urlsplit(url).netloc}")
        self.retry_after = retry_after


NOT_MODIFIED = object()  # returned by get_json(cache=True) when the server says 304


class Http:
    """Shared by all source threads.

    - At most one request per `min_interval` seconds to any single host.
    - One requests.Session per thread.
    - 5xx is retried with backoff. 429 is raised as RateLimited right away,
      so the caller decides how long to back off.
    """

    def __init__(self, timeout: float = 30, retries: int = 2, min_interval: float = 1.0, etag_ttl: float = 1800):
        self.timeout = timeout
        self.retries = retries
        self.min_interval = min_interval
        self._local = threading.local()
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}
        # url -> (etag, saved_at). Entries expire so every board gets a full fetch now and then.
        self._etags: dict[str, tuple[str, float]] = {}
        self.etag_ttl = etag_ttl

    @property
    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers["User-Agent"] = BROWSER_UA
            s.headers["Accept-Language"] = "en-US,en;q=0.9"
            self._local.session = s
        return self._local.session

    def _wait_for_host(self, url: str, min_interval: float | None) -> None:
        host = urlsplit(url).netloc
        gap = self.min_interval if min_interval is None else min_interval
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + gap
        if slot > now:
            time.sleep(slot - now)

    def request(self, method: str, url: str, min_interval: float | None = None, **kwargs) -> requests.Response:
        delay = 5.0
        for attempt in range(self.retries + 1):
            self._wait_for_host(url, min_interval)
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After", "")
                raise RateLimited(url, float(ra) if ra.isdigit() else None)
            if resp.status_code >= 500 and attempt < self.retries:
                log.warning("HTTP %s from %s, retry in %.0fs", resp.status_code, urlsplit(url).netloc, delay)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 304:
                return resp
            resp.raise_for_status()
            return resp
        raise RuntimeError("unreachable")

    def get_json(self, url: str, cache: bool = False, **kwargs):
        """cache=True: send the last ETag; returns NOT_MODIFIED if the board did not change."""
        if not cache:
            return self.request("GET", url, **kwargs).json()
        with self._lock:
            etag, saved = self._etags.get(url, ("", 0.0))
        headers = dict(kwargs.pop("headers", None) or {})
        if etag and time.monotonic() - saved < self.etag_ttl:
            headers["If-None-Match"] = etag
        resp = self.request("GET", url, headers=headers, **kwargs)
        if resp.status_code == 304:
            return NOT_MODIFIED
        if resp.headers.get("ETag"):
            with self._lock:
                self._etags[url] = (resp.headers["ETag"], time.monotonic())
        return resp.json()

    def post_json(self, url: str, body: dict, **kwargs):
        return self.request("POST", url, json=body, **kwargs).json()

    def get_text(self, url: str, **kwargs) -> str:
        return self.request("GET", url, **kwargs).text
