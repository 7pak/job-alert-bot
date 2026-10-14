from __future__ import annotations

from ..models import Alert
from . import score_dot


class ConsoleNotifier:
    """Prints alerts instead of sending them. Used for --dry-run and when no token is set."""

    def send_text(self, text: str) -> str | None:
        print(text)
        return None

    def send_alert(self, a: Alert) -> str | None:
        place = " · ".join(p for p in (a.city, a.work_mode, a.posted_ago) if p)
        print(f"\n{score_dot(a.score)} {a.score:.1f}/5  {a.title}, {a.company}")
        print(f"📍 {place}")
        if a.positives:
            print("✅ " + ", ".join(a.positives))
        for w in a.warnings[:3]:
            print("⚠️ " + w)
        print(f"🔗 {a.url}")
        return None
