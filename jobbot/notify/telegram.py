from __future__ import annotations

import html
import logging
import time

import requests

from ..models import Alert, short_id
from . import score_dot

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


def format_alert(a: Alert) -> str:
    e = html.escape
    place = " · ".join(p for p in (a.city, a.work_mode, a.posted_ago) if p)
    lines = [
        f"{score_dot(a.score)} <b>{a.score:.1f}/5</b>  <b>{e(a.title)}</b>, {e(a.company)}",
        f"📍 {e(place)}",
    ]
    if a.positives:
        lines.append("✅ " + e(", ".join(a.positives)))
    for w in a.warnings[:3]:
        lines.append("⚠️ " + e(w))
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout: float = 20, tailor_button: bool = False):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = chat_id
        self.timeout = timeout
        self.tailor_button = tailor_button
        self.session = requests.Session()

    def call(self, method: str, files: dict | None = None, **payload) -> dict:
        for attempt in range(3):
            if files:  # multipart upload (sendDocument)
                resp = self.session.post(self.base + method, data=payload, files=files, timeout=self.timeout + 60)
            else:
                resp = self.session.post(self.base + method, json=payload, timeout=self.timeout)
            data = resp.json()
            if data.get("ok"):
                return data["result"]
            retry = (data.get("parameters") or {}).get("retry_after")
            if resp.status_code == 429 and retry and attempt < 2:
                log.warning("telegram rate limit, waiting %ss", retry)
                time.sleep(retry)
                continue
            raise TelegramError(f"{method}: {data.get('description', resp.status_code)}")
        raise TelegramError(f"{method}: rate limited")

    def send_text(self, text: str) -> str | None:
        msg = self.call("sendMessage", chat_id=self.chat_id, text=text)
        return str(msg["message_id"])

    def send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        self.call("sendDocument", files={"document": (filename, content)}, chat_id=self.chat_id,
                  caption=caption[:1000])

    def send_alert(self, alert: Alert) -> str | None:
        msg = self.call(
            "sendMessage",
            chat_id=self.chat_id,
            text=format_alert(alert),
            parse_mode="HTML",
            link_preview_options={"is_disabled": True},
            reply_markup=keyboard(alert.url, short_id(alert.job_key), "alerted", self.tailor_button),
        )
        return str(msg["message_id"])


def keyboard(url: str, cb_id: str, status: str, tailor: bool = False) -> dict:
    """[Open job] [Applied] [Skip], plus [✍️ Tailor CV] when tailoring is on.
    After a tap, the pressed state shows with an undo."""
    open_btn = {"text": "Open job", "url": url}
    if status == "applied":
        row = [open_btn, {"text": "✅ Applied · undo", "callback_data": f"u:{cb_id}"}]
    elif status == "skipped":
        row = [open_btn, {"text": "⏭ Skipped · undo", "callback_data": f"u:{cb_id}"}]
    else:
        row = [open_btn, {"text": "Applied", "callback_data": f"a:{cb_id}"},
               {"text": "Skip", "callback_data": f"s:{cb_id}"}]
    rows = [row]
    if tailor:
        rows.append([{"text": "✍️ Tailor CV", "callback_data": f"t:{cb_id}"}])
    return {"inline_keyboard": rows}
