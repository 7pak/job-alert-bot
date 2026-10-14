"""The send step. Everything else talks to `Notifier`, so Telegram can be replaced by FCM later."""
from __future__ import annotations

from typing import Protocol

from ..models import Alert


class Notifier(Protocol):
    def send_text(self, text: str) -> str | None:
        """Send a plain message. Returns a message id if the channel has one."""
        ...

    def send_alert(self, alert: Alert) -> str | None:
        """Send one job alert. Raise on failure so the job is retried next cycle."""
        ...


def score_dot(score: float) -> str:
    return "🟢" if score >= 4.0 else ("🟡" if score >= 3.0 else "🔴")
