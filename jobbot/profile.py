"""profile.yml: who you are and which jobs you want. Every filter rule is read from here.

Load order: DEFAULTS (generic English job-post heuristics) <- region pack (`region: gcc`)
<- your profile.yml. Tracks can start from a preset (`- preset: backend`) and override any field.
See docs/configuration.md for every key.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .patterns import NEVER, human_join, terms_re

LEVELS = ("intern", "junior", "mid", "senior", "lead")
REMOTE_POLICIES = ("anywhere", "region", "none")
WORK_MODES = ("on-site", "hybrid", "remote")

# Language name -> ISO code. A language you do not speak is blocked when a post requires it.
LANGUAGES = {
    "english": "en", "arabic": "ar", "german": "de", "french": "fr", "spanish": "es", "portuguese": "pt",
    "italian": "it", "dutch": "nl", "greek": "el", "turkish": "tr", "polish": "pl", "russian": "ru",
    "mandarin": "zh", "chinese": "zh", "cantonese": "zh", "japanese": "ja", "korean": "ko", "hindi": "hi",
    "urdu": "ur", "hebrew": "he", "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi",
    "czech": "cs", "hungarian": "hu", "romanian": "ro", "ukrainian": "uk", "farsi": "fa", "persian": "fa",
    "indonesian": "id", "bahasa": "id", "malay": "ms", "thai": "th", "vietnamese": "vi", "bengali": "bn",
    "tagalog": "tl",
}

DEFAULTS: dict = {
    "name": "my profile",
    "summary": "",
    "years_experience": None,
    "timezone": "UTC",
    "region": None,
    "skills": {"main": [], "secondary": []},
    "tracks": [],
    # A title needs one of these to count as a role (for title_with_role terms such as "mobile").
    "role_words": ["engineer", "developer", "programmer", "dev", "sde", "swe", "scientist", "researcher",
                   "specialist"],
    # Titles with these words are never a match (a track can re-allow some with allow_title_words).
    "exclude_titles": [
        "designer", "marketing", "sales", "recruiter", "recruitment", "support", "analyst", "writer",
        "account", "operations", "product manager", "product owner", "tester", "sdet",
        "trainer", "tutor", "annotator", "annotation", "labeling", "labelling", "language specialist",
        "servicenow", "salesforce", "sap", "dynamics 365", "outsystems", "mendix", "pega",
    ],
    # Excluded too, unless the title also has a plain engineering phrase (engineering_titles).
    "exclude_titles_unless_engineering": ["qa", "quality", "test", "testing", "design"],
    # Local-language titles, rewritten before matching: {entwickler: developer}. Region packs set them.
    "title_aliases": {},
    # Removed from titles before matching, e.g. gender markers like "(m/w/d)". Regexes.
    "title_noise": [],
    "engineering_titles": [
        "re:(?:software|mobile|android|flutter|ios|app|ai|ml|backend|back-end|frontend|front-end|web|data|cloud"
        "|platform|devops) (?:engineer|developer)",
    ],
    # Generic titles ("Software Engineer") are matched to a track by the description:
    # at least `min_signals` hits of the tracks' description_signals.
    "generic_titles": {
        "titles": ["re:software (?:engineer|developer)|full[- ]?stack|application (?:engineer|developer)"
                   "|product engineer|founding engineer"],
        "exclude": [
            "backend", "back-end", "back end", "frontend", "front-end", "front end", "web", "data", "devops",
            "sre", "security", "infrastructure", "embedded", "firmware", "salesforce", "sap", ".net", "java",
            "php", "ruby", "golang", "qa", "test", "network", "hardware", "mainframe", "cobol", "erp",
            "dynamics", "servicenow",
        ],
        "min_signals": 2,
    },
    "seniority": {
        "max_years": 5,            # drop posts that require this many years or more
        "junior_max_years": 2,     # junior-only tracks: a junior title, or at most this many years asked
        "comfortable_years": 3,    # small score bonus when the post asks this many years or fewer
        "blocked_title_words": ["staff", "principal", "lead", "head", "director", "vp", "vice president",
                                "chief", "architect", "manager"],
        "senior_title_words": ["senior", "sr", "sr.", "mid-senior", "mid senior", "midsenior", "expert",
                               "experienced"],
        "junior_title_words": [
            "re:(?<![a-z])(?:junior|jr\\.?|associate|entry[- ]level|early[- ]career)(?![a-z])"
            "|(?:engineer|developer)\\s*(?:i|1)(?![a-z0-9])|level\\s*1(?![0-9])",
        ],
        "graduate_title_words": ["graduate", "intern", "internship", "trainee", "apprentice", "apprenticeship",
                                 "campus", "new grad", "working student"],
        "graduate_description_patterns": [
            "re:graduate (?:program|programme|scheme|trainee)|campus (?:hire|hiring|recruit\\w*)|new grad"
            "|class of 20\\d\\d|internship program",
        ],
        "allow_graduate_programs": False,
        # Extra "N years" phrases (regexes, group 1 = years), e.g. German "Mindestens 7 Jahre". Region packs set them.
        "years_patterns": [],
    },
    "locations": {
        "home": "",                 # your city, used in messages and the AI prompt
        "home_country": "",
        "region_name": "your target locations",
        "targets": [],              # [{name, terms, bonus}] in priority order
        "remote": "region",         # anywhere | region | none
        # Remote regions that include you ("Remote, Worldwide" is fine).
        "remote_ok_terms": ["worldwide", "anywhere", "global", "international", "multiple locations", "various"],
        # Remote-OK terms that still deserve a "check you are allowed" warning (e.g. emea).
        "confirm_remote_terms": [],
        # A remote post tied to one of these (and none of yours) is region-locked.
        "region_lock_terms": [
            "US", "U.S.", "U.S", "USA", "UK", "EU", "CET", "EST", "PST", "APAC", "LATAM", "united states",
            "united kingdom", "europe", "european union", "european", "canada", "north america", "americas",
            "latin america", "australia", "india",
        ],
        "work_modes": ["on-site", "hybrid", "remote"],
        "ai_description": "",
        # Places that count only when the post offers visa sponsorship or relocation: [{name, terms, bonus}].
        "sponsored_targets": [],
        # Region packs whose places are added to sponsored_targets, e.g. [dach, uk, eu].
        "sponsored_regions": [],
        # A remote job limited to a sponsored place, with no sponsorship: warn (alert with a warning) | sponsor | drop.
        "sponsored_remote": "warn",
        "sponsored_penalty": 0.3,   # taken off the score, so your own targets rank first
        "sponsorship_terms": [
            "visa sponsorship", "sponsor your visa", "sponsor visas", "sponsorship available", "sponsorship provided",
            "sponsorship offered", "we sponsor", "we can sponsor", "we will sponsor", "will sponsor",
            "visa support", "visa assistance", "relocation package", "relocation support", "relocation assistance",
            "relocation bonus", "relocation allowance", "help you relocate", "help with relocation", "blue card",
            "skilled worker visa", "work permit support",
        ],
        # Checked first: a match means the post refuses sponsorship.
        "no_sponsorship_terms": [
            r"re:\b(?:not|unable to|cannot|can't|can’t|won't|won’t)\s+(?:[\w-]+\s+){0,3}(?:sponsor|sponsorship)\b",
            r"re:\bno\s+(?:visa\s+)?sponsorship\b",
            r"re:\bsponsorship\s+(?:is\s+)?not\s+(?:available|offered|provided|possible)\b",
            "without sponsorship", "without visa sponsorship",
            "must have the right to work", "must already have the right to work", "existing right to work",
            "must be eligible to work", "must hold a valid work permit", "must have a valid work permit",
        ],
    },
    "work_authorization": {
        "visa": "",
        "citizenship": "",
        "note": "",
        "nationals_only_patterns": [],   # regexes; a match drops the job
        "nationals_examples": "",
    },
    "languages": ["english"],
    "salary": {
        "min": 0, "currency": "USD", "period": "month",
        # A post naming one of these states a minimum ("from X, overpayment possible"), not the offer.
        "minimum_markers": ["overpayment", "over-payment", "collective agreement", "collective bargaining agreement"],
    },
    "blocked": {"title_keywords": [], "companies": []},
    "ai": {
        "soft_issues": ('"nationals preferred", one year more than you have, one missing framework, '
                        "relocation inside your target region"),
        "notes": "",
    },
}

TRACK_DEFAULTS: dict = {
    "name": "",
    "label": "",
    "title_any": [],            # one of these in the title is enough
    "title_with_role": [],      # needs a role word too ("mobile" + "engineer")
    "title_exclude": [],
    "allow_title_words": [],    # remove words from exclude_titles for this track (e.g. analyst)
    "description_signals": [],  # pull generic titles ("Software Engineer") into this track
    "levels": ["junior", "mid", "senior"],
    "weight": 0.0,              # added to the base keyword score of 3.0
    "bonus": [],                # [{terms, title, description}] or [{junior_title: 0.2}]
    "avoid": [],                # stack rules, see AvoidRule
    "note": "",                 # warning added to every alert of this track
    "fallback": False,          # checked after every other track and the description signals
    "ai_description": "",
    "search_queries": [],       # used by `jobbot init` for config.yml
}

AVOID_DEFAULTS: dict = {
    "name": "",
    "title_terms": [],          # title is this stack...
    "title_ok_with": [],        # ...unless it also names one of these
    "rescued_by": [],           # a title hit plus one of these anywhere is only a warning
    "description_terms": [],    # description mentions this stack...
    "description_ok_with": None,  # ...drop unless one of these appears anywhere; null means warn only
}


class ProfileError(ValueError):
    pass


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _preset(presets_dir: Path, kind: str, name: str) -> dict:
    path = presets_dir / kind / f"{name}.yml"
    if not path.exists():
        have = sorted(p.stem for p in (presets_dir / kind).glob("*.yml"))
        raise ProfileError(f"unknown {kind[:-1]} preset '{name}'. Available: {', '.join(have) or 'none'}")
    return read_yaml(path)


def merged_profile(raw: dict, presets_dir: Path) -> dict:
    """DEFAULTS + region pack + profile.yml, with track presets expanded. Plain data."""
    data = copy.deepcopy(DEFAULTS)
    if raw.get("region"):
        data = deep_merge(data, _preset(presets_dir, "regions", str(raw["region"])))
    data = deep_merge(data, raw)
    loc = data["locations"]
    loc["sponsored_targets"] = list(loc.get("sponsored_targets") or [])
    for name in loc.get("sponsored_regions") or []:
        pack = _preset(presets_dir, "regions", str(name)).get("locations") or {}
        loc["sponsored_targets"] += [{**t, "bonus": t.get("bonus", 0)} for t in pack.get("targets") or []]
    tracks = []
    for i, t in enumerate(data.get("tracks") or []):
        if isinstance(t, str):
            t = {"preset": t}
        base = _preset(presets_dir, "tracks", str(t["preset"])) if t.get("preset") else {}
        t = {**TRACK_DEFAULTS, **base, **{k: v for k, v in t.items() if k != "preset"}}
        if not t["name"]:
            t["name"] = str(base.get("name") or f"track{i + 1}")
        tracks.append(t)
    data["tracks"] = tracks
    return data


# ---- compiled profile ---------------------------------------------------------------


@dataclass
class AvoidRule:
    name: str
    title_terms: re.Pattern
    title_ok_with: re.Pattern
    rescued_by: re.Pattern
    description_terms: re.Pattern
    description_ok_with: re.Pattern | None   # None: description hits only warn


@dataclass
class Bonus:
    terms: re.Pattern | None
    title: float = 0.0
    description: float = 0.0
    junior_title: float = 0.0


@dataclass
class Track:
    name: str
    label: str
    levels: list[str]
    weight: float
    note: str
    fallback: bool
    ai_description: str
    title_any: re.Pattern
    title_with_role: re.Pattern
    title_exclude: re.Pattern
    exclude: re.Pattern            # exclude_titles minus allow_title_words
    exclude_soft: re.Pattern
    signals: re.Pattern
    signal_terms: list[str]
    bonus: list[Bonus]
    avoid: list[AvoidRule]

    @property
    def junior_only(self) -> bool:
        return set(self.levels) <= {"intern", "junior"}

    def levels_text(self) -> str:
        core = [lv for lv in LEVELS if lv in self.levels and lv not in ("intern", "lead")]
        if not core:
            return ""
        return core[0] if len(core) == 1 else f"{core[0]} to {core[-1]}"


@dataclass
class Target:
    name: str
    terms: re.Pattern
    bonus: float


@dataclass
class Profile:
    data: dict
    tracks: list[Track]
    not_relevant: str
    role_word: re.Pattern
    eng_title: re.Pattern
    generic_title: re.Pattern
    generic_exclude: re.Pattern
    min_signals: int
    desc_signal: re.Pattern
    has_signals: bool
    blocked_title_words: re.Pattern
    senior_title: re.Pattern
    junior_title: re.Pattern
    grad_title: re.Pattern
    grad_desc: re.Pattern
    allow_graduate: bool
    max_years: int
    junior_max_years: int
    comfortable_years: int
    targets: list[Target]
    target_any: re.Pattern
    remote_policy: str
    remote_ok: re.Pattern
    confirm_remote: re.Pattern
    region_lock_terms: list[str]
    sponsored_targets: list[Target]
    sponsored_any: re.Pattern
    sponsored_remote: str
    sponsored_penalty: float
    sponsorship_yes: re.Pattern
    sponsorship_no: re.Pattern
    work_modes: list[str]
    region_name: str
    home: str
    home_country: str
    nationals: re.Pattern | None
    spoken: list[dict]
    spoken_codes: set[str]
    blocked_langs: re.Pattern
    spoken_or: re.Pattern
    salary_min: float
    salary_currency: str
    salary_period: str
    salary_minimum: re.Pattern
    skills: list[str]
    skill_re: re.Pattern
    blocked_keywords: re.Pattern
    title_noise: re.Pattern
    title_aliases: list[tuple[re.Pattern, str]]
    years_patterns: list[re.Pattern]
    blocked_companies: set[str] = field(default_factory=set)
    timezone: str = "UTC"

    @property
    def salary_min_month(self) -> float:
        return self.salary_min / 12 if self.salary_period == "year" else self.salary_min


def _f(v, default: float = 0.0) -> float:
    return default if v is None else float(v)


def _languages(raw) -> list[dict]:
    out = []
    for item in raw or []:
        if isinstance(item, str):
            item = {"name": item}
        name = str(item["name"]).strip().lower()
        out.append({"name": name, "level": str(item.get("level") or ""),
                    "code": str(item.get("code") or LANGUAGES.get(name) or name[:2]).lower()})
    return out


def _spoken_or(names: list[str]) -> re.Pattern:
    """"English or German" means either is fine, so a language next to one you speak is not a wall."""
    if not names:
        return NEVER
    alt = "|".join(map(re.escape, names))
    return re.compile(rf"(?:{alt})\s+or|or\s+(?:{alt})", re.I)


def compile_profile(data: dict) -> Profile:
    sen = data["seniority"]
    loc = data["locations"]
    auth = data["work_authorization"]
    excl, excl_soft = data["exclude_titles"], data["exclude_titles_unless_engineering"]

    tracks: list[Track] = []
    for t in data["tracks"]:
        allow = {str(w).lower() for w in t.get("allow_title_words") or []}
        bonuses = []
        for b in t.get("bonus") or []:
            bonuses.append(Bonus(terms_re(b["terms"]) if b.get("terms") else None, _f(b.get("title")),
                                 _f(b.get("description")), _f(b.get("junior_title"))))
        rules = []
        for a in t.get("avoid") or []:
            a = {**AVOID_DEFAULTS, **a}
            ok = a["description_ok_with"]
            rules.append(AvoidRule(a["name"], terms_re(a["title_terms"]), terms_re(a["title_ok_with"]),
                                   terms_re(a["rescued_by"]), terms_re(a["description_terms"]),
                                   None if ok is None else terms_re(ok)))
        signals = [str(s) for s in t.get("description_signals") or []]
        tracks.append(Track(
            name=t["name"], label=t.get("label") or t["name"], levels=[str(x) for x in t["levels"]],
            weight=_f(t.get("weight")), note=t.get("note") or "", fallback=bool(t.get("fallback")),
            ai_description=t.get("ai_description") or "",
            title_any=terms_re(t["title_any"]), title_with_role=terms_re(t["title_with_role"]),
            title_exclude=terms_re(t["title_exclude"]),
            exclude=terms_re([w for w in excl if str(w).lower() not in allow]),
            exclude_soft=terms_re([w for w in excl_soft if str(w).lower() not in allow]),
            signals=terms_re(signals), signal_terms=signals, bonus=bonuses, avoid=rules,
        ))

    # Non-fallback tracks keep their order, fallback tracks go last.
    ordered = [t for t in tracks if not t.fallback] + [t for t in tracks if t.fallback]
    all_signals = [s for t in ordered for s in t.signal_terms]
    targets = [Target(str(x.get("name") or ""), terms_re(x.get("terms") or [], caps_sensitive=True),
                      _f(x.get("bonus"), 0.2)) for x in loc.get("targets") or []]
    spoken = _languages(data["languages"])
    codes = {s["code"] for s in spoken}
    names = [s["name"] for s in spoken]
    blocked_langs = [n for n, c in LANGUAGES.items() if c not in codes and n not in names]
    patterns = auth.get("nationals_only_patterns") or []
    sal = data["salary"]
    skills = [str(s) for s in (data["skills"].get("main") or []) + (data["skills"].get("secondary") or [])]
    blocked = data["blocked"]

    return Profile(
        data=data,
        tracks=ordered,
        not_relevant=f"not a {human_join([t.label for t in tracks])} role" if tracks else "no tracks in profile",
        role_word=terms_re(data["role_words"]),
        eng_title=terms_re(data["engineering_titles"]),
        generic_title=terms_re(data["generic_titles"]["titles"]),
        generic_exclude=terms_re(data["generic_titles"]["exclude"]),
        min_signals=int(data["generic_titles"].get("min_signals", 2)),
        desc_signal=terms_re(all_signals),
        has_signals=bool(all_signals),
        blocked_title_words=terms_re(sen["blocked_title_words"]),
        senior_title=terms_re(sen["senior_title_words"]),
        junior_title=terms_re(sen["junior_title_words"]),
        grad_title=terms_re(sen["graduate_title_words"]),
        grad_desc=terms_re(sen["graduate_description_patterns"]),
        allow_graduate=bool(sen["allow_graduate_programs"]),
        max_years=int(sen["max_years"]),
        junior_max_years=int(sen["junior_max_years"]),
        comfortable_years=int(sen["comfortable_years"]),
        targets=targets,
        target_any=terms_re([t for x in loc.get("targets") or [] for t in x.get("terms") or []],
                            caps_sensitive=True),
        remote_policy=str(loc["remote"]),
        remote_ok=terms_re(loc["remote_ok_terms"], caps_sensitive=True),
        confirm_remote=terms_re(loc["confirm_remote_terms"], caps_sensitive=True),
        region_lock_terms=[str(x) for x in loc["region_lock_terms"]],
        sponsored_targets=[Target(str(x.get("name") or ""), terms_re(x.get("terms") or [], caps_sensitive=True),
                                  _f(x.get("bonus"), 0.0)) for x in loc["sponsored_targets"]],
        sponsored_any=terms_re([t for x in loc["sponsored_targets"] for t in x.get("terms") or []],
                               caps_sensitive=True),
        sponsored_remote=str(loc["sponsored_remote"]),
        sponsored_penalty=_f(loc["sponsored_penalty"], 0.3),
        sponsorship_yes=terms_re(loc["sponsorship_terms"]),
        sponsorship_no=terms_re(loc["no_sponsorship_terms"]),
        work_modes=[str(m).lower() for m in loc["work_modes"]],
        region_name=loc.get("region_name") or "your target locations",
        home=loc.get("home") or "",
        home_country=loc.get("home_country") or "",
        nationals=re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None,
        spoken=spoken,
        spoken_codes=codes,
        blocked_langs=terms_re(blocked_langs),
        spoken_or=_spoken_or(names),
        salary_min=_f(sal.get("min")),
        salary_currency=str(sal.get("currency") or "USD").upper(),
        salary_period="year" if str(sal.get("period") or "month").startswith("y") else "month",
        salary_minimum=terms_re(sal.get("minimum_markers") or []),
        skills=skills,
        skill_re=terms_re(skills),
        blocked_keywords=terms_re(blocked.get("title_keywords") or []),
        title_noise=re.compile("|".join(f"(?:{n})" for n in data.get("title_noise") or []) or "(?!x)x", re.I),
        title_aliases=[(re.compile(rf"-?(?<![A-Za-z0-9]){re.escape(str(a))}(?![A-Za-z0-9])", re.I), f" {b}")
                       for a, b in sorted((data.get("title_aliases") or {}).items(), key=lambda kv: -len(kv[0]))],
        years_patterns=[re.compile(str(x), re.I) for x in sen.get("years_patterns") or []],
        blocked_companies={str(c).strip().lower() for c in blocked.get("companies") or []},
        timezone=str(data.get("timezone") or "UTC"),
    )


def load_profile(path: Path | None, presets_dir: Path, raw: dict | None = None) -> Profile:
    """Read and compile a profile. Pass `raw` to skip reading the file (tests)."""
    if raw is None:
        raw = read_yaml(path) if path else {}
    return compile_profile(merged_profile(raw, presets_dir))
