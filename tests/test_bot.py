import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jobbot.db import JobStore
from jobbot.models import Job, Verdict, short_id
from jobbot.notify.telegram_bot import TelegramBot
from jobbot.worker import CycleStats, Item, Worker
from tests.helpers import worker_cfg

CHAT = "111"


class FakeApi:
    def __init__(self):
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {"message_id": 1}

    def sent(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


class FakeNotifier:
    def __init__(self):
        self.alerts = []

    def send_alert(self, alert):
        self.alerts.append(alert)
        return "99"

    def send_text(self, text):
        return None


def job(i=1, title="Flutter Engineer"):
    return Job(source="t", company="Acme", external_id=str(i), title=title, url=f"https://x/{i}",
               location="Dubai, United Arab Emirates", description="Flutter and BLoC.",
               posted_at=datetime.now(timezone.utc))


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "t.db")
        self.bot = TelegramBot("token", CHAT, self.store)
        self.bot.api = FakeApi()

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def tap(self, action, j):
        self.bot.handle_update({"update_id": 1, "callback_query": {
            "id": "cq", "data": f"{action}:{short_id(j.key)}",
            "message": {"message_id": 5, "chat": {"id": int(CHAT)}}}})

    def command(self, text, chat=CHAT):
        self.bot.handle_update({"update_id": 1, "message": {"chat": {"id": int(chat)}, "text": text}})

    def test_applied_skip_undo(self):
        j = job()
        self.store.record(j, "alerted", Verdict(keep=True, score=4.2))
        self.tap("a", j)
        self.assertEqual(self.store.status(j.key), "applied")
        markup = [p for m, p in self.bot.api.calls if m == "editMessageReplyMarkup"][-1]["reply_markup"]
        self.assertIn("Applied · undo", str(markup))
        self.tap("u", j)
        self.assertEqual(self.store.status(j.key), "alerted")
        self.tap("s", j)
        self.assertEqual(self.store.status(j.key), "skipped")

    def test_unknown_job(self):
        self.tap("a", job(42))
        answer = [p for m, p in self.bot.api.calls if m == "answerCallbackQuery"][-1]
        self.assertEqual(answer["text"], "Job not found")

    def test_today_lists_matches_not_dropped(self):
        self.store.record(job(1), "alerted", Verdict(keep=True, score=4.2))
        self.store.record(job(2, "Android Developer"), "applied", Verdict(keep=True, score=3.8))
        self.store.record(job(3, "Sales Manager"), "dropped", Verdict(keep=False, reason="x"))
        self.command("/today")
        text = self.bot.api.sent()[-1]
        self.assertIn("Flutter Engineer", text)
        self.assertNotIn("Sales Manager", text)

    def test_today_counts_applied(self):
        j = job()
        self.store.record(j, "alerted", Verdict(keep=True, score=4.2))
        self.tap("a", j)
        self.command("/today")
        self.assertIn("1 applied", self.bot.api.sent()[-1])

    def test_pause_mutes_and_resume_reports(self):
        self.command("/pause")
        self.assertTrue(self.store.paused)
        cfg = worker_cfg()
        notifier = FakeNotifier()
        w = Worker(cfg, self.store, notifier, [])
        w.handle([Item(job(7), None, False)], CycleStats())
        self.assertEqual(notifier.alerts, [])
        self.assertEqual(self.store.status(job(7).key), "muted")
        self.command("/today")
        self.assertIn("while paused", self.bot.api.sent()[-1])
        self.command("/resume")
        self.assertFalse(self.store.paused)
        self.assertIn("1 matches came in while paused", self.bot.api.sent()[-1])
        w.handle([Item(job(8, "Android Engineer"), None, False)], CycleStats())
        self.assertEqual(len(notifier.alerts), 1)

    def test_stats(self):
        self.store.record(job(1), "alerted", Verdict(keep=True, score=4.2))
        self.bot.source_status = lambda: ["✓ greenhouse: just now"]
        self.command("/stats")
        text = self.bot.api.sent()[-1]
        self.assertIn("Today: 1 matches", text)
        self.assertIn("greenhouse", text)

    def test_other_chat_ignored(self):
        self.command("/pause", chat="999")
        self.assertFalse(self.store.paused)
        self.assertEqual(self.bot.api.sent(), [])

    def test_command_with_bot_suffix(self):
        self.command("/stats@example_job_alert_bot")
        self.assertIn("Stats", self.bot.api.sent()[-1])


if __name__ == "__main__":
    unittest.main()
