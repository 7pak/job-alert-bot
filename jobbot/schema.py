"""Light validation for config.yml and profile.yml.

Unknown keys are warnings (with a "did you mean" hint), wrong types are errors. Messages point to
the file and line, so nobody has to read the Python code to fix a typo.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

import yaml

NUM = (int, float)
TEXT = (str, type(None))
ANY = object


class Map:
    """A mapping with free keys (e.g. currency codes) whose values all follow `spec`."""

    def __init__(self, spec):
        self.spec = spec


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def yaml_lines(text: str) -> dict[tuple, int]:
    """Map each key path, e.g. ('sources', 'linkedin', 'queries', 0), to its 1-based line."""
    lines: dict[tuple, int] = {}
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return lines

    def walk(node, path: tuple) -> None:
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                p = path + (k.value,)
                lines[p] = k.start_mark.line + 1
                walk(v, p)
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                lines[path + (i,)] = item.start_mark.line + 1
                walk(item, path + (i,))

    if root is not None:
        walk(root, ())
    return lines


def _type_name(spec) -> str:
    if isinstance(spec, dict) or isinstance(spec, Map):
        return "a mapping (key: value)"
    if isinstance(spec, list):
        return "a list"
    names = {int: "a whole number", float: "a number", str: "text", bool: "true or false", type(None): "empty"}
    if isinstance(spec, tuple):
        return " or ".join(dict.fromkeys(names.get(t, t.__name__) for t in spec))
    return names.get(spec, getattr(spec, "__name__", str(spec)))


def _is(value, spec) -> bool:
    if spec is ANY:
        return True
    types = spec if isinstance(spec, tuple) else (spec,)
    if isinstance(value, bool) and bool not in types:
        return False  # true/false is not a number here
    return isinstance(value, types)


def validate(data, spec, filename: str, lines: dict[tuple, int], report: Report | None = None,
             path: tuple = ()) -> Report:
    report = report or Report()

    def where(p: tuple) -> str:
        line = lines.get(p) or lines.get(p[:-1]) if p else None
        dotted = ".".join(str(x) for x in p) or "(top level)"
        return f"{filename}:{line}: {dotted}" if line else f"{filename}: {dotted}"

    if isinstance(spec, dict):
        if not isinstance(data, dict):
            report.errors.append(f"{where(path)}: expected {_type_name(spec)}, got {type(data).__name__}")
            return report
        for key, value in data.items():
            if key not in spec:
                close = difflib.get_close_matches(str(key), [str(k) for k in spec], n=1)
                hint = f" Did you mean '{close[0]}'?" if close else ""
                report.warnings.append(f"{where(path + (key,))}: unknown key, ignored.{hint}")
                continue
            if value is None:
                continue  # an empty value means "use the default"
            validate(value, spec[key], filename, lines, report, path + (key,))
    elif isinstance(spec, Map):
        if not isinstance(data, dict):
            report.errors.append(f"{where(path)}: expected {_type_name(spec)}, got {type(data).__name__}")
            return report
        for key, value in data.items():
            validate(value, spec.spec, filename, lines, report, path + (key,))
    elif isinstance(spec, list):
        if not isinstance(data, list):
            report.errors.append(f"{where(path)}: expected {_type_name(spec)}, got {type(data).__name__} "
                                 f"({data!r}). Write it as [a, b] or as lines starting with '- '.")
            return report
        for i, item in enumerate(data):
            validate(item, spec[0], filename, lines, report, path + (i,))
    elif not _is(data, spec):
        report.errors.append(f"{where(path)}: expected {_type_name(spec)}, got {data!r}")
    return report


# ---- specs ----------------------------------------------------------------------------

STR_LIST = [str]
_SOURCE = {"enabled": bool, "interval_seconds": NUM, "workers": int}

CONFIG_SPEC = {
    "poll_seconds": NUM,
    "max_job_age_hours": NUM,
    "alert_min_score": NUM,
    "max_alerts_per_cycle": int,
    "max_backoff_seconds": NUM,
    "request_timeout_seconds": NUM,
    "db_path": str,
    "profile_file": str,
    "companies_file": str,
    "log_level": str,
    "healthcheck_url": TEXT,
    "notifier": str,
    "currency_rates": Map(NUM),
    "sources": {
        "greenhouse": _SOURCE,
        "lever": _SOURCE,
        "ashby": _SOURCE,
        "workable": _SOURCE,
        "smartrecruiters": _SOURCE,
        "workable_search": {**_SOURCE, "queries": STR_LIST, "locations": STR_LIST, "pages": int},
        "himalayas": {**_SOURCE, "queries": STR_LIST, "country": str},
        "careerjet": {**_SOURCE, "queries": STR_LIST, "locales": STR_LIST, "affiliate_id": TEXT},
        "linkedin": {**_SOURCE, "time_window": str, "min_request_gap_seconds": NUM,
                     "queries": [{"keywords": str, "location": str}],
                     "city_fix": {"suspect": STR_LIST, "cities": STR_LIST}},
    },
    "ai": {
        "enabled": bool,
        "provider": str,
        "models": STR_LIST,
        "timeout_seconds": NUM,
        "min_score": NUM,
        "prefilter_min_score": NUM,
        "max_calls_per_day": int,
        "min_gap_seconds": NUM,
        "max_desc_chars": int,
    },
    "tailoring": {
        "enabled": bool,
        "provider": str,
        "model": str,
        "cv_file": str,
        "docx": bool,
        "cover_letter": bool,
        "max_per_day": int,
        "max_cost_per_month_usd": NUM,
        "price_per_mtok": {"input": NUM, "output": NUM},
        "allow_free_tier": bool,
        "max_desc_chars": int,
    },
}

_TRACK = {
    "preset": str,
    "name": str,
    "label": str,
    "title_any": STR_LIST,
    "title_with_role": STR_LIST,
    "title_exclude": STR_LIST,
    "allow_title_words": STR_LIST,
    "description_signals": STR_LIST,
    "levels": STR_LIST,
    "weight": NUM,
    "bonus": [{"terms": STR_LIST, "title": NUM, "description": NUM, "junior_title": NUM}],
    "avoid": [{"name": str, "title_terms": STR_LIST, "title_ok_with": STR_LIST, "rescued_by": STR_LIST,
               "description_terms": STR_LIST, "description_ok_with": STR_LIST}],
    "note": str,
    "fallback": bool,
    "ai_description": str,
    "search_queries": STR_LIST,
}

PROFILE_SPEC = {
    "name": str,
    "summary": str,
    "years_experience": NUM,
    "timezone": str,
    "region": str,
    "skills": {"main": STR_LIST, "secondary": STR_LIST},
    "tracks": [(dict, str)],
    "role_words": STR_LIST,
    "title_aliases": Map(str),
    "title_noise": STR_LIST,
    "exclude_titles": STR_LIST,
    "exclude_titles_unless_engineering": STR_LIST,
    "engineering_titles": STR_LIST,
    "generic_titles": {"titles": STR_LIST, "exclude": STR_LIST, "min_signals": int},
    "seniority": {
        "max_years": int, "junior_max_years": int, "comfortable_years": int,
        "blocked_title_words": STR_LIST, "senior_title_words": STR_LIST, "junior_title_words": STR_LIST,
        "graduate_title_words": STR_LIST, "graduate_description_patterns": STR_LIST,
        "allow_graduate_programs": bool, "years_patterns": STR_LIST,
    },
    "locations": {
        "home": str, "home_country": str, "region_name": str,
        "targets": [{"name": str, "terms": STR_LIST, "bonus": NUM}],
        "remote": str, "remote_ok_terms": STR_LIST, "confirm_remote_terms": STR_LIST,
        "region_lock_terms": STR_LIST, "work_modes": STR_LIST, "ai_description": str,
    },
    "work_authorization": {"visa": str, "citizenship": str, "note": str,
                           "nationals_only_patterns": STR_LIST, "nationals_examples": str},
    "languages": [(str, dict)],
    "salary": {"min": NUM, "currency": str, "period": str, "minimum_markers": STR_LIST},
    "blocked": {"title_keywords": STR_LIST, "companies": STR_LIST},
    "ai": {"soft_issues": str, "notes": str},
    "search": {"timezone": str, "locations": STR_LIST, "country": str, "careerjet_locale": str,
               "linkedin_location": str},
}
TRACK_SPEC = _TRACK
