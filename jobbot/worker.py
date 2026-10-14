from __future__ import annotations

import logging
import queue
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests

from .ai import CallCounter, GeminiScorer, Scorer, build_system_prompt
from .config import enabled_source
from .db import JobStore
from .filters import JobFilter
from .http import Http, RateLimited
from .models import Alert, Job, Verdict
from .notify import Notifier
from .notify.telegram_bot import fmt_ago
from .sources import Source
from .sources.ashby import AshbySource
from .sources.careerjet import CareerjetSource
from .sources.greenhouse import GreenhouseSource
from .sources.himalayas import HimalayasSource
from .sources.lever import LeverSource
from .sources.linkedin import LinkedInSource
from .sources.smartrecruiters import SmartRecruitersSource
from .sources.workable import WorkableAccountsSource, WorkableSearchSource
from .text import time_ago

log = logging.getLogger(__name__)

BOARD_SOURCES = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "workable": WorkableAccountsSource,
    "smartrecruiters": SmartRecruitersSource,
}
HEALTHCHECK_EVERY = 300  # seconds between pings at most


def build_sources(cfg: dict, companies: dict, http: Http, only: set[str] | None = None) -> list[Source]:
    """`companies` maps ATS name -> list of {name, token, ...} (from companies.yml)."""
    out: list[Source] = []

    def enabled(name: str) -> dict | None:
        c = enabled_source(cfg, name)
        return None if c is None or (only and name not in only) else c

    for name, cls in BOARD_SOURCES.items():
        c = enabled(name)
        if c is not None and companies.get(name):
            out.append(cls(companies[name], http, c.get("interval_seconds", cfg["poll_seconds"]), c.get("workers", 6)))
    if (c := enabled("workable_search")) is not None:
        out.append(WorkableSearchSource(c["queries"], c["locations"], http, c.get("interval_seconds", 1200),
                                        c.get("pages", 2)))
    if (c := enabled("himalayas")) is not None:
        out.append(HimalayasSource(c["queries"], c.get("country", ""), http, c.get("interval_seconds", 1800)))
    if (c := enabled("careerjet")) is not None:
        out.append(CareerjetSource(c["queries"], c.get("locales", ["en_GB"]), http, c.get("interval_seconds", 2700),
                                   c.get("affiliate_id") or ""))
    if (c := enabled("linkedin")) is not None:
        out.append(LinkedInSource(c["queries"], http, c.get("interval_seconds", 900),
                                  c.get("time_window", "r86400"), c.get("min_request_gap_seconds", 8),
                                  c.get("city_fix")))
    return out


def to_alert(job: Job, v: Verdict) -> Alert:
    return Alert(
        job_key=job.key, score=v.score, title=job.title, company=job.company, url=job.url,
        city=v.city or job.location,
        work_mode="" if (v.city or "").lower() == v.work_mode.lower() else v.work_mode,
        posted_ago=time_ago(job.posted_at, date_only=job.date_only),
        positives=v.positives, warnings=v.warnings,
    )


@dataclass
class Item:
    job: Job
    precheck: str | None  # drop reason from the title check, or None
    too_old: bool


@dataclass
class CycleStats:
    fetched: int = 0
    new: int = 0
    alerted: int = 0
    dropped: dict[str, int] = field(default_factory=dict)       # reason group -> count
    examples: dict[str, list[str]] = field(default_factory=dict)  # reason group -> up to 2 examples

    def drop(self, reason: str) -> None:
        group, example = group_reason(reason)
        self.dropped[group] = self.dropped.get(group, 0) + 1
        seen = self.examples.setdefault(group, [])
        if example and example not in seen and len(seen) < 2:
            seen.append(example)


def _short(text: str, limit: int = 40) -> str:
    """Cut a long example at a word boundary: 'Prague, Czechia; El Segundo, ...'."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;-")
    return f"{cut} ..."


STATUS_LABELS = {"low_score": "score under alert_min_score", "duplicate": "already alerted"}


def group_reason(reason: str) -> tuple[str, str]:
    """'on-site outside GCC (London)' -> ('on-site outside GCC', 'London'), for a short summary."""
    if reason in STATUS_LABELS:
        return STATUS_LABELS[reason], ""
    if reason.startswith("AI: "):
        return "AI hard wall", reason[4:60]
    if m := re.match(r"(remote limited to) (.+)", reason):
        return m.group(1), _short(m.group(2))
    if m := re.match(r"salary about (.+)", reason):
        return "salary below your floor", m.group(1)
    if m := re.match(r"(\d+)\+ years required", reason):
        return "too many years required", f"{m.group(1)}+"
    if m := re.match(r"(.+?) \((.+)\)$", reason):
        return m.group(1), _short(m.group(2))
    return reason, ""


def age_text(job: Job, now: datetime) -> str:
    if job.posted_at is None:
        return "age unknown"
    hours = (now - job.posted_at).total_seconds() / 3600
    return f"{hours:.0f} h old" if hours < 48 else f"{hours / 24:.0f} d old"


def build_scorer(cfg: dict, http: Http, store: JobStore | None) -> Scorer | None:
    """store=None counts AI calls in memory only (dry runs write nothing)."""
    ai = cfg.get("ai") or {}
    if not ai.get("enabled") or not cfg.get("gemini_api_key"):
        return None
    kwargs = {k: ai[k] for k in ("max_desc_chars", "min_gap_seconds", "max_calls_per_day") if k in ai}
    models = ai.get("models") or [ai["model"]]
    # Own client: no slow 5xx retries (the scorer moves to the next model instead), shorter timeout.
    ai_http = Http(timeout=ai.get("timeout_seconds", 25), retries=0)
    return GeminiScorer(cfg["gemini_api_key"], ai_http, models, system=build_system_prompt(cfg["profile"]),
                        calls_today=CallCounter(store), **kwargs)


class Worker:
    def __init__(self, cfg: dict, store: JobStore, notifier: Notifier, sources: list[Source],
                 scorer: Scorer | None = None, max_age_hours: float | None = None):
        self.cfg = cfg
        self.store = store
        self.notifier = notifier
        self.sources = sources
        self.scorer = scorer
        ai = cfg.get("ai") or {}
        self.ai_min = ai.get("min_score", 3.5)
        self.ai_prefilter = ai.get("prefilter_min_score", 2.5)
        self.filter = JobFilter(cfg["profile"], cfg.get("money"))
        self.max_age = timedelta(hours=max_age_hours or cfg["max_job_age_hours"])
        self.healthcheck_url = cfg.get("healthcheck_url") or ""
        self._last_ping = 0.0
        self._enrich_failures: dict[str, int] = {}
        self._queue: queue.Queue[tuple[str, list[Item]]] = queue.Queue()
        self._stop = threading.Event()
        # name -> {"ok": ts of last good run, "error": text, "retry_at": ts while backing off}
        self.health: dict[str, dict] = {s.name: {} for s in sources}

    # ---- source side (runs in source threads) --------------------------------

    def collect(self, source: Source, ignore_seen: bool = False, stats: CycleStats | None = None) -> Iterable[Item]:
        now = datetime.now(timezone.utc)
        seen_this_run: set[str] = set()  # search sources return the same job for several queries
        for job in source.fetch():
            if stats:
                stats.fetched += 1
            if job.key in seen_this_run:
                continue
            seen_this_run.add(job.key)
            if not ignore_seen and self.store.status(job.key) not in (None, "alert_failed"):
                continue
            reason = self.filter.precheck(job.title, job.company)
            too_old = bool(job.posted_at and now - job.posted_at > self.max_age)
            if reason is None and not too_old and job.needs_detail:
                try:
                    source.enrich(job)
                except RateLimited:
                    raise
                except Exception as exc:
                    n = self._enrich_failures[job.key] = self._enrich_failures.get(job.key, 0) + 1
                    log.warning("%s detail failed for %s (%d/3): %s", source.name, job.title, n, exc)
                    if n < 3:
                        continue  # retry next run
                    reason = f"detail fetch failed: {exc}"[:120]
            yield Item(job, reason, too_old)

    # ---- main thread: filter, store, alert --------------------------------------

    def handle(self, items: Iterable[Item], stats: CycleStats, dry_run: bool = False, verbose: int = 0) -> None:
        """verbose: 1 lists dropped jobs and why (old ones with the verdict they would get),
        2 also lists jobs that are not one of your roles at all."""
        now = datetime.now(timezone.utc)
        for it in items:
            job = it.job
            stats.new += 1
            if it.precheck:
                v, status = Verdict(keep=False, reason=it.precheck), "dropped"
            elif it.too_old:
                v, status = Verdict(keep=False), "old"
            else:
                v = self.filter.evaluate(job)
                if not v.keep:
                    status = "dropped"
                elif self.store.already_alerted(job):
                    status = "duplicate"
                elif self.scorer is not None and v.score >= self.ai_prefilter:
                    status = self._ai_check(job, v)
                elif v.score < self.cfg["alert_min_score"]:
                    status = "low_score"
                else:
                    status = "alert"

            if status != "alert":
                label = v.reason if status == "dropped" else status
                stats.drop(label)
                if verbose and (verbose > 1 or status != "dropped" or label != self.filter.not_relevant):
                    print(f"  - {status:<9} [{job.source}] {job.company}: {job.title} [{job.location}] "
                          f"{self._old_verdict(job, now) if status == 'old' else v.reason}")
                if not dry_run:
                    self.store.record(job, status, v)
                continue

            if not dry_run and self.store.paused:
                self.store.record(job, "muted", v)  # shown in /today
                continue
            if stats.alerted >= self.cfg["max_alerts_per_cycle"]:
                continue  # flood guard: left unrecorded, picked up next run
            if dry_run:
                self.notifier.send_alert(to_alert(job, v))
                stats.alerted += 1
                continue
            try:
                msg_id = self.notifier.send_alert(to_alert(job, v))
                self.store.record(job, "alerted", v, msg_id)
                stats.alerted += 1
                log.info("alerted %.1f [%s] %s: %s", v.score, job.source, job.company, job.title)
            except Exception as exc:
                log.error("alert failed for %s: %s", job.key, exc)
                self.store.record(job, "alert_failed", v)

    def _old_verdict(self, job: Job, now: datetime) -> str:
        """For -v: what the filter would say about a job that is too old to alert."""
        v = self.filter.evaluate(job)
        partial = " (title and snippet only)" if job.needs_detail or job.snippet_only else ""
        verdict = f"would keep, score {v.score:.1f}" if v.keep else f"would drop: {v.reason}"
        return f"{age_text(job, now)}, {verdict}{partial}"

    def _ai_check(self, job: Job, v: Verdict) -> str:
        """Let the AI read the full post. Returns dropped / low_score / alert."""
        res = self.scorer.score(job, v)
        if res is None:  # quota or error: never lose a job because of the AI
            v.warnings.insert(0, "AI check unavailable")
            return "alert" if v.score >= self.cfg["alert_min_score"] else "low_score"
        v.ai = res
        v.score = res.score
        if res.hard_wall:
            v.keep = False
            v.reason = f"AI: {res.wall_reason or 'hard wall'}"[:160]
            return "dropped"
        if res.positives:
            v.positives = res.positives
        v.warnings = list(dict.fromkeys([*res.warnings, *v.warnings]))
        if res.work_mode in ("on-site", "hybrid", "remote"):
            v.work_mode = res.work_mode.capitalize()
        if res.location and (job.source in ("linkedin", "careerjet") or not v.city):
            v.city = res.location[:40]
        return "alert" if res.score >= self.ai_min else "low_score"

    # ---- one-shot (CLI `once`) ----------------------------------------------------

    def run_cycle(self, dry_run: bool = False, ignore_seen: bool = False, verbose: int = 0) -> CycleStats:
        stats = CycleStats()
        for source in self.sources:
            try:
                items = list(self.collect(source, ignore_seen, stats))
            except RateLimited as exc:
                log.warning("%s: %s, skipped this run", source.name, exc)
                continue
            self.handle(items, stats, dry_run, verbose)
        return stats

    # ---- long-running (CLI `run`) -------------------------------------------------

    def _source_loop(self, source: Source) -> None:
        max_backoff = self.cfg.get("max_backoff_seconds", 4 * 3600)
        # A 429 backoff survives restarts, so a restart does not hit a rate-limited site again right away.
        key = f"backoff:{source.name}"
        saved = (self.store.get_setting(key) or "").split("|")
        backoff = float(saved[1]) if len(saved) == 2 else 0.0
        if len(saved) == 2 and float(saved[0]) > time.time():
            remaining = float(saved[0]) - time.time()
            log.info("%s: still backing off from before restart, %.0f min left", source.name, remaining / 60)
            self.health[source.name].update(error="rate limited", retry_at=float(saved[0]))
            if self._stop.wait(remaining):
                return
        while not self._stop.is_set():
            started = time.monotonic()
            health = self.health[source.name]
            try:
                items = list(self.collect(source))
                self._queue.put((source.name, items))
                if backoff:
                    self.store.set_setting(key, None)
                backoff = 0.0
                wait = source.interval
                health.update(ok=time.time(), error=None, retry_at=None)
            except RateLimited as exc:
                backoff = min(max_backoff, max(exc.retry_after or 0, backoff * 2 or source.interval * 3))
                log.warning("%s: %s, backing off %.0f min", source.name, exc, backoff / 60)
                wait = backoff
                health.update(error="rate limited", retry_at=time.time() + backoff)
                self.store.set_setting(key, f"{time.time() + backoff}|{backoff}")
            except Exception as exc:
                log.exception("%s crashed, retrying next run", source.name)
                wait = source.interval
                health.update(error=str(exc)[:80], retry_at=None)
            # jitter so requests do not land on exact intervals
            wait = max(10.0, wait * random.uniform(0.9, 1.1) - (time.monotonic() - started))
            self._stop.wait(wait)

    def source_status(self) -> list[str]:
        """One line per source for /stats."""
        lines = []
        if isinstance(self.scorer, GeminiScorer):
            lines.append(f"🤖 AI ({self.scorer.last_model or self.scorer.model}): {self.scorer.counter.today()} calls today")
        for name, h in self.health.items():
            if h.get("retry_at"):
                mins = max(0, int((h["retry_at"] - time.time()) // 60))
                lines.append(f"⏳ {name}: {h['error']}, retry in {mins} min")
            elif h.get("error"):
                lines.append(f"⚠️ {name}: {h['error']}")
            elif h.get("ok"):
                lines.append(f"✓ {name}: {fmt_ago(h['ok'])}")
            else:
                lines.append(f"… {name}: starting")
        return lines

    def ping_healthcheck(self) -> None:
        """Tell an uptime monitor (e.g. healthchecks.io) that a source run went fine."""
        if not self.healthcheck_url or time.monotonic() - self._last_ping < HEALTHCHECK_EVERY:
            return
        self._last_ping = time.monotonic()
        try:
            requests.get(self.healthcheck_url, timeout=10)
        except requests.RequestException as exc:
            log.warning("healthcheck ping failed: %s", exc)

    def run_forever(self, bot=None) -> None:
        if bot is not None:
            bot.source_status = self.source_status
            bot.start()
        for i, source in enumerate(self.sources):
            t = threading.Thread(target=self._delayed_start, args=(source, i * 5), name=source.name, daemon=True)
            t.start()
        log.info("worker started: %s", ", ".join(f"{s.name} every {s.interval / 60:.0f} min" for s in self.sources))
        try:
            while True:
                try:
                    name, items = self._queue.get(timeout=1)
                except queue.Empty:
                    continue
                stats = CycleStats()
                self.handle(items, stats)
                if stats.new:
                    log.info("%s: new=%d alerted=%d", name, stats.new, stats.alerted)
                self.ping_healthcheck()
        finally:
            self._stop.set()

    def _delayed_start(self, source: Source, delay: float) -> None:
        if not self._stop.wait(delay):
            self._source_loop(source)
