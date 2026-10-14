"""Turn the word lists in profile.yml into regexes.

A plain entry matches as a whole word, ignoring case ("react native" does not match "reactive").
An entry that starts with `re:` is a raw regular expression, used as is (also ignoring case).
"""
from __future__ import annotations

import re

NEVER = re.compile(r"(?!x)x")
# Short all-caps place codes (US, UK, EU, U.S.) are matched case-sensitively in location lists,
# so "join us" is not read as "US".
_CAPS = re.compile(r"^[A-Z][A-Z.]{1,4}$")


def terms_re(terms: list | tuple | None, caps_sensitive: bool = False) -> re.Pattern:
    plain: list[str] = []
    raw: list[str] = []
    for t in terms or []:
        t = str(t)
        if t.startswith("re:"):
            raw.append(f"(?i:{t[3:]})")
        elif caps_sensitive and _CAPS.match(t):
            plain.append(re.escape(t))
        else:
            plain.append(f"(?i:{re.escape(t)})")
    parts = []
    if plain:
        # Longest first, so "llms" wins over "llm" and "react native" over "react".
        plain.sort(key=lambda p: len(p.removeprefix("(?i:")), reverse=True)
        parts.append(r"(?<![A-Za-z0-9])(?:" + "|".join(plain) + r")(?![A-Za-z0-9])")
    parts.extend(raw)
    return re.compile("|".join(parts)) if parts else NEVER


def alternation(terms: list | tuple | None, caps_sensitive: bool = True) -> str:
    """The terms as one regex group (no word boundaries), to embed in a bigger pattern."""
    alts = []
    for t in terms or []:
        t = str(t)
        if t.startswith("re:"):
            alts.append(f"(?i:{t[3:]})")
        elif caps_sensitive and _CAPS.match(t):
            alts.append(re.escape(t))
        else:
            alts.append(f"(?i:{re.escape(t)})")
    alts.sort(key=len, reverse=True)
    return "(?:" + "|".join(alts) + ")" if alts else "(?!x)x"


def human_join(items: list[str], last: str = "or") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]
