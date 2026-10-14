"""Salary parsing with a static exchange-rate table (no paid FX API).

`currency_rates` in config.yml gives how much one unit of each currency is worth in a common
base (any base works, only the ratios matter). Currencies missing from the table are ignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Approximate values in USD. Edit them in config.yml (currency_rates) if you care about precision.
DEFAULT_RATES = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.12, "CAD": 0.73, "AUD": 0.66, "INR": 0.012,
    "AED": 0.2725, "SAR": 0.2667, "QAR": 0.2747, "KWD": 3.25, "BHD": 2.65, "OMR": 2.6, "EGP": 0.02,
    "PLN": 0.25, "SEK": 0.095, "NOK": 0.093, "DKK": 0.145, "SGD": 0.74, "JPY": 0.0067,
}
# Symbols and local names that map to a currency code.
SYMBOLS = {
    "$": "USD", "us$": "USD", "€": "EUR", "£": "GBP", "₹": "INR",
    "dh": "AED", "dhs": "AED", "dirham": "AED", "dirhams": "AED",
}
# Sanity bounds, in USD per month: a smaller number is not a salary ("$5 voucher"), a bigger
# monthly-looking number is really yearly.
MIN_PAY_USD = 272.5
YEARLY_ABOVE_USD = 21_800

_AMT = r"(?P<a>\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*(?P<ak>k)?"
# Words that make a sentence about money look like pay at all.
SALARY_CONTEXT = re.compile(
    r"salary|compensation|pay|package|base|remuneration|ote|per month|per year|annual", re.I)
# Words that make it clearly about salary, so a low figure may drop the job.
PAY_WORD = re.compile(
    r"(?<![a-z])(?:salary|salaries|compensation|pay|remuneration|base|package|wages?|ote|ctc)(?![a-z])", re.I)
# Perks are money too, but not salary: "home office stipend: $100 per month".
PERK = re.compile(
    r"(?<![a-z])(?:stipends?|allowances?|budgets?|reimburse\w*|wellness|learning|home[- ]office|internet"
    r"|phone|mobile plan|gym|meals?|lunch|cards?|per diem|bonus(?:es)?|equity|stock|relocation|vouchers?)(?![a-z])",
    re.I)
CLAUSE_END = re.compile(r"[,;+(]|(?<![a-z])(?:plus|and|with)(?![a-z])", re.I)
PERIOD_MONTH = re.compile(r"^\W{0,3}(?:per month|a month|monthly|/\s?mo|/\s?month|pm\b|p\.m\.)", re.I)
PERIOD_YEAR = re.compile(r"^\W{0,3}(?:per year|a year|per annum|annually|annual|yearly|/\s?yr|/\s?year|p\.a\.|pa\b)", re.I)
PERIOD_HOUR = re.compile(r"^\W{0,3}(?:per hour|an hour|hourly|/\s?h(?:ou)?r)", re.I)


@dataclass
class Pay:
    monthly: float   # in the target currency
    clear: bool      # a pay word or a range: safe to drop a job on


def is_perk(m: re.Match, sent: str) -> bool:
    """True when the amount belongs to a perk named right before or right after it."""
    before = sent[max(0, m.start() - 40): m.start()]
    after = sent[m.end(): m.end() + 40]
    if cut := CLAUSE_END.search(after):
        after = after[: cut.start()]
    perks = list(PERK.finditer(before))
    if perks:
        pays = list(PAY_WORD.finditer(before))
        if not pays or pays[-1].start() < perks[-1].start():
            return True
    return bool(PERK.search(after))


class Money:
    def __init__(self, rates: dict | None = None):
        self.rates = {str(k).upper(): float(v) for k, v in (rates or DEFAULT_RATES).items()}
        self.aliases = {code.lower(): code for code in self.rates}
        self.aliases.update({s: c for s, c in SYMBOLS.items() if c in self.rates})
        cur = "|".join(sorted((re.escape(a) for a in self.aliases), key=len, reverse=True))
        amt2 = rf"(?:\s*(?:-|–|to)\s*(?:{cur})?\s*(?P<b>\d{{1,3}}(?:[,.]\d{{3}})+|\d+(?:\.\d+)?)\s*(?P<bk>k)?)?"
        self.patterns = [
            re.compile(rf"(?P<cur>{cur})\s?" + _AMT + amt2, re.I),
            re.compile(_AMT + amt2 + rf"\s?(?P<cur>{cur})", re.I),
        ]

    def known(self, code: str) -> bool:
        return code.upper() in self.rates

    def convert(self, amount: float, frm: str, to: str) -> float:
        return amount * self.rates[frm.upper()] / self.rates[to.upper()]

    def _to_usd(self, amount: float, code: str) -> float:
        return self.convert(amount, code, "USD") if "USD" in self.rates else amount

    def read(self, m: re.Match, sent: str, target: str) -> Pay | None:
        """Monthly pay in `target` currency for one regex match, or None if it is not a salary."""
        def num(s: str | None, k: str | None) -> float | None:
            if not s:
                return None
            s = re.sub(r"[,.](?=\d{3}(?:\D|$))", "", s)
            try:
                n = float(s)
            except ValueError:
                return None
            return n * 1000 if k else n

        upper = num(m.group("b"), m.group("bk")) or num(m.group("a"), m.group("ak"))
        code = self.aliases.get(m.group("cur").lower())
        if not upper or code is None or is_perk(m, sent):
            return None
        amount = self.convert(upper, code, target)
        usd = self._to_usd(upper, code)
        after = sent[m.end(): m.end() + 20]
        if PERIOD_HOUR.search(after):
            monthly, usd_monthly = amount * 160, usd * 160
        elif PERIOD_MONTH.search(after):
            monthly, usd_monthly = amount, usd
        elif PERIOD_YEAR.search(after):
            monthly, usd_monthly = amount / 12, usd / 12
        elif SALARY_CONTEXT.search(sent):
            yearly = usd > YEARLY_ABOVE_USD
            monthly, usd_monthly = (amount / 12, usd / 12) if yearly else (amount, usd)
            if usd < MIN_PAY_USD:
                return None  # "$50M raised", "$5 voucher", and so on
        else:
            return None
        if usd_monthly < MIN_PAY_USD:
            return None
        return Pay(monthly, bool(PAY_WORD.search(sent) or m.group("b")))
