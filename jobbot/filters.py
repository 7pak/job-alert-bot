"""Keyword filter. Hard filters drop a job. Jobs that pass get a 1-5 keyword score.

Every rule comes from the profile (profile.yml, see docs/configuration.md). The regexes here are
only generic English job-post grammar: how posts say "required", "nice to have", "5+ years".
"""
from __future__ import annotations

import re

from .models import Job, Verdict
from .money import Money
from .patterns import alternation, terms_re
from .profile import AvoidRule, Profile, Track
from .text import sentences

LANG_CUE = re.compile(
    r"fluen|proficien|native[- ](?:speaker|level|or)|speak|spoken|written|verbal|language skills|bilingual"
    r"|command of|business[- ]level|mother tongue|(?<![a-z])[abc][12](?![a-z0-9])|required|must|mandatory|essential",
    re.I,
)
SOFT = re.compile(
    r"plus|nice[- ]to[- ]have|preferred|preferable|advantage|bonus|desirable|beneficial|asset|ideally|optional",
    re.I,
)

REMOTE_LOC = re.compile(r"remote|anywhere|work from home|wfh", re.I)
REMOTE_DESC = re.compile(r"fully remote|100% remote|remote[- ]first|work from anywhere|remote (?:position|role|job)", re.I)
HYBRID = re.compile(r"hybrid", re.I)
_LOCK_CUE = (r"(?i:based|located|reside|residing|living|resident|authori[sz]ed to work|eligible to work"
             r"|right to work|work authori[sz]ation|time ?zones?)")

_NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
YEARS_RE = re.compile(
    r"(?<![\d.])" + _NUM + r"\s*(?:\(\d{1,2}\)\s*)?(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)(?![a-z])",
    re.I,
)
YEARS_AFTER = re.compile(
    r"^.{0,60}?(?:experience|exp\b|professional|industry|hands[- ]on|working|developing|development|building"
    r"|engineering|programming|coding|in (?:a |an )?(?:mobile|software|android|flutter|ios|similar|relevant"
    r"|backend|back-end|frontend|front-end|web|data|cloud|devops|qa|testing|design|product|machine learning))",
    re.I,
)
YEARS_BEFORE = re.compile(r"(?:minimum|at least|min\.?|requires?)\s*(?:of\s*)?$", re.I)
BARE_END = re.compile(r"[ \t]*(?:[.;)]|$|\n)")
HISTORY = re.compile(r"(?:for|over|than|since|around|about|past|last)\s*$", re.I)


class JobFilter:
    def __init__(self, profile: Profile, money: Money | None = None):
        self.p = profile
        self.money = money or Money()
        if not self.money.known(profile.salary_currency):
            raise ValueError(f"salary currency {profile.salary_currency} is not in currency_rates")
        self.not_relevant = profile.not_relevant
        self.exclude_all = terms_re(profile.data["exclude_titles"])
        self.exclude_soft_all = terms_re(profile.data["exclude_titles_unless_engineering"])
        region = alternation(profile.region_lock_terms)
        self.remote_restrict = [
            re.compile(_LOCK_CUE + r"[^.]{0,40}?(?<![A-Za-z])" + region + r"(?![A-Za-z])"),
            re.compile(r"(?<![A-Za-z])" + region + r"[- ](?i:only)(?![a-z])"),
        ]

    # ---- public -------------------------------------------------------

    def precheck(self, title: str, company: str = "") -> str | None:
        """Title-only check, run before fetching a job's details. Returns a drop reason or None."""
        p = self.p
        title = self.norm_title(title)
        if reason := self._blocked(title, company):
            return reason
        track = self._title_track(title)
        generic = self._generic_title(title)
        # A generic title ("Software Engineer") may still match a track through its description.
        if track is None and not (generic and p.has_signals):
            return self.not_relevant
        if not self._allows_grad(track) and (m := p.grad_title.search(title)):
            return f"graduate/intern title ({m.group(0)})"
        if not (track and "lead" in track.levels) and (m := p.blocked_title_words.search(title)):
            return f"too senior ({m.group(0)})"
        # "Senior Software Engineer" may still be a Flutter role (checked in the description),
        # but "Senior Backend Engineer" on a junior-only track is not.
        if track and "senior" not in track.levels and not generic and p.senior_title.search(title):
            return self._senior_reason(track)
        return None

    def evaluate(self, job: Job) -> Verdict:
        p = self.p
        title, text = self.norm_title(job.title), job.description
        full = f"{title}\n{job.location}\n{text}"
        v = Verdict(keep=True)

        if reason := self._blocked(title, job.company):
            return self._drop(reason)
        track = self._track(title, text)
        if track is None:
            return self._drop(self.not_relevant)
        v.track = track.name

        if reason := self.precheck(title, job.company):
            return self._drop(reason)
        if not self._allows_grad(track) and (m := p.grad_desc.search(text)):
            return self._drop(f"graduate program ({m.group(0)})")
        if p.nationals and (m := p.nationals.search(full)):
            return self._drop(f"nationals only ({m.group(0)})")

        if reason := self._language(job, v):
            return self._drop(reason)
        for rule in track.avoid:
            if reason := self._avoid(rule, title, text, v):
                return self._drop(reason)
        if reason := self._location(job, v):
            return self._drop(reason)

        years = self._years(text)
        if years and years[0] >= p.max_years:
            return self._drop(f"{years[0]}+ years required")
        if "senior" not in track.levels and p.senior_title.search(title):
            return self._drop(self._senior_reason(track))
        if track.junior_only and not (p.junior_title.search(title) or (years and years[0] <= p.junior_max_years)):
            return self._drop(f"{track.label} role, not junior level")
        if track.note:
            v.warnings.append(track.note)
        if reason := self._salary(text, v):
            return self._drop(reason)

        if job.snippet_only:
            v.warnings.append("Only a snippet was checked, read the full post")
        self._positives(full, years, v)
        v.score = self._score(job, track, years, v)
        return v

    # ---- tracks -----------------------------------------------------------

    @staticmethod
    def _drop(reason: str) -> Verdict:
        return Verdict(keep=False, reason=reason)

    def _blocked(self, title: str, company: str) -> str | None:
        if company and company.strip().lower() in self.p.blocked_companies:
            return f"blocked company ({company.strip()})"
        if m := self.p.blocked_keywords.search(title):
            return f"blocked keyword ({m.group(0)})"
        return None

    def norm_title(self, title: str) -> str:
        """Local-language titles to the words the tracks use: "Python-Entwickler (m/w/d)" -> "Python developer"."""
        p = self.p
        if not p.title_aliases and p.title_noise.pattern == "(?!x)x":
            return title
        title = p.title_noise.sub(" ", title)
        for rx, word in p.title_aliases:
            title = rx.sub(word, title)
        return re.sub(r"\s{2,}", " ", title).strip()

    def _allows_grad(self, track: Track | None) -> bool:
        return self.p.allow_graduate or bool(track and "intern" in track.levels)

    @staticmethod
    def _senior_reason(track: Track) -> str:
        if track.junior_only:
            return f"{track.label} role, not junior (senior title)"
        return f"{track.label} role, senior title (targeting {track.levels_text()})"

    def _non_eng(self, exclude: re.Pattern, exclude_soft: re.Pattern, title: str) -> bool:
        return bool(exclude.search(title) or (exclude_soft.search(title) and not self.p.eng_title.search(title)))

    def _title_matches(self, track: Track, title: str) -> bool:
        if self._non_eng(track.exclude, track.exclude_soft, title) or track.title_exclude.search(title):
            return False
        if track.title_any.search(title):
            return True
        return bool(track.title_with_role.search(title) and self.p.role_word.search(title))

    def _title_track(self, title: str) -> Track | None:
        """First track whose title rules match (fallback tracks are last in the list)."""
        return next((t for t in self.p.tracks if self._title_matches(t, title)), None)

    def _generic_title(self, title: str) -> bool:
        p = self.p
        if self._non_eng(self.exclude_all, self.exclude_soft_all, title):
            return False
        return bool(p.generic_title.search(title)) and not p.generic_exclude.search(title)

    def _track(self, title: str, text: str) -> Track | None:
        p = self.p
        for t in p.tracks:
            if not t.fallback and self._title_matches(t, title):
                return t
        if p.has_signals and self._generic_title(title) and len(p.desc_signal.findall(text)) >= p.min_signals:
            for t in p.tracks:
                if not t.fallback and t.signals.search(text):
                    return t
        for t in p.tracks:
            if t.fallback and self._title_matches(t, title):
                return t
        return None

    # ---- hard filters ---------------------------------------------------

    def _language(self, job: Job, v: Verdict) -> str | None:
        p = self.p
        if job.language and job.language.lower()[:2] not in p.spoken_codes:
            return f"posting language is {job.language}"
        for sent in [job.title, *sentences(job.description)]:
            m = p.blocked_langs.search(sent)
            if not m or p.spoken_or.search(sent):
                continue
            name = m.group(0).title()
            if SOFT.search(sent):
                v.warnings.append(f"{name} mentioned as a plus")
            elif LANG_CUE.search(sent):
                return f"requires {name}"
        return None

    @staticmethod
    def _avoid(rule: AvoidRule, title: str, text: str, v: Verdict) -> str | None:
        """Stack rules, e.g. 'React Native only' or 'iOS only' for a mobile track."""
        if rule.title_terms.search(title) and not rule.title_ok_with.search(title):
            rescue = rule.rescued_by.search(title) or rule.rescued_by.search(text)
            if not rescue:
                return f"{rule.name} role"
            v.warnings.append(f"{rule.name} title, {rescue.group(0).title()} in description")
            return None
        if m := rule.description_terms.search(text):
            ok = rule.description_ok_with
            if ok is not None and not (ok.search(title) or ok.search(text)):
                return f"{rule.name} only"
            sent = next((s for s in sentences(text) if rule.description_terms.search(s)), m.group(0))
            v.warnings.append(f"Mentions {rule.name} as a plus" if SOFT.search(sent) else f"Mentions {rule.name}")
        return None

    def _location(self, job: Job, v: Verdict) -> str | None:
        p = self.p
        loc, text = job.location.strip(), job.description
        remote = bool(REMOTE_LOC.search(loc) or REMOTE_DESC.search(text))
        v.work_mode = "Hybrid" if HYBRID.search(loc) or HYBRID.search(text) else ("Remote" if remote else "On-site")
        if v.work_mode.lower() not in p.work_modes:
            return f"{v.work_mode.lower()} not wanted"

        if p.target_any.search(loc):
            parts = [x.strip() for x in re.split(r"[;|/]", loc)]
            v.city = next((x for x in parts if p.target_any.search(x)), loc).split(",")[0].strip()
            return None

        if remote:
            if p.remote_policy == "none":
                return f"remote outside {p.region_name} ({loc or 'region not stated'})"
            if p.remote_policy == "anywhere":
                v.city = "Remote"
                return None
            for sent in [loc, *sentences(text)]:
                if p.target_any.search(sent) or p.remote_ok.search(sent):
                    continue
                for rx in self.remote_restrict:
                    if m := rx.search(sent):
                        return f"remote restricted ({m.group(0)[:50]})"
            leftover = REMOTE_LOC.sub(" ", loc)
            leftover = re.sub(r"[^A-Za-z ]+", " ", leftover).strip()
            v.city = "Remote"
            if p.remote_ok.search(loc):
                if m := p.confirm_remote.search(loc):
                    home = p.home_country or "your country"
                    v.warnings.append(f"{m.group(0).upper()} remote, confirm {home} is allowed")
                return None
            if leftover and not p.target_any.search(leftover):
                return f"remote limited to {loc}"
            if not p.target_any.search(text) and not p.remote_ok.search(text):
                v.warnings.append("Remote region not stated")
            return None

        if not loc:
            if p.target_any.search(text):
                v.city = f"{p.region_name} (from description)"
                v.warnings.append("Location taken from description")
                return None
            v.warnings.append("Location unknown")
            return None
        return f"{v.work_mode.lower()} outside {p.region_name} ({loc})"

    def _years(self, text: str) -> tuple[int, int | None] | None:
        """Largest minimum-years requirement found, as (low, high)."""
        found: list[tuple[int, int | None]] = []
        for m in YEARS_RE.finditer(text):
            after = text[m.end(): m.end() + 70]
            before = text[max(0, m.start() - 25): m.start()]
            # A bare "7+ years." at the end of a requirement line counts too, but not "for 20+ years."
            bare = "+" in m.group(0) and BARE_END.match(after) and not HISTORY.search(before)
            if not (YEARS_AFTER.search(after) or YEARS_BEFORE.search(before) or bare):
                continue
            raw = m.group(1).lower()
            found.append((_WORDNUM.get(raw) or int(raw), int(m.group(2)) if m.group(2) else None))
        for rx in self.p.years_patterns:  # local-language phrases from the region pack
            for m in rx.finditer(text):
                hi = m.group(2) if (rx.groups or 0) >= 2 else None
                found.append((int(m.group(1)), int(hi) if hi else None))
        best: tuple[int, int | None] | None = None
        for lo, hi in found:
            if lo > 20 or (hi is not None and hi < lo):
                continue
            if best is None or lo > best[0]:
                best = (lo, hi)
        return best

    def _salary(self, text: str, v: Verdict) -> str | None:
        p = self.p
        cur = p.salary_currency
        pays = [pay for sent in sentences(text) for rx in self.money.patterns for m in rx.finditer(sent)
                if (pay := self.money.read(m, sent, cur)) is not None]
        if not pays:
            return None
        best = max(pay.monthly for pay in pays)
        yearly = p.salary_period == "year"
        shown = f"{best * 12:,.0f} {cur}/year" if yearly else f"{best:,.0f} {cur}/month"
        if best >= p.salary_min_month:
            v.positives.append(f"~{best * 12 / 1000:.0f}k {cur}/yr" if yearly else f"~{best / 1000:.0f}k {cur}/mo")
            return None
        if p.salary_minimum.search(text):
            # "From EUR 52,000, overpayment depending on experience": a legal minimum, not the offer.
            v.warnings.append(f"Pay from about {shown} (a minimum, more is possible)")
            return None
        if not any(pay.clear for pay in pays):
            return None  # an amount with no pay word and no range is too unclear to drop on
        return f"salary about {shown}"

    # ---- scoring ------------------------------------------------------------

    def _positives(self, full: str, years: tuple[int, int | None] | None, v: Verdict) -> None:
        display = {s.lower(): s for s in self.p.skills}
        seen: list[str] = []
        for m in self.p.skill_re.finditer(full):
            name = display.get(m.group(0).lower(), m.group(0))
            if name.lower() not in (s.lower() for s in seen):
                seen.append(name)
        skills = seen[:4]
        if years:
            lo, hi = years
            skills.append(f"{lo}-{hi} yrs" if hi else f"{lo}+ yrs")
        v.positives[:0] = skills
        if self.p.nationals is not None:
            v.positives.append("no nationality limits")

    def _score(self, job: Job, track: Track, years, v: Verdict) -> float:
        p = self.p
        title, text, loc = job.title, job.description, job.location
        s = 3.0 + track.weight
        for b in track.bonus:
            if b.junior_title and p.junior_title.search(title):
                s += b.junior_title
            if b.terms is None:
                continue
            if b.title and b.terms.search(title):
                s += b.title
            elif b.description and b.terms.search(text):
                s += b.description
        target = next((t for t in p.targets if t.terms.search(loc)), None)
        if target:
            s += target.bonus
        if p.senior_title.search(title):
            s -= 0.4
            v.warnings.append("Senior title, check the years")
        if years and years[0] <= p.comfortable_years:
            s += 0.2
        s -= 0.2 * sum(1 for w in v.warnings if "region" in w or "unknown" in w)
        return round(min(5.0, max(1.0, s)), 1)
