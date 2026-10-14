"""Load and check the user files: config.yml, profile.yml, companies.yml and .env.

Each one is gitignored and has a committed *.example.yml twin. A missing file falls back to its
example with a clear notice, so a fresh clone runs (`jobbot once --dry-run`) before any setup.
Set JOBBOT_HOME to keep these files outside the code folder.
"""
from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import load_dotenv

from . import schema
from .money import Money
from .profile import LEVELS, REMOTE_POLICIES, WORK_MODES, ProfileError, load_profile, merged_profile

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "poll_seconds": 180,
    "max_job_age_hours": 48,
    "alert_min_score": 3.0,
    "max_alerts_per_cycle": 15,
    "max_backoff_seconds": 4 * 3600,
    "request_timeout_seconds": 30,
    "db_path": "data/jobs.db",
    "profile_file": "profile.yml",
    "companies_file": "companies.yml",
    "log_level": "INFO",
    "healthcheck_url": "",
    "notifier": "telegram",
    "currency_rates": None,
    "sources": {},
    "ai": {
        "enabled": False,
        "provider": "gemini",
        "models": ["gemini-3.5-flash-lite"],
        "timeout_seconds": 25,
        "min_score": 3.5,
        "prefilter_min_score": 2.5,
        "max_calls_per_day": 200,
        "min_gap_seconds": 6,
        "max_desc_chars": 12000,
    },
    "tailoring": {
        "enabled": False,
        "provider": "claude",
        "model": "claude-haiku-5-5",
        "cv_file": "cv.md",
        "docx": False,
        "cover_letter": False,
        "max_per_day": 10,
        "max_cost_per_month_usd": 2.0,
        "price_per_mtok": {"input": 0.10, "output": 0.50},
        "allow_free_tier": False,
        "max_desc_chars": 15000,
    },
}

# Never poll faster than this (seconds). Faster gets your IP rate limited or banned.
MIN_INTERVALS = {
    "greenhouse": 60, "lever": 60, "ashby": 60, "workable": 120, "smartrecruiters": 120,
    "workable_search": 300, "himalayas": 300, "careerjet": 600, "linkedin": 600,
}
NOTIFIERS = ("telegram", "console")
TAILOR_PROVIDERS = ("claude", "gemini")


class ConfigError(Exception):
    """A config problem the user must fix. The message says where and how."""


@dataclass
class Loaded:
    path: Path
    data: dict
    example: bool = False                 # loaded from the *.example.yml fallback
    report: schema.Report = field(default_factory=schema.Report)


def home() -> Path:
    """Where the user files live: JOBBOT_HOME, else the project folder (or the current folder when
    the package was installed without the project files next to it)."""
    if os.environ.get("JOBBOT_HOME"):
        return Path(os.environ["JOBBOT_HOME"]).resolve()
    return ROOT if (ROOT / "presets").is_dir() else Path.cwd().resolve()


def project_dir() -> Path:
    """Where presets/ and the *.example.yml files are."""
    for d in (ROOT, home()):
        if (d / "presets").is_dir():
            return d
    raise ConfigError("presets/ folder not found. Run jobbot from a clone of the repository "
                      "(pip install -e .), or set JOBBOT_HOME to it.")


def _resolve(path: str | Path, base: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else base / p


def example_for(path: Path) -> Path:
    return path.with_name(f"{path.stem}.example{path.suffix}")


def not_a_folder(path: Path) -> None:
    """Docker turns a missing bind-mounted file into an empty folder. Say so clearly."""
    if path.is_dir():
        raise ConfigError(f"{path.name} is a folder, not a file. With Docker this happens when the file did not "
                          f"exist before `docker compose up`: delete the folder, create the file (jobbot init, or "
                          f"copy {example_for(path).name}), then start again.")


def read_user_file(path: Path, spec) -> Loaded:
    """Read a YAML file, falling back to its .example twin, and validate it against `spec`."""
    not_a_folder(path)
    example = False
    if not path.exists():
        alt = example_for(path)
        if not alt.exists():
            raise ConfigError(f"{path.name} not found. Run `jobbot init` to create it from the examples.")
        path, example = alt, True
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{path.name}:{mark.line + 1}" if mark else path.name
        raise ConfigError(f"{where}: not valid YAML ({getattr(exc, 'problem', exc)}). "
                          "Check the indentation and that lists use '- ' or [a, b].") from None
    loaded = Loaded(path, data, example)
    if spec is not None:
        schema.validate(data, spec, path.name, schema.yaml_lines(text), loaded.report)
    return loaded


def load_companies(path: Path) -> dict:
    """companies.yml: {greenhouse: [{name, token}], lever: [...], ...}. Entries with enabled: false are skipped."""
    not_a_folder(path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {ats: [c for c in (rows or []) if c.get("enabled", True)] for ats, rows in raw.items()}


def check_profile(prof: Loaded, presets: Path, rates: dict, report: schema.Report) -> None:
    name, lines = prof.path.name, schema.yaml_lines(prof.path.read_text(encoding="utf-8"))
    try:
        data = merged_profile(prof.data, presets)
    except (ProfileError, KeyError, TypeError) as exc:
        report.errors.append(f"{name}: {exc}")
        return
    for i, t in enumerate(prof.data.get("tracks") or []):
        if isinstance(t, dict):
            schema.validate(t, schema.TRACK_SPEC, name, lines, report, ("tracks", i))
    if not data["tracks"]:
        report.errors.append(f"{name}: no tracks. Add at least one, e.g. `tracks: [{{preset: backend}}]`.")
    for i, t in enumerate(data["tracks"]):
        bad = [lv for lv in t.get("levels") or [] if lv not in LEVELS]
        if bad:
            report.errors.append(f"{name}: tracks.{i}.levels: unknown level {bad}. Use {', '.join(LEVELS)}.")
        if not any(t.get(k) for k in ("title_any", "title_with_role")):
            report.errors.append(f"{name}: tracks.{i} ({t['name']}): needs title_any or title_with_role.")
    loc = data["locations"]
    if loc["remote"] not in REMOTE_POLICIES:
        report.errors.append(f"{name}: locations.remote must be one of {', '.join(REMOTE_POLICIES)}.")
    bad = [m for m in loc["work_modes"] if str(m).lower() not in WORK_MODES]
    if bad:
        report.errors.append(f"{name}: locations.work_modes: unknown {bad}. Use {', '.join(WORK_MODES)}.")
    if not loc["targets"] and loc["remote"] != "anywhere":
        report.warnings.append(f"{name}: locations.targets is empty, so only remote jobs can pass.")
    cur = str(data["salary"].get("currency") or "USD").upper()
    if cur not in {k.upper() for k in rates}:
        report.errors.append(f"{name}: salary.currency {cur} is not in currency_rates (config.yml).")
    if str(data["salary"].get("period") or "month") not in ("month", "year"):
        report.errors.append(f"{name}: salary.period must be month or year.")
    try:
        ZoneInfo(str(data.get("timezone") or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        report.errors.append(f"{name}:{lines.get(('timezone',), '?')}: timezone '{data.get('timezone')}' is not "
                             "an IANA name. Examples: Europe/Berlin, America/New_York, Asia/Dubai.")


def check_config(cfg: dict, report: schema.Report, fname: str) -> None:
    for src, c in (cfg.get("sources") or {}).items():
        if c is None:
            cfg["sources"][src] = c = {}
        floor = MIN_INTERVALS.get(src)
        iv = c.get("interval_seconds")
        if floor and iv is not None and iv < floor:
            report.warnings.append(f"{fname}: sources.{src}.interval_seconds {iv} is below the safe minimum "
                                   f"({floor}), using {floor}.")
            c["interval_seconds"] = floor
        needs = {"workable_search": ("queries", "locations"), "himalayas": ("queries",),
                 "careerjet": ("queries",), "linkedin": ("queries",)}.get(src, ())
        for key in needs:
            if c.get("enabled", True) and not c.get(key):
                report.errors.append(f"{fname}: sources.{src}.{key} is empty. Add some or set enabled: false.")
    if cfg["poll_seconds"] < 60:
        report.warnings.append(f"{fname}: poll_seconds is below 60, using 60.")
        cfg["poll_seconds"] = 60
    if cfg["notifier"] not in NOTIFIERS:
        report.errors.append(f"{fname}: notifier must be one of {', '.join(NOTIFIERS)}.")
    if cfg["ai"].get("provider", "gemini") != "gemini":
        report.errors.append(f"{fname}: ai.provider: only gemini is supported for scoring.")
    if cfg["tailoring"]["provider"] not in TAILOR_PROVIDERS:
        report.errors.append(f"{fname}: tailoring.provider must be one of {', '.join(TAILOR_PROVIDERS)}.")


def with_defaults(data: dict) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = {**cfg[k], **v}
        elif v is not None or k not in cfg:
            cfg[k] = v
    return cfg


def load_config(path: str | Path | None = None, strict: bool = True) -> dict:
    """Everything the bot needs, as one dict. strict=False keeps going and leaves problems in cfg['report']."""
    base = home()
    load_dotenv(base / ".env")
    conf = read_user_file(Path(path) if path else base / "config.yml", schema.CONFIG_SPEC)
    cfg = with_defaults(conf.data)
    report = conf.report
    notices = []
    if conf.example:
        notices.append(f"config.yml not found, using {conf.path.name}. Copy it to config.yml to make it yours "
                       "(or run `jobbot init`).")
    check_config(cfg, report, conf.path.name)

    money = Money(cfg["currency_rates"]) if cfg["currency_rates"] else Money()
    presets = project_dir() / "presets"
    prof = read_user_file(_resolve(cfg["profile_file"], base), schema.PROFILE_SPEC)
    if prof.example:
        notices.append(f"profile.yml not found, using {prof.path.name}. Copy it to profile.yml and edit it "
                       "(or run `jobbot init`).")
    report.errors += prof.report.errors
    report.warnings += prof.report.warnings
    check_profile(prof, presets, money.rates, report)

    companies_path = _resolve(cfg["companies_file"], base)
    if not companies_path.exists() and example_for(companies_path).exists():
        notices.append(f"{companies_path.name} not found, using {example_for(companies_path).name}.")
        companies_path = example_for(companies_path)

    if report.errors and strict:
        raise ConfigError("Config problems:\n  " + "\n  ".join(report.errors))

    cfg["home"] = str(base)
    cfg["config_path"] = str(conf.path)
    cfg["profile_path"] = str(prof.path)
    cfg["companies_path"] = str(companies_path)
    cfg["notices"] = notices
    cfg["report"] = report
    cfg["money"] = money
    cfg["db_path"] = str(_resolve(cfg["db_path"], base))
    cfg["companies"] = load_companies(companies_path)
    cfg["profile"] = None if report.errors else load_profile(prof.path, presets, raw=prof.data)
    cfg["timezone"] = cfg["profile"].timezone if cfg["profile"] else "UTC"
    cfg["tailoring"]["cv_path"] = str(_resolve(cfg["tailoring"]["cv_file"], base))
    cfg["telegram_token"] = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    cfg["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    cfg["gemini_api_key"] = os.getenv("GEMINI_API_KEY", "").strip()
    cfg["anthropic_api_key"] = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return cfg


def enabled_source(cfg: dict, name: str) -> dict | None:
    c = (cfg.get("sources") or {}).get(name)
    if c is None or c.get("enabled", True) is False:
        return None
    return c
