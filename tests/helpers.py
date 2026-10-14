"""Shared test setup. Tests load explicit fixture profiles, never the user's own files."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jobbot.money import Money
from jobbot.profile import Profile, load_profile

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRESETS = ROOT / "presets"
# The rate table the GCC profile was tuned with (AED per unit).
AED_RATES = {"AED": 1, "USD": 3.67, "SAR": 0.98, "QAR": 1.01, "KWD": 12.0, "BHD": 9.75, "OMR": 9.55,
             "EUR": 4.0, "GBP": 4.7}


@lru_cache(maxsize=None)
def gcc_profile() -> Profile:
    return load_profile(FIXTURES / "profile_gcc.yml", PRESETS)


def profile_from(raw: dict) -> Profile:
    return load_profile(None, PRESETS, raw=raw)


def worker_cfg(**over) -> dict:
    cfg = {"max_job_age_hours": 48, "alert_min_score": 3.0, "max_alerts_per_cycle": 15,
           "profile": gcc_profile(), "money": Money(AED_RATES),
           "ai": {"min_score": 3.5, "prefilter_min_score": 2.5}}
    cfg.update(over)
    return cfg
