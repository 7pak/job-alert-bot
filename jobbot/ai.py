"""AI scoring (optional): reads the full job post and finds hidden walls the keyword filter cannot see.

Only public job posts and the anonymous parts of profile.yml (summary, location, languages, targets)
are sent. Never your name, contact details or CV. Provider: Gemini API via plain REST
(models.generateContent). Note: the Gemini free tier may use prompts to improve Google's models.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import requests

from .http import Http, RateLimited
from .models import Job, Verdict
from .patterns import NEVER, human_join
from .profile import Profile, Track

log = logging.getLogger(__name__)

GENERIC_CANDIDATE = "- A job seeker. No other details given."

RUBRIC = """score (1 to 5, decimals allowed):
5 = strong match, no walls, years fit (0 to {fit}), stack matches well.
4 = good match with a minor gap.
3 = possible but with a clear gap (stack, years, seniority wording).
2 = weak match.
1 = wrong role or a hard wall.
If hard_wall is true, score must be 1 or 2.

Keep positives and warnings short (max 6 words each), concrete, and taken from the post. No em-dashes.
"""


def _candidate(profile: Profile) -> str:
    d = profile.data
    lines = [ln.strip() for ln in (d.get("summary") or "").strip().splitlines() if ln.strip()]
    lines = [ln if ln.startswith("-") else f"- {ln}" for ln in lines]
    auth = d["work_authorization"]
    if profile.home or auth.get("visa") or auth.get("citizenship") or auth.get("note"):
        s = f"- Lives in {profile.home}" if profile.home else "- Location not given"
        s += f" on a {auth['visa']}." if auth.get("visa") else "."
        if auth.get("citizenship"):
            s += f" Citizen of {auth['citizenship']}."
        if auth.get("note"):
            s += f" {auth['note'].strip()}"
        lines.append(s)
    if profile.spoken:
        langs = ", ".join(f"{s['name'].title()} ({s['level']})" if s["level"] else s["name"].title()
                          for s in profile.spoken)
        lines.append(f"- Languages: {langs}. No other languages.")
    return "\n".join(lines) or GENERIC_CANDIDATE


def _a(word: str) -> str:
    return "An" if word[:1].lower() in "aeiou" else "A"


def _track_line(t: Track) -> str:
    if t.ai_description:
        return t.ai_description
    lv = t.levels_text()
    return f"{t.label} roles" + (f" at {lv} level" if lv else "") + "."


def _location_line(profile: Profile) -> str:
    loc = profile.data["locations"]
    if loc.get("ai_description"):
        return loc["ai_description"]
    names = [t.name for t in profile.targets if t.name]
    where = f"in {human_join(names)} (in that order of preference)" if names else "anywhere"
    home = profile.home_country or "the candidate's country"
    remote = {"region": f", or remote that explicitly allows {home}",
              "anywhere": ", or remote from anywhere",
              "none": " (no remote roles)"}[profile.remote_policy]
    return where + remote + _sponsored_line(profile) + "."


def _sponsored_line(profile: Profile) -> str:
    names = list(dict.fromkeys(t.name for t in profile.sponsored_targets if t.name))
    if not names:
        return ""
    line = f". Also {human_join(names)}, but only when the post offers visa sponsorship or relocation"
    if profile.sponsored_remote == "warn":
        line += " (remote roles limited to these places are acceptable too)"
    return line


def build_system_prompt(profile: Profile | None) -> str:
    """The AI instructions, built from profile.yml. Nothing about the user is hard-coded."""
    if profile is None:
        return f"You screen job posts for one candidate.\n\nCandidate:\n{GENERIC_CANDIDATE}\n\n" + RUBRIC.format(fit=4)
    d = profile.data
    sen = d["seniority"]
    walls = []
    if profile.nationals is not None:
        ex = d["work_authorization"].get("nationals_examples")
        walls.append("Only nationals of a country can apply" + (f" ({ex})." if ex else "."))
    if profile.spoken:
        walls.append(f"A spoken language other than {human_join([s['name'].title() for s in profile.spoken])} "
                     'is required (not "nice to have").')
    region = profile.region_name
    home = profile.home_country or "the candidate's country"
    names = list(dict.fromkeys(t.name for t in profile.sponsored_targets if t.name))
    if names:
        region = f"{region} (or {human_join(names)} with visa sponsorship offered)"
    if names and profile.sponsored_remote == "warn" and profile.remote_policy == "region":
        walls.append(f"On-site or hybrid outside {region}, or remote limited to regions that exclude {home} "
                     f"and are not {human_join(names)}.")
        walls.append("A post that says it cannot sponsor a visa, or requires an existing right to work there.")
    elif profile.remote_policy == "region":
        walls.append(f"On-site or hybrid outside {region}, or remote limited to regions that exclude {home} "
                     "(US only, EU only, ...).")
    elif profile.remote_policy == "none":
        walls.append(f"Any role outside {region}, including remote roles.")
    else:
        walls.append(f"On-site or hybrid outside {region}.")
    blocked = [w.title() for w in sen["blocked_title_words"][:4]]
    walls.append(f"{profile.max_years} or more years of experience required"
                 + (f", or {' / '.join(blocked)} level." if blocked else "."))
    for t in profile.tracks:
        if t.junior_only:
            walls.append(f"{_a(t.label)} {t.label} role that is not junior.")
        elif "senior" not in t.levels:
            walls.append(f"{_a(t.label)} {t.label} role at senior level or above.")
        drops = [r.name for r in t.avoid if r.title_terms is not NEVER or r.description_ok_with is not None]
        if drops:
            walls.append(f"{human_join([f'{n}-only' for n in drops])} {t.label} roles.")
    if not profile.allow_graduate:
        walls.append("Graduate or campus program, or internship.")
    if profile.salary_min:
        walls.append(f"Stated salary below {profile.salary_min:,.0f} {profile.salary_currency} per "
                     f"{profile.salary_period} (or equivalent).")
    modes = [m for m in ("on-site", "hybrid", "remote") if m not in profile.work_modes]
    if modes:
        walls.append(f"{human_join([m.capitalize() for m in modes])} work.")
    walls.append("Requires existing work authorization or residency the candidate does not have "
                 '(e.g. "US citizens only", "must already hold a local work permit").')

    parts = [
        "You screen job posts for one candidate.",
        "",
        "Candidate:",
        _candidate(profile),
        "Target roles:",
        *[f"- {_track_line(t)}" for t in profile.tracks],
        f"Location: {_location_line(profile)}",
        "",
        "hard_wall = true when ANY of these is clearly stated in the post:",
        *[f"- {w}" for w in walls],
        f"Soft issues (NOT walls, put them in warnings): {d['ai'].get('soft_issues') or 'none'}.",
    ]
    if (d["ai"].get("notes") or "").strip():
        parts.append(d["ai"]["notes"].strip())
    parts += ["", RUBRIC.format(fit=max(0, profile.max_years - 1))]
    return "\n".join(parts)


SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "hard_wall": {"type": "boolean"},
        "wall_reason": {"type": "string"},
        "years_required": {"type": "integer"},
        "location": {"type": "string"},
        "work_mode": {"type": "string", "enum": ["on-site", "hybrid", "remote", "unclear"]},
        "positives": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "hard_wall", "wall_reason", "years_required", "location", "work_mode", "positives", "warnings"],
}


@dataclass
class AiResult:
    score: float
    hard_wall: bool
    wall_reason: str = ""
    years_required: int = -1
    location: str = ""
    work_mode: str = "unclear"
    positives: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: str = ""


class Scorer(Protocol):
    def score(self, job: Job, verdict: Verdict) -> AiResult | None:
        """None means the AI check could not run (quota, error). The caller falls back to keywords."""
        ...


class GeminiScorer:
    API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, http: Http, model: str | list[str], system: str | None = None,
                 max_desc_chars: int = 12000, min_gap_seconds: float = 6.0,
                 calls_today: "CallCounter | None" = None, max_calls_per_day: int = 200):
        self.api_key = api_key
        self.http = http
        # Tried in order. Free-tier models are often overloaded (503) or out of quota (429),
        # so a busy model just hands the job to the next one.
        self.models = [model] if isinstance(model, str) else list(model)
        self.model = self.models[0]
        self.last_model = ""
        self.system = system or build_system_prompt(None)
        self.max_desc_chars = max_desc_chars
        self.min_gap = min_gap_seconds
        self.counter = calls_today or CallCounter()
        self.max_calls = max_calls_per_day

    def _prompt(self, job: Job, verdict: Verdict) -> str:
        desc = job.description[: self.max_desc_chars]
        note = " (only a short snippet is available)" if job.snippet_only else ""
        return (
            f"Title: {job.title}\nCompany: {job.company}\nListed location: {job.location or 'not given'}\n"
            f"Source: {job.source}\nKeyword filter notes: {'; '.join(verdict.warnings) or 'none'}\n\n"
            f"Job description{note}:\n{desc}\n\n"
            "Return the JSON assessment."
        )

    def _body(self, job: Job, verdict: Verdict, with_schema: bool) -> dict:
        gen = {"responseMimeType": "application/json", "temperature": 0.2}
        if with_schema:
            gen["responseSchema"] = SCHEMA
        return {
            "systemInstruction": {"parts": [{"text": self.system}]},
            "contents": [{"role": "user", "parts": [{"text": self._prompt(job, verdict)}]}],
            "generationConfig": gen,
        }

    def score(self, job: Job, verdict: Verdict) -> AiResult | None:
        if self.counter.today() >= self.max_calls:
            log.warning("AI daily cap (%d) reached, using keyword score", self.max_calls)
            return None
        headers = {"x-goog-api-key": self.api_key}
        for model in self.models:
            url = self.API.format(model=model)
            with_schema = True
            for _ in range(2):  # second try only to drop the schema after a 400
                self.counter.add()
                try:
                    data = self.http.post_json(url, self._body(job, verdict, with_schema), headers=headers,
                                               min_interval=self.min_gap)
                    result = parse_result(data)
                    self.last_model = model
                    return result
                except RateLimited:
                    log.warning("%s: quota or rate limit, trying the next model", model)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else 0
                    body = exc.response.text[:200] if exc.response is not None else ""
                    if status == 400 and with_schema:
                        log.warning("%s rejected the schema, retrying without it: %s", model, body)
                        with_schema = False
                        continue
                    log.warning("%s: HTTP %s, trying the next model", model, status)
                except Exception as exc:  # timeouts, bad JSON
                    log.warning("%s failed (%s), trying the next model", model, str(exc)[:120])
                break
        log.warning("AI check failed on every model for %s, using keyword score", job.title)
        return None


def parse_result(data: dict) -> AiResult:
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    obj = json.loads(text)
    score = max(1.0, min(5.0, float(obj.get("score", 1))))
    wall = bool(obj.get("hard_wall"))
    if wall:
        score = min(score, 2.0)
    return AiResult(
        score=round(score, 1),
        hard_wall=wall,
        wall_reason=str(obj.get("wall_reason") or "").strip(),
        years_required=int(obj.get("years_required", -1) or -1),
        location=str(obj.get("location") or "").strip(),
        work_mode=str(obj.get("work_mode") or "unclear"),
        positives=[str(p).strip() for p in (obj.get("positives") or []) if str(p).strip()][:4],
        warnings=[str(w).strip() for w in (obj.get("warnings") or []) if str(w).strip()][:3],
        raw=text,
    )


class CallCounter:
    """Counts AI calls per UTC day, in the settings table when a store is given."""

    def __init__(self, store=None):
        self.store = store
        self._mem: dict[str, int] = {}

    def _key(self) -> str:
        return "ai_calls:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def today(self) -> int:
        if self.store is None:
            return self._mem.get(self._key(), 0)
        return int(self.store.get_setting(self._key(), "0") or 0)

    def add(self) -> None:
        n = self.today() + 1
        if self.store is None:
            self._mem[self._key()] = n
        else:
            self.store.set_setting(self._key(), str(n))
