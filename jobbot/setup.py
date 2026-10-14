"""`jobbot init`: create the user files from the examples, set up for a role, region and timezone.

Defaults come from the example files. The search sources in config.yml (queries, locations,
country) are filled in from the chosen track presets and region pack. Existing files are kept
unless --force is given.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .config import example_for, home, project_dir

FILES = ("config.yml", "profile.yml", "companies.yml", ".env")


@dataclass
class Choice:
    tracks: list[str]
    region: str | None
    timezone: str
    notes: list[str] = field(default_factory=list)


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def available(kind: str) -> list[str]:
    return sorted(p.stem for p in (project_dir() / "presets" / kind).glob("*.yml"))


def example_defaults() -> Choice:
    ex = _yaml(project_dir() / "profile.example.yml")
    tracks = [t["preset"] if isinstance(t, dict) else str(t) for t in ex.get("tracks") or []]
    return Choice(tracks=[t for t in tracks if t], region=ex.get("region"), timezone=ex.get("timezone") or "UTC")


def _region_search(region: str | None) -> dict:
    if not region:
        return {}
    return _yaml(project_dir() / "presets" / "regions" / f"{region}.yml").get("search") or {}


def _ask(question: str, default: str) -> str:
    try:
        answer = input(f"{question} [{default}]: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def resolve(tracks: list[str] | None, region: str | None, timezone: str | None, interactive: bool) -> Choice:
    """Combine flags, answers and the example defaults. Raises ValueError on unknown names."""
    ex = example_defaults()
    have_tracks, have_regions = available("tracks"), available("regions")
    if interactive and tracks is None:
        print(f"\nRole presets: {', '.join(have_tracks)}")
        tracks = _ask("Which roles do you want (comma separated)", ",".join(ex.tracks)).split(",")
    if interactive and region is None:
        region = _ask(f"Region pack ({', '.join(have_regions)}), or none", ex.region or "none")
    tracks = [t.strip() for t in (tracks or ex.tracks) if t.strip()]
    region = ex.region if region is None else (None if region.lower() == "none" else region)
    unknown = [t for t in tracks if t not in have_tracks]
    if unknown:
        raise ValueError(f"unknown track preset {', '.join(unknown)}. Available: {', '.join(have_tracks)}")
    if region and region not in have_regions:
        raise ValueError(f"unknown region pack {region}. Available: {', '.join(have_regions)}")

    suggested = (_region_search(region).get("timezone") if region != ex.region else None) or ex.timezone
    if interactive and timezone is None:
        timezone = _ask("Your timezone (IANA name, e.g. Europe/Berlin, America/New_York, Asia/Dubai)", suggested)
    timezone = timezone or suggested
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"timezone {timezone} is not an IANA name (e.g. Europe/Berlin)") from None
    return Choice(tracks, region, timezone)


# ---- rewriting the example text (keeps its comments) ------------------------------------


def _sub(text: str, pattern: str, repl: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if not n:
        raise RuntimeError(f"example file changed, cannot find {pattern!r}")
    return new


def _flow(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def profile_text(text: str, c: Choice) -> str:
    ex = example_defaults()
    label = f"{' + '.join(c.tracks)}" + (f" in {c.region.upper()}" if c.region else "")
    text = _sub(text, r"^name: .*?(?=\s+#|$)", f"name: {label}")
    text = _sub(text, r"^timezone: \S+", f"timezone: {c.timezone}")
    text = _sub(text, r"^#? ?region: .*$", f"region: {c.region}" if c.region else "# region: none")
    tracks = "".join(f"  - preset: {t}\n" for t in c.tracks)
    text = _sub(text, r"^tracks:\n(?:  .*\n)+", "tracks:\n" + tracks)
    if c.region != ex.region:
        # The example's home, languages and salary belong to its own region: reset them.
        pack = _yaml(project_dir() / "presets" / "regions" / f"{c.region}.yml") if c.region else {}
        sal = pack.get("salary") or {}
        text = _sub(text, r"^  home: .*$", '  home: ""                      # your city')
        text = _sub(text, r"^  home_country: .*$", '  home_country: ""')
        text = _sub(text, r"^languages:\n(?:  - .*\n)+", "languages:\n  - {name: english, level: fluent}\n")
        text = _sub(text, r"^  min: .*$", "  min: 0                         # your floor, 0 = none")
        text = _sub(text, r"^  currency: \S+", f"  currency: {sal.get('currency', 'USD')}")
        text = _sub(text, r"^  period: \S+", f"  period: {sal.get('period', 'year')}")
        c.notes.append("profile.yml: set your home, languages and salary floor.")
    return text


def _set_in_block(text: str, block: str, key: str, value: str) -> str:
    """Replace `key:` (and an indented list under it) inside `  block:` of config.yml."""
    m = re.search(rf"^  {re.escape(block)}:\n((?:    .*\n|\s*\n)*)", text, flags=re.M)
    if not m:
        raise RuntimeError(f"example config changed, no {block} block")
    body = m.group(1)
    line = f"    {key}:{value}" if value.startswith("\n") else f"    {key}: {value}"
    new_body, n = re.subn(rf"^    {key}:.*\n(?:      .*\n)*", lambda _: line + "\n", body, count=1, flags=re.M)
    if not n:
        raise RuntimeError(f"example config changed, no {block}.{key}")
    return text[: m.start(1)] + new_body + text[m.end(1):]


def config_text(text: str, c: Choice) -> str:
    queries: list[str] = []
    for t in c.tracks:
        for q in _yaml(project_dir() / "presets" / "tracks" / f"{t}.yml").get("search_queries") or []:
            if q not in queries:
                queries.append(q)
    queries = queries[:6] or ["software engineer"]
    s = _region_search(c.region)
    if s.get("locations"):
        text = _set_in_block(text, "workable_search", "locations", _flow(s["locations"]))
    text = _set_in_block(text, "workable_search", "queries", _flow(queries))
    if s.get("country"):
        text = _set_in_block(text, "himalayas", "country", s["country"])
    text = _set_in_block(text, "himalayas", "queries", _flow(queries))
    if s.get("careerjet_locale"):
        text = _set_in_block(text, "careerjet", "locales", _flow([s["careerjet_locale"]]))
    text = _set_in_block(text, "careerjet", "queries", _flow(queries))
    li = s.get("linkedin_location") or "Worldwide"
    lines = "".join(f"\n      - {{ keywords: {q}, location: {li} }}" for q in queries[:3])
    text = _set_in_block(text, "linkedin", "queries", lines)
    if not c.region:
        c.notes.append("config.yml: no region chosen, set workable_search.locations and himalayas.country.")
    return text


def init(tracks: list[str] | None = None, region: str | None = None, timezone: str | None = None,
         force: bool = False, yes: bool = False) -> int:
    base = home()
    flags_given = any(v is not None for v in (tracks, region, timezone))
    interactive = sys.stdin.isatty() and not yes and not flags_given
    if not interactive and not flags_given:
        print("Not asking questions (no terminal, or --yes): using the example's settings. "
              "Pass --track, --region and --timezone to choose.")
    try:
        choice = resolve(tracks, region, timezone, interactive)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1
    print(f"Setting up in {base}: tracks {', '.join(choice.tracks)}, region {choice.region or 'none'}, "
          f"timezone {choice.timezone}")
    src_dir = project_dir()
    for name in FILES:
        dst = base / name
        if dst.exists() and not force:
            print(f"  keep    {name} (already there, use --force to replace it)")
            continue
        text = (src_dir / (".env.example" if name == ".env" else example_for(Path(name)).name)).read_text(encoding="utf-8")
        if name == "profile.yml":
            text = profile_text(text, choice)
        elif name == "config.yml":
            text = config_text(text, choice)
        pack = src_dir / "presets" / "companies" / f"{choice.region}.yml"
        if name == "companies.yml" and choice.region != example_defaults().region and pack.exists():
            text = pack.read_text(encoding="utf-8")
        existed = dst.exists()
        dst.write_text(text, encoding="utf-8")
        print(f"  {'replaced' if existed else 'created '} {name}")
    for note in choice.notes:
        print(f"  note: {note}")
    print("""
Next steps:
  1. Telegram: talk to @BotFather, create a bot, put the token in .env as TELEGRAM_BOT_TOKEN.
  2. Send your bot /start, then run `jobbot chat-id` and put the number in .env as TELEGRAM_CHAT_ID.
  3. Edit profile.yml (roles, locations, salary) and config.yml (sources, queries).
  4. `jobbot check-config`, then `jobbot once --dry-run -v --max-age-hours 336` to see what would match.
  5. `jobbot test-alert`, then `jobbot run` (or deploy it, see docs/deployment.md).""")
    return 0
