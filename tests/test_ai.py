import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import requests

from jobbot.ai import AiResult, GeminiScorer, parse_result
from jobbot.db import JobStore
from jobbot.models import Job
from jobbot.worker import CycleStats, Item, Worker
from tests.helpers import worker_cfg

CFG = worker_cfg()


def job(i=1, title="Flutter Engineer", desc="Flutter and BLoC. 2-4 years of experience."):
    return Job(source="t", company="Acme", external_id=str(i), title=title, url=f"https://x/{i}",
               location="Dubai, United Arab Emirates", description=desc, posted_at=datetime.now(timezone.utc))


class FakeScorer:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def score(self, job, verdict):
        self.calls += 1
        return self.result


class FakeNotifier:
    def __init__(self):
        self.alerts = []

    def send_alert(self, alert):
        self.alerts.append(alert)
        return "1"


def gemini_response(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


class WorkerAi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "t.db")
        self.notifier = FakeNotifier()

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def run_one(self, result, j=None):
        scorer = FakeScorer(result)
        w = Worker(CFG, self.store, self.notifier, [], scorer)
        j = j or job()
        w.handle([Item(j, None, False)], CycleStats())
        return j, scorer

    def test_hard_wall_dropped(self):
        j, _ = self.run_one(AiResult(score=1.5, hard_wall=True, wall_reason="Saudi nationals only"))
        self.assertEqual(self.store.status(j.key), "dropped")
        row = self.store.conn.execute("SELECT reason, ai_score FROM jobs WHERE key=?", (j.key,)).fetchone()
        self.assertIn("Saudi nationals only", row["reason"])
        self.assertEqual(row["ai_score"], 1.5)
        self.assertEqual(self.notifier.alerts, [])

    def test_low_ai_score_not_alerted(self):
        j, _ = self.run_one(AiResult(score=3.0, hard_wall=False))
        self.assertEqual(self.store.status(j.key), "low_score")

    def test_good_score_alerts_with_ai_details(self):
        j, _ = self.run_one(AiResult(score=4.4, hard_wall=False, positives=["Flutter + BLoC", "2-4 yrs"],
                                     warnings=["Swift is a plus"], work_mode="hybrid", raw="{}"))
        self.assertEqual(self.store.status(j.key), "alerted")
        a = self.notifier.alerts[0]
        self.assertEqual(a.score, 4.4)
        self.assertEqual(a.positives, ["Flutter + BLoC", "2-4 yrs"])
        self.assertEqual(a.warnings[0], "Swift is a plus")
        self.assertEqual(a.work_mode, "Hybrid")

    def test_ai_unavailable_falls_back_to_keywords(self):
        j, _ = self.run_one(None)
        self.assertEqual(self.store.status(j.key), "alerted")
        self.assertIn("AI check unavailable", self.notifier.alerts[0].warnings)

    def test_keyword_drop_skips_ai(self):
        j, scorer = self.run_one(AiResult(score=5, hard_wall=False), job(title="Sales Manager"))
        self.assertEqual(scorer.calls, 0)
        self.assertEqual(self.store.status(j.key), "dropped")


class Parse(unittest.TestCase):
    def test_parse(self):
        r = parse_result(gemini_response({"score": 4.2, "hard_wall": False, "wall_reason": "", "years_required": 3,
                                          "location": "Dubai", "work_mode": "hybrid",
                                          "positives": ["Flutter"], "warnings": []}))
        self.assertEqual((r.score, r.hard_wall, r.location), (4.2, False, "Dubai"))

    def test_wall_caps_score(self):
        r = parse_result(gemini_response({"score": 4.8, "hard_wall": True, "wall_reason": "German required"}))
        self.assertLessEqual(r.score, 2.0)

    def test_code_fence(self):
        data = {"candidates": [{"content": {"parts": [{"text": '```json\n{"score": 3, "hard_wall": false}\n```'}]}}]}
        self.assertEqual(parse_result(data).score, 3.0)


class FakeHttp:
    """First call: 400 (schema rejected). Second call: success. Records bodies."""

    def __init__(self):
        self.bodies = []

    def post_json(self, url, body, **kw):
        self.bodies.append(body)
        if len(self.bodies) == 1:
            resp = requests.Response()
            resp.status_code = 400
            resp._content = b'{"error": "bad schema"}'
            raise requests.HTTPError("400", response=resp)
        return gemini_response({"score": 4, "hard_wall": False})


class SchemaFallback(unittest.TestCase):
    def test_retries_without_schema(self):
        http = FakeHttp()
        s = GeminiScorer("key", http, "m")
        from jobbot.models import Verdict
        r = s.score(job(), Verdict(keep=True))
        self.assertEqual(r.score, 4.0)
        self.assertIn("responseSchema", http.bodies[0]["generationConfig"])
        self.assertNotIn("responseSchema", http.bodies[1]["generationConfig"])

    def test_daily_cap(self):
        s = GeminiScorer("key", FakeHttp(), "m", max_calls_per_day=0)
        from jobbot.models import Verdict
        self.assertIsNone(s.score(job(), Verdict(keep=True)))


if __name__ == "__main__":
    unittest.main()
