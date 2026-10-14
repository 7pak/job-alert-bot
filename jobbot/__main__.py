"""
Usage (also as `python -m jobbot ...`):
  jobbot init                 create config.yml, profile.yml, companies.yml and .env from the examples
  jobbot check-config         validate every file and show what will run
  jobbot chat-id              print your Telegram chat id (message the bot first)
  jobbot test-telegram        send a test message
  jobbot test-alert           send a sample job alert
  jobbot once --dry-run       one cycle, print alerts, write nothing
  jobbot once                 one cycle, send alerts, save to SQLite
  jobbot run                  poll forever
  jobbot stats                job counts by status
  jobbot ai-models            list the Gemini models your key can use
  jobbot ai-prompt            print what the AI scorer is told about you
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .db import JobStore
from .http import Http
from .models import Alert
from .notify.console import ConsoleNotifier
from .notify.telegram import TelegramNotifier


def make_notifier(cfg: dict, dry_run: bool):
    if dry_run or cfg["notifier"] == "console":
        return ConsoleNotifier()
    if not cfg["telegram_token"] or not cfg["telegram_chat_id"]:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env (or use --dry-run).")
    return TelegramNotifier(cfg["telegram_token"], cfg["telegram_chat_id"],
                            tailor_button=bool(cfg["tailoring"].get("enabled")))


def cmd_chat_id(cfg: dict) -> None:
    if not cfg["telegram_token"]:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env first.")
    updates = TelegramNotifier(cfg["telegram_token"], "").call("getUpdates")
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "") for u in updates if "message" in u}
    if not chats:
        print("No messages yet. Open your bot in Telegram, send it /start, then run this again.")
    for chat_id, name in chats.items():
        print(f"{chat_id}  {name}")


def cmd_ai_models(cfg: dict) -> None:
    if not cfg["gemini_api_key"]:
        sys.exit("Set GEMINI_API_KEY in .env first.")
    data = Http().get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                           headers={"x-goog-api-key": cfg["gemini_api_key"]})
    for m in data.get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            print(f"{m['name'].removeprefix('models/'):<40} {m.get('displayName', '')}")


def sample_alert() -> Alert:
    return Alert(job_key="sample:acme:1", score=4.3, title="Backend Engineer (sample alert)", company="Acme",
                 url="https://example.com/jobs/1", city="Berlin", work_mode="Hybrid", posted_ago="posted 12 min ago",
                 positives=["Python", "PostgreSQL", "2-4 yrs", "~70k EUR/yr"], warnings=["Sample only, not a real job"])


def print_summary(s, max_age: float, override: float | None) -> None:
    print(f"\nfetched={s.fetched} new={s.new} alerts={s.alerted}")
    for group, n in sorted(s.dropped.items(), key=lambda kv: -kv[1]):
        ex = s.examples.get(group) or []
        print(f"  {n:>5}  {group}" + (f"  (e.g. {' | '.join(ex)})" if ex else ""))
    old = s.dropped.get("old", 0)
    if not s.alerted and old and not override:
        print(f"\nNo alerts: {old} jobs that passed the title check were older than max_job_age_hours "
              f"({max_age:g} h). To test your filters on them: jobbot once --dry-run -v --max-age-hours 336")



# ---- check-config ------------------------------------------------------------------------


def cmd_check_config(path: str | None) -> int:
    try:
        cfg = load_config(path, strict=False)
    except ConfigError as exc:
        print(f"✗ {exc}")
        return 1
    rep = cfg["report"]
    for n in cfg["notices"]:
        print(f"ℹ {n}")
    for w in rep.warnings:
        print(f"⚠ {w}")
    for e in rep.errors:
        print(f"✗ {e}")
    if rep.errors:
        print(f"\n{len(rep.errors)} problem(s) to fix. Reference: docs/configuration.md")
        return 1
    p = cfg["profile"]
    print(f"\nProfile '{p.data['name']}' ({Path(cfg['profile_path']).name})")
    for t in p.tracks:
        print(f"  track {t.name:<12} levels: {', '.join(t.levels)}" + ("  (fallback)" if t.fallback else ""))
    names = [t.name for t in p.targets] or ["none"]
    print(f"  locations: {', '.join(names)} · remote: {p.remote_policy} · work modes: {', '.join(p.work_modes)}")
    print(f"  languages: {', '.join(s['name'] for s in p.spoken)} · max years: {p.max_years} · "
          f"salary floor: {p.salary_min:,.0f} {p.salary_currency}/{p.salary_period} · timezone: {p.timezone}")

    from .worker import build_sources
    sources = build_sources(cfg, cfg["companies"], Http())
    print(f"\nSources ({len(sources)} enabled, companies from {Path(cfg['companies_path']).name}):")
    for s in sources:
        boards = f", {len(s.companies)} boards" if hasattr(s, "companies") else ""
        print(f"  {s.name:<16} every {s.interval / 60:.0f} min{boards}")
    if not sources:
        print("  none. Enable some under `sources:` in config.yml.")

    secret = lambda v: "set" if v else "missing"  # never print the values
    print(f"\nSecrets (.env): TELEGRAM_BOT_TOKEN {secret(cfg['telegram_token'])}, "
          f"TELEGRAM_CHAT_ID {secret(cfg['telegram_chat_id'])}, GEMINI_API_KEY {secret(cfg['gemini_api_key'])}")
    ai = cfg["ai"]
    if ai.get("enabled"):
        state = "on" if cfg["gemini_api_key"] else "enabled but GEMINI_API_KEY is missing (keyword score only)"
        print(f"AI scoring: {state}, models {', '.join(ai.get('models') or [])}")
    else:
        print("AI scoring: off")
    t = cfg["tailoring"]
    if t.get("enabled"):
        cv = Path(t["cv_path"])
        key = cfg["anthropic_api_key"] if t["provider"] == "claude" else cfg["gemini_api_key"]
        problems = [] if cv.exists() else [f"{cv.name} not found"]
        if not key:
            problems.append("ANTHROPIC_API_KEY missing" if t["provider"] == "claude" else "GEMINI_API_KEY missing")
        if t["provider"] == "gemini" and not t.get("allow_free_tier"):
            problems.append("gemini needs allow_free_tier: true (privacy guard)")
        print(f"CV tailoring: on ({t['provider']} {t['model']})" + (f", problems: {'; '.join(problems)}" if problems else ""))
    else:
        print("CV tailoring: off")
    if cfg["healthcheck_url"]:
        print("Health check ping: on")
    print("\n✓ Config OK")
    return 0


# ---- main ----------------------------------------------------------------------------------


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # emoji on the Windows console

    p = argparse.ArgumentParser(prog="jobbot", description="Instant job alerts on Telegram. Never applies for you.")
    p.add_argument("--config", help="path to config.yml (default: config.yml in JOBBOT_HOME or the project)")
    sub = p.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="create your config files from the examples")
    init.add_argument("--track", action="append", metavar="PRESET",
                      help="role preset (repeatable or comma separated), e.g. --track backend --track data")
    init.add_argument("--region", help="region pack (gcc, dach, uk, us) or none")
    init.add_argument("--timezone", help="IANA timezone, e.g. America/New_York")
    init.add_argument("--force", action="store_true", help="replace files that already exist")
    init.add_argument("-y", "--yes", action="store_true", help="no questions, use the example's settings")
    sub.add_parser("check-config", help="validate config.yml, profile.yml and companies.yml")
    sub.add_parser("chat-id", help="print your Telegram chat id")
    sub.add_parser("test-telegram", help="send a test message")
    sub.add_parser("test-alert", help="send a sample job alert")
    once = sub.add_parser("once", help="one polling cycle")
    once.add_argument("--dry-run", action="store_true", help="print alerts, do not send or save")
    once.add_argument("--ignore-seen", action="store_true", help="re-check jobs already in the database")
    once.add_argument("-v", "--verbose", action="count", default=0,
                      help="list dropped jobs and why (old ones with the verdict they would get); "
                           "-vv also lists jobs that are not one of your roles")
    once.add_argument("--max-age-hours", type=float, metavar="H",
                      help="with --dry-run: treat jobs up to H hours old as new, to test your filters "
                           "on real jobs (e.g. 336 = two weeks)")
    once.add_argument("--source", action="append", help="only this source (repeatable), e.g. --source lever")
    once.add_argument("--no-ai", action="store_true", help="skip the AI check")
    sub.add_parser("ai-models", help="list Gemini models your key can use")
    sub.add_parser("ai-prompt", help="print the exact instructions the AI scorer gets (built from profile.yml)")
    sub.add_parser("run", help="poll forever")
    sub.add_parser("stats", help="job counts by status")
    args = p.parse_args()

    if args.cmd == "init":
        from .setup import init
        tracks = [t for arg in args.track for t in arg.split(",")] if args.track else None
        sys.exit(init(tracks, args.region, args.timezone, force=args.force, yes=args.yes))
    if args.cmd == "check-config":
        sys.exit(cmd_check_config(args.config))

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        sys.exit(f"{exc}\nRun `jobbot check-config` for details.")
    logging.basicConfig(level=cfg["log_level"], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("jobbot")
    for n in cfg["notices"]:
        log.warning(n)
    for w in cfg["report"].warnings:
        log.warning(w)

    if args.cmd == "chat-id":
        return cmd_chat_id(cfg)
    if args.cmd == "test-telegram":
        make_notifier(cfg, dry_run=False).send_text("✅ job-alert-bot is connected. Alerts will arrive here.")
        print("Test message sent.")
        return
    if args.cmd == "test-alert":
        make_notifier(cfg, dry_run=False).send_alert(sample_alert())
        print("Sample alert sent.")
        return
    if args.cmd == "ai-models":
        return cmd_ai_models(cfg)
    if args.cmd == "ai-prompt":
        from .ai import build_system_prompt
        print(build_system_prompt(cfg["profile"]))
        return

    from .worker import Worker, build_scorer, build_sources

    dry_run = getattr(args, "dry_run", False)
    if getattr(args, "max_age_hours", None) and not dry_run:
        sys.exit("--max-age-hours only works with --dry-run (it would otherwise alert old jobs).")
    store = JobStore(cfg["db_path"], read_only=dry_run or args.cmd == "stats")
    if args.cmd == "stats":
        for status, n in sorted(store.counts().items()):
            print(f"{status:<13} {n}")
        return

    only = set(args.source) if getattr(args, "source", None) else None
    http = Http(timeout=cfg["request_timeout_seconds"])
    sources = build_sources(cfg, cfg["companies"], http, only)
    if not sources:
        log.warning("no sources enabled (check `sources:` in config.yml and companies.yml)")
    scorer = None if getattr(args, "no_ai", False) else build_scorer(cfg, http, None if dry_run else store)
    if scorer is None and (cfg.get("ai") or {}).get("enabled") and not getattr(args, "no_ai", False):
        log.warning("AI scoring is enabled in config.yml but GEMINI_API_KEY is not set; using the keyword score")
    worker = Worker(cfg, store, make_notifier(cfg, dry_run), sources, scorer,
                    max_age_hours=getattr(args, "max_age_hours", None))
    if args.cmd == "once":
        s = worker.run_cycle(dry_run=dry_run, ignore_seen=args.ignore_seen, verbose=args.verbose)
        print_summary(s, cfg["max_job_age_hours"], args.max_age_hours)
    elif args.cmd == "run":
        bot = None
        if cfg["notifier"] == "telegram":
            from .notify.telegram_bot import TelegramBot
            from .tailor import start_tailor

            tailor = start_tailor(cfg, store)
            bot = TelegramBot(cfg["telegram_token"], cfg["telegram_chat_id"], store, cfg["timezone"], tailor=tailor)
        try:
            worker.run_forever(bot)
        except KeyboardInterrupt:
            print("stopped")


if __name__ == "__main__":
    main()
