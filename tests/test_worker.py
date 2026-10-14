"""Dry runs: nothing written, old jobs explained, short grouped summary."""
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobbot.db import JobStore
from jobbot.models import Job, Verdict
from jobbot.worker import CycleStats, Item, Worker, group_reason
from tests.helpers import worker_cfg


class FakeNotifier:
    def __init__(self):
        self.alerts = []

    def send_alert(self, alert):
        self.alerts.append(alert)


def job(i=1, title="Flutter Engineer", hours=1, location="Dubai, United Arab Emirates"):
    return Job(source="t", company="Acme", external_id=str(i), title=title, url=f"https://x/{i}",
               location=location, description="Flutter and BLoC.",
               posted_at=datetime.now(timezone.utc) - timedelta(hours=hours))


class ReadOnlyStore(unittest.TestCase):
    def test_dry_run_creates_no_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "jobs.db"
            store = JobStore(path, read_only=True)
            self.assertIsNone(store.status("x"))
            store.conn.close()
            self.assertFalse(path.parent.exists())

    def test_existing_database_is_read_but_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.db"
            rw = JobStore(path)
            rw.record(job(), "alerted", Verdict(keep=True, score=4.0))
            rw.conn.close()
            ro = JobStore(path, read_only=True)
            self.assertEqual(ro.status(job().key), "alerted")
            with self.assertRaises(sqlite3.OperationalError):
                ro.set_setting("x", "1")
            ro.conn.close()


class OldJobs(unittest.TestCase):
    def setUp(self):
        self.store = JobStore(":memory:", read_only=True)

    def run_items(self, items, verbose=1, max_age=None):
        w = Worker(worker_cfg(), self.store, FakeNotifier(), [], max_age_hours=max_age)
        out, stats = io.StringIO(), CycleStats()
        with redirect_stdout(out):
            w.handle(items, stats, dry_run=True, verbose=verbose)
        return out.getvalue(), stats, w

    def test_old_job_shows_age_and_would_be_verdict(self):
        out, stats, _ = self.run_items([Item(job(hours=100), None, True)])
        self.assertEqual(stats.dropped, {"old": 1})
        self.assertIn("4 d old, would keep, score", out)

    def test_max_age_override(self):
        w = Worker(worker_cfg(), self.store, FakeNotifier(), [], max_age_hours=336)
        self.assertEqual(w.max_age, timedelta(hours=336))

    def test_not_relevant_only_with_vv(self):
        items = [Item(job(2, "Sales Manager"), "not a mobile, AI or software role", False)]
        self.assertNotIn("Sales Manager", self.run_items(items, verbose=1)[0])
        self.assertIn("Sales Manager", self.run_items(items, verbose=2)[0])


class Summary(unittest.TestCase):
    def test_group_reason(self):
        self.assertEqual(group_reason("on-site outside GCC (London)"), ("on-site outside GCC", "London"))
        self.assertEqual(group_reason("too senior (Lead)"), ("too senior", "Lead"))
        self.assertEqual(group_reason("7+ years required"), ("too many years required", "7+"))
        self.assertEqual(group_reason("remote limited to Remote, US")[0], "remote limited to")
        self.assertEqual(group_reason("not a backend role"), ("not a backend role", ""))

    def test_examples_capped_at_two(self):
        s = CycleStats()
        for city in ("London", "Paris", "Berlin", "London"):
            s.drop(f"on-site outside GCC ({city})")
        self.assertEqual(s.dropped, {"on-site outside GCC": 4})
        self.assertEqual(s.examples["on-site outside GCC"], ["London", "Paris"])


if __name__ == "__main__":
    unittest.main()
