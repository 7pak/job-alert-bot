"""CV tailoring: off means no button and no CV access; on means guarded, capped and delivered as documents."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jobbot.db import JobStore
from jobbot.models import Job, Verdict, short_id
from jobbot.notify.telegram import TelegramNotifier, keyboard
from jobbot.notify.telegram_bot import TelegramBot
from jobbot.tailor import GeminiModel, Tailor, TailorError, build_tailor, parse_answer, start_tailor

CHAT = "111"
ANSWER = """=== CHANGES ===
- Moved Flutter projects to the top
- Reworded the summary for fintech
GAPS:
- Kubernetes
=== CV ===
# Sam Example
## Experience
- Built a **Flutter** app
=== COVER LETTER ===
Dear team, ...
"""


class FakeModel:
    name = "fake-model"

    def __init__(self, cost=0.01, may_train=False):
        self.cost = cost
        self.may_train_on_data = may_train
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        assert "Truth rules" in system and "CV (Markdown)" in user
        return ANSWER, self.cost


class FakeApi:
    def __init__(self):
        self.calls, self.documents = [], []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {"message_id": 1}

    def send_document(self, name, data, caption=""):
        self.documents.append((name, data))

    def sent(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def job(i=1):
    return Job(source="t", company="Acme", external_id=str(i), title="Flutter Engineer", url=f"https://x/{i}",
               location="Dubai", description="We need Flutter and Kotlin.", posted_at=datetime.now(timezone.utc))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def tailor(self, model=None, **cfg):
        conf = {"max_per_day": 10, "max_cost_per_month_usd": 2.0, "cover_letter": False, **cfg}
        return Tailor(conf, model or FakeModel(), "# Sam Example\n- Built a Flutter app", self.store)


class Disabled(Base):
    def test_no_button_and_no_cv_read(self):
        self.assertNotIn("t:", str(keyboard("https://x", "abc", "alerted")))
        self.assertFalse(TelegramNotifier("tok", CHAT).tailor_button)
        cfg = {"tailoring": {"enabled": False, "cv_path": str(Path(self.tmp.name) / "missing.md")}}
        self.assertIsNone(build_tailor(cfg, self.store))  # a missing CV is never even looked at

    def test_setup_error_never_stops_the_bot(self):
        cfg = {"db_path": str(Path(self.tmp.name) / "jobs.db"), "anthropic_api_key": "", "gemini_api_key": "",
               "tailoring": {"enabled": True, "provider": "gemini", "model": "m",
                             "cv_path": str(Path(self.tmp.name) / "cv.docx")}}
        with self.assertLogs("jobbot.tailor", level="ERROR") as logs:
            self.assertIsNone(start_tailor(cfg, self.store))
        self.assertIn("CV tailoring is OFF", logs.output[0])

    def test_button_when_enabled(self):
        self.assertIn("t:abc", str(keyboard("https://x", "abc", "applied", tailor=True)))

    def test_tap_when_off(self):
        bot = TelegramBot("tok", CHAT, self.store)
        bot.api = FakeApi()
        self.store.record(job(), "alerted", Verdict(keep=True, score=4.0))
        bot.handle_update({"update_id": 1, "callback_query": {
            "id": "cq", "data": f"t:{short_id(job().key)}", "message": {"message_id": 5, "chat": {"id": int(CHAT)}}}})
        answer = [p for m, p in bot.api.calls if m == "answerCallbackQuery"][-1]
        self.assertEqual(answer["text"], "CV tailoring is off")


class Guards(Base):
    def test_free_tier_refused_without_override(self):
        t = self.tailor(FakeModel(may_train=True))
        self.assertIn("free tier", t.blocked_reason())
        with self.assertRaises(TailorError):
            t.run({"title": "x", "description": "y"})
        self.assertIsNone(self.tailor(FakeModel(may_train=True), allow_free_tier=True).blocked_reason())

    def test_gemini_counts_as_free_tier(self):
        self.assertTrue(GeminiModel("key", "gemini-x", 0, 0).may_train_on_data)

    def test_daily_cap(self):
        model = FakeModel()
        t = self.tailor(model, max_per_day=1)
        t.run({"title": "x", "description": "y"})
        with self.assertRaises(TailorError) as ctx:
            t.run({"title": "x", "description": "y"})
        self.assertIn("Daily", str(ctx.exception))
        self.assertEqual(model.calls, 1)

    def test_monthly_cost_cap(self):
        t = self.tailor(FakeModel(cost=1.5), max_cost_per_month_usd=1.0)
        t.run({"title": "x", "description": "y"})
        self.assertIn("Monthly", t.blocked_reason())

    def test_no_saved_job_text(self):
        with self.assertRaises(TailorError):
            self.tailor().run({"title": "x", "description": ""})

    def test_answer_without_cv(self):
        with self.assertRaises(TailorError):
            parse_answer("=== CHANGES ===\n- nothing\n")


class Flow(Base):
    def test_documents_and_changes_sent(self):
        bot = TelegramBot("tok", CHAT, self.store, tailor=self.tailor(cover_letter=True))
        bot.api = FakeApi()
        j = job()
        self.store.record(j, "alerted", Verdict(keep=True, score=4.0))
        row = self.store.by_cb_id(short_id(j.key))
        self.assertEqual(row["description"], "We need Flutter and Kotlin.")  # saved for matches
        bot._tailor_job({k: row[k] for k in ("title", "company", "location", "url", "description")})
        names = [n for n, _ in bot.api.documents]
        self.assertEqual(names, ["CV - Acme - Flutter-Engineer.md", "Cover letter - Acme.md"])
        self.assertIn(b"Built a **Flutter** app", bot.api.documents[0][1])
        text = bot.api.sent()[-1]
        self.assertIn("Moved Flutter projects to the top", text)
        self.assertIn("Nothing was applied for you", text)

    def test_dropped_jobs_do_not_keep_text(self):
        j = job(2)
        self.store.record(j, "dropped", Verdict(keep=False, reason="x"))
        self.assertIsNone(self.store.by_cb_id(short_id(j.key))["description"])


if __name__ == "__main__":
    unittest.main()
