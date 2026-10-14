"""Telegram control: button taps (Applied / Skip / undo / Tailor CV) and commands (/today /pause /resume /stats).

Runs in its own thread with long polling (getUpdates). Only your chat id is obeyed.
"""
from __future__ import annotations

import html
import logging
import threading
import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Callable
from zoneinfo import ZoneInfo

from ..db import JobStore
from . import score_dot
from .telegram import TelegramError, TelegramNotifier, keyboard

log = logging.getLogger(__name__)

COMMANDS = [
    ("today", "Today's matches"),
    ("pause", "Stop alerts (matches are still saved)"),
    ("resume", "Start alerts again"),
    ("stats", "Counts and source health"),
    ("help", "List commands"),
]
STATUS_MARK = {"alerted": "", "applied": " · ✅ applied", "skipped": " · ⏭ skipped", "muted": " · 🔕 while paused"}
ACTIONS = {"a": ("applied", "Marked as applied"), "s": ("skipped", "Skipped"), "u": ("alerted", "Undone")}


def as_tz(value: str | float | int | None) -> tzinfo:
    """An IANA name (Asia/Dubai) or, for old configs, a UTC offset in hours."""
    if value is None or value == "":
        return timezone.utc
    if isinstance(value, (int, float)):
        return timezone(timedelta(hours=value))
    return ZoneInfo(str(value))


class TelegramBot:
    def __init__(self, token: str, chat_id: str, store: JobStore, tz: str | float = "UTC",
                 source_status: Callable[[], list[str]] | None = None, tailor=None):
        self.api = TelegramNotifier(token, chat_id, timeout=70)  # own session: long polls block
        self.chat_id = str(chat_id)
        self.store = store
        self.tz = as_tz(tz)
        self.source_status = source_status or (lambda: [])
        self.tailor = tailor  # jobbot.tailor.Tailor, or None when tailoring is off
        self._stop = threading.Event()

    # ---- loop -------------------------------------------------------------------

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self._loop, name="telegram", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        try:
            self.api.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
        except Exception as exc:
            log.warning("setMyCommands failed: %s", exc)
        offset = int(self.store.get_setting("tg_offset", "0") or 0)
        backoff = 5.0
        while not self._stop.is_set():
            try:
                updates = self.api.call("getUpdates", offset=offset, timeout=50,
                                        allowed_updates=["message", "callback_query"])
                backoff = 5.0
            except TelegramError as exc:
                # 409 Conflict means another copy of the bot is polling (e.g. one on the PC, one on the server).
                log.warning("telegram getUpdates: %s (retry in %.0fs)", exc, backoff)
                self._stop.wait(backoff)
                backoff = min(300, backoff * 2)
                continue
            except Exception as exc:
                log.warning("telegram getUpdates failed: %s (retry in %.0fs)", exc, backoff)
                self._stop.wait(backoff)
                backoff = min(300, backoff * 2)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    self.handle_update(u)
                except Exception:
                    log.exception("telegram update failed")
            if updates:
                self.store.set_setting("tg_offset", str(offset))

    # ---- dispatch -----------------------------------------------------------------

    def handle_update(self, u: dict) -> None:
        if cq := u.get("callback_query"):
            if str(cq.get("message", {}).get("chat", {}).get("id")) != self.chat_id:
                return
            self.on_button(cq)
        elif msg := u.get("message"):
            if str(msg.get("chat", {}).get("id")) != self.chat_id:
                log.info("ignored message from chat %s", msg.get("chat", {}).get("id"))
                return
            text = (msg.get("text") or "").strip()
            if text.startswith("/"):
                cmd = text.split()[0][1:].split("@")[0].lower()
                log.info("command /%s", cmd)
                self.on_command(cmd)

    def on_button(self, cq: dict) -> None:
        action, _, cb_id = (cq.get("data") or "").partition(":")
        row = self.store.by_cb_id(cb_id)
        if row is None or (action not in ACTIONS and action != "t"):
            self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text="Job not found")
            return
        if action == "t":
            return self.on_tailor(cq, row)
        status, toast = ACTIONS[action]
        self.store.set_status(row["key"], status)
        self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text=toast)
        msg = cq.get("message") or {}
        try:
            self.api.call("editMessageReplyMarkup", chat_id=self.chat_id, message_id=msg["message_id"],
                          reply_markup=keyboard(row["url"], cb_id, status, self.tailor is not None))
        except TelegramError as exc:
            if "not modified" not in str(exc):
                raise
        log.info("%s: %s, %s", status, row["company"], row["title"])

    def on_tailor(self, cq: dict, row) -> None:
        if self.tailor is None:
            self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text="CV tailoring is off")
            return
        if reason := self.tailor.blocked_reason():
            self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text="Not available")
            self.send(html.escape(reason))
            return
        self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text="Tailoring your CV, about a minute")
        job = {k: row[k] for k in ("title", "company", "location", "url", "description")}
        threading.Thread(target=self._tailor_job, args=(job,), name="tailor", daemon=True).start()

    def _tailor_job(self, job: dict) -> None:
        from ..tailor import TailorError  # only loaded when tailoring is on

        try:
            result = self.tailor.run(job)
            for name, data in self.tailor.files(result, job):
                self.api.send_document(name, data)
        except TailorError as exc:
            self.send(f"✍️ Could not tailor the CV for {html.escape(job['title'])}: {html.escape(str(exc))}")
            return
        except Exception as exc:
            log.exception("tailoring failed")
            self.send(f"✍️ Tailoring failed: {html.escape(str(exc)[:200])}")
            return
        lines = [f"✍️ <b>Tailored CV</b> for {html.escape(job['title'])}, {html.escape(job['company'])}",
                 *[f"• {html.escape(c)}" for c in result.changes[:12]],
                 f"<i>{html.escape(result.model)}, about ${result.cost_usd:.3f}. Check every line before you "
                 "send it. Nothing was applied for you.</i>"]
        self.send("\n".join(lines))
        log.info("tailored CV for %s, %s ($%.4f)", job["company"], job["title"], result.cost_usd)

    def on_command(self, cmd: str) -> None:
        handler = {"today": self.cmd_today, "pause": self.cmd_pause, "resume": self.cmd_resume,
                   "stats": self.cmd_stats, "help": self.cmd_help, "start": self.cmd_help}.get(cmd)
        self.send(handler() if handler else "Unknown command. " + self.cmd_help())

    def send(self, text: str) -> None:
        # Telegram caps messages at 4096 chars; split on line breaks.
        chunk = ""
        for line in text.split("\n"):
            if len(chunk) + len(line) + 1 > 3900:
                self._send_one(chunk)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            self._send_one(chunk)

    def _send_one(self, text: str) -> None:
        self.api.call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML",
                      link_preview_options={"is_disabled": True})

    # ---- commands ---------------------------------------------------------------

    def _midnight(self) -> datetime:
        return datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)

    def cmd_today(self) -> str:
        rows = self.store.matches_since(self._midnight())
        if not rows:
            return "No matches yet today."
        counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("applied", "skipped")}
        lines = [f"<b>Today: {len(rows)} matches</b> ({counts['applied']} applied, {counts['skipped']} skipped)", ""]
        for r in rows[:40]:
            score = r["score"] or 0
            t = datetime.fromisoformat(r["alerted_at"]).astimezone(self.tz).strftime("%H:%M")
            lines.append(
                f"{score_dot(score)} {score:.1f}  <a href=\"{html.escape(r['url'], quote=True)}\">{html.escape(r['title'])}</a>, "
                f"{html.escape(r['company'])} · {t}{STATUS_MARK.get(r['status'], '')}"
            )
        if len(rows) > 40:
            lines.append(f"… and {len(rows) - 40} more")
        return "\n".join(lines)

    def cmd_pause(self) -> str:
        if self.store.paused:
            return "Already paused. /resume to start alerts again."
        self.store.set_setting("paused_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return "🔕 Alerts paused. I keep checking and saving matches; see them with /today. /resume to start again."

    def cmd_resume(self) -> str:
        paused_at = self.store.get_setting("paused_at")
        if not paused_at:
            return "Alerts are already on."
        self.store.set_setting("paused_at", None)
        missed = sum(1 for r in self.store.matches_since(datetime.fromisoformat(paused_at)) if r["status"] == "muted")
        tail = f" {missed} matches came in while paused, see /today." if missed else ""
        return "🔔 Alerts are back on." + tail

    def cmd_stats(self) -> str:
        today = self.store.match_counts_since(self._midnight())
        week = self.store.match_counts_since(self._midnight() - timedelta(days=6))
        totals = self.store.counts()

        def line(c: dict[str, int]) -> str:
            n = sum(c.values())
            return f"{n} matches · {c.get('applied', 0)} applied · {c.get('skipped', 0)} skipped"

        paused_at = self.store.get_setting("paused_at")
        state = "🔕 paused" if paused_at else "🔔 alerts on"
        lines = [
            "<b>Stats</b>",
            f"Today: {line(today)}",
            f"Last 7 days: {line(week)}",
            f"Jobs seen: {sum(totals.values()):,} ({totals.get('dropped', 0):,} filtered out)",
            f"State: {state}",
        ]
        if src := self.source_status():
            lines += ["", "<b>Sources</b>", *[html.escape(s) for s in src]]
        return "\n".join(lines)

    @staticmethod
    def cmd_help() -> str:
        return "Commands:\n" + "\n".join(f"/{c}  {d}" for c, d in COMMANDS)


def fmt_ago(ts: float | None) -> str:
    if not ts:
        return "never"
    mins = int((time.time() - ts) // 60)
    return "just now" if mins < 1 else (f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago")
