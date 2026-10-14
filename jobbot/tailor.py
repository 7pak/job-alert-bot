"""CV tailoring (optional, off by default).

When `tailoring.enabled` is true, alerts get a [✍️ Tailor CV] button. A tap sends the job post and
your CV to the model and the bot replies with a tailored CV (Markdown, plus .docx if python-docx is
installed) and a short list of changes. It never applies anywhere. When disabled, nothing here runs
and your CV is never read.

A CV is personal data, so a provider that may train on prompts (the Gemini free tier) is refused
unless `allow_free_tier: true`. Claude goes through the official `anthropic` SDK
(`pip install .[claude]`).
"""
from __future__ import annotations

import io
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .http import Http

log = logging.getLogger(__name__)

SYSTEM = """\
You tailor a CV to one job post for the candidate who owns the CV.

Truth rules. They are not negotiable:
1. Use only facts that are already in the CV. You may reorder, reword, shorten and emphasize them.
2. Never invent or inflate skills, tools, employers, job titles, dates, degrees, certifications, projects or metrics.
3. Never add a skill or keyword only because the job asks for it. If the job needs something the CV does not show, leave it out of the CV and list it under GAPS.
4. Keep names, employers, dates, links and contact details exactly as written.
5. If you are not sure a change stays true to the CV, do not make it, or mark it with [CHECK] in the CV and explain why under CHANGES.
6. Write plain, natural English. No em-dashes.

Answer with exactly these sections, each header on its own line:
=== CHANGES ===
3 to 8 short bullets: what you changed and why. Then a line "GAPS:" with bullets for job requirements the CV does not show (or "none").
=== CV ===
The full tailored CV in Markdown.
=== COVER LETTER ===
Only when asked. Under 250 words, only facts from the CV.
"""

_SECTION = re.compile(r"^===\s*(CHANGES|CV|COVER LETTER)\s*===\s*$", re.M)


class TailorError(Exception):
    """Shown to the user in the chat."""


@dataclass
class TailorResult:
    cv: str
    changes: list[str]
    cover_letter: str = ""
    cost_usd: float = 0.0
    model: str = ""


class TextModel(Protocol):
    name: str
    may_train_on_data: bool   # free tiers that may use prompts for training

    def complete(self, system: str, user: str) -> tuple[str, float]:
        """Return the answer text and its cost in USD."""
        ...


class ClaudeModel:
    """Claude through the official anthropic SDK."""

    may_train_on_data = False

    def __init__(self, api_key: str, model: str, price_in: float, price_out: float, max_tokens: int = 16000):
        try:
            import anthropic
        except ImportError:
            raise TailorError("The anthropic package is not installed. Run: pip install .[claude]") from None
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key or None, timeout=180.0)
        self.name = model
        self.price_in, self.price_out = price_in, price_out
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> tuple[str, float]:
        a = self._anthropic
        try:
            resp = self.client.messages.create(model=self.name, max_tokens=self.max_tokens, system=system,
                                               messages=[{"role": "user", "content": user}])
        except a.AuthenticationError:
            raise TailorError("Claude rejected the API key. Check ANTHROPIC_API_KEY in .env.") from None
        except a.RateLimitError:
            raise TailorError("Claude is rate limiting this key. Try again in a minute.") from None
        except a.APIStatusError as exc:
            raise TailorError(f"Claude API error {exc.status_code}: {exc.message[:200]}") from None
        except a.APIConnectionError:
            raise TailorError("Could not reach the Claude API. Check the server's network.") from None
        cost = (resp.usage.input_tokens * self.price_in + resp.usage.output_tokens * self.price_out) / 1e6
        if resp.stop_reason == "refusal":
            raise TailorError("The model declined this request.")
        if resp.stop_reason == "max_tokens":
            raise TailorError("The answer was cut off. Try a shorter CV or job post.")
        return "".join(b.text for b in resp.content if b.type == "text"), cost


class GeminiModel:
    """Gemini via REST. The free tier may use prompts for training, so it needs allow_free_tier."""

    may_train_on_data = True
    API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, price_in: float, price_out: float, http: Http | None = None):
        self.api_key = api_key
        self.name = model
        self.price_in, self.price_out = price_in, price_out
        self.http = http or Http(timeout=180, retries=0)

    def complete(self, system: str, user: str) -> tuple[str, float]:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}]}
        try:
            data = self.http.post_json(self.API.format(model=self.name), body, headers={"x-goog-api-key": self.api_key})
        except Exception as exc:
            raise TailorError(f"Gemini request failed: {str(exc)[:200]}") from None
        parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        usage = data.get("usageMetadata") or {}
        cost = (usage.get("promptTokenCount", 0) * self.price_in
                + usage.get("candidatesTokenCount", 0) * self.price_out) / 1e6
        return "".join(p.get("text", "") for p in parts), cost


def parse_answer(text: str) -> tuple[list[str], str, str]:
    """(changes, cv, cover_letter) from the model's sectioned answer."""
    sections: dict[str, str] = {}
    marks = list(_SECTION.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections[m.group(1)] = text[m.end():end].strip()
    cv = sections.get("CV", "").strip()
    if not cv:
        raise TailorError("The model did not return a CV section. Try again.")
    changes = [ln.strip().lstrip("-* ").strip() for ln in sections.get("CHANGES", "").splitlines() if ln.strip()]
    return changes, cv, sections.get("COVER LETTER", "").strip()


def read_cv(path: Path) -> str:
    if path.is_dir():
        raise TailorError(f"{path} is a folder, not your CV file. Set tailoring.cv_file to the file inside it.")
    if not path.exists():
        raise TailorError(f"CV file not found: {path.name}. Set tailoring.cv_file in config.yml.")
    if path.suffix.lower() == ".docx":
        try:
            import docx
        except ImportError:
            raise TailorError("Reading a .docx CV needs python-docx. Run: pip install .[docx]") from None
        lines = []
        for para in docx.Document(str(path)).paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            if style.startswith("heading"):
                level = int(style.split()[-1]) if style.split()[-1].isdigit() else 2
                lines.append("#" * min(level, 3) + " " + text)
            elif "list" in style:
                lines.append(f"- {text}")
            else:
                lines.append(text)
        return "\n".join(lines)
    return path.read_text(encoding="utf-8")


def markdown_to_docx(md: str) -> bytes | None:
    """A plain .docx from simple Markdown (headings, bullets, bold). None when python-docx is missing."""
    try:
        import docx
    except ImportError:
        return None
    doc = docx.Document()
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if m := re.match(r"^(#{1,3})\s+(.*)", line):
            doc.add_heading(m.group(2).strip(), level=len(m.group(1)))
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)", line)
        para = doc.add_paragraph(style="List Bullet" if bullet else None)
        for i, chunk in enumerate(re.split(r"\*\*(.+?)\*\*", bullet.group(1) if bullet else line)):
            para.add_run(chunk).bold = i % 2 == 1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40] or "job"


@dataclass
class Tailor:
    cfg: dict                       # the tailoring block of config.yml
    model: TextModel
    cv_text: str
    store: object                   # JobStore, for the daily and monthly counters
    out_dir: Path | None = None     # also save files here (inside data/, writable under systemd)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _keys(self) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        return f"tailor_calls:{now:%Y-%m-%d}", f"tailor_cost:{now:%Y-%m}"

    def blocked_reason(self) -> str | None:
        """Why a tailoring request must not run now, or None."""
        if self.model.may_train_on_data and not self.cfg.get("allow_free_tier"):
            return ("CV tailoring is off for this provider: the Gemini free tier may use prompts for training, "
                    "and a CV is personal data. Use provider: claude, or set allow_free_tier: true if your key "
                    "is on a paid plan.")
        day_key, month_key = self._keys()
        if float(self.store.get_setting(day_key, "0") or 0) >= self.cfg.get("max_per_day", 10):
            return f"Daily tailoring limit reached ({self.cfg.get('max_per_day')}). Try again tomorrow."
        cap = float(self.cfg.get("max_cost_per_month_usd", 0) or 0)
        if cap and float(self.store.get_setting(month_key, "0") or 0) >= cap:
            return f"Monthly tailoring budget reached (${cap:.2f}). Raise max_cost_per_month_usd to continue."
        return None

    def run(self, job: dict) -> TailorResult:
        """job: {title, company, location, url, description}."""
        if reason := self.blocked_reason():
            raise TailorError(reason)
        desc = (job.get("description") or "").strip()
        if not desc:
            raise TailorError("No job text was saved for this alert, so it cannot be tailored.")
        desc = desc[: int(self.cfg.get("max_desc_chars", 15000))]
        cover = bool(self.cfg.get("cover_letter"))
        user = (
            f"Job post\nTitle: {job.get('title')}\nCompany: {job.get('company')}\n"
            f"Location: {job.get('location') or 'not given'}\nURL: {job.get('url')}\n\n{desc}\n\n"
            f"CV (Markdown):\n{self.cv_text}\n\n"
            + ("Also write the cover letter section." if cover else "Do not write a cover letter section.")
        )
        day_key, month_key = self._keys()
        with self._lock:  # one at a time keeps the caps exact
            self.store.add_to_setting(day_key, 1)
            text, cost = self.model.complete(SYSTEM, user)
            self.store.add_to_setting(month_key, cost)
        changes, cv, letter = parse_answer(text)
        return TailorResult(cv=cv, changes=changes, cover_letter=letter if cover else "", cost_usd=cost,
                            model=self.model.name)

    def files(self, result: TailorResult, job: dict) -> list[tuple[str, bytes]]:
        base = f"CV - {_slug(job.get('company') or '')} - {_slug(job.get('title') or '')}"
        out = [(f"{base}.md", result.cv.encode("utf-8"))]
        if self.cfg.get("docx") and (data := markdown_to_docx(result.cv)):
            out.append((f"{base}.docx", data))
        if result.cover_letter:
            out.append((f"Cover letter - {_slug(job.get('company') or '')}.md", result.cover_letter.encode("utf-8")))
            if self.cfg.get("docx") and (data := markdown_to_docx(result.cover_letter)):
                out.append((f"Cover letter - {_slug(job.get('company') or '')}.docx", data))
        if self.out_dir:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            for name, data in out:
                (self.out_dir / name).write_bytes(data)
        return out


def start_tailor(cfg: dict, store) -> Tailor | None:
    """build_tailor for `jobbot run`: a setup problem is logged and the bot runs without
    tailoring, so an optional feature can never crash-loop the service."""
    try:
        tailor = build_tailor(cfg, store)
    except Exception as exc:
        log.error("CV tailoring is OFF for this run: %s", exc if isinstance(exc, TailorError) else repr(exc))
        return None
    if tailor and (reason := tailor.blocked_reason()):
        log.warning("CV tailoring: %s", reason)
    return tailor


def build_tailor(cfg: dict, store) -> Tailor | None:
    """None when tailoring is disabled: then the CV is never read."""
    t = cfg.get("tailoring") or {}
    if not t.get("enabled"):
        return None
    price = t.get("price_per_mtok") or {}
    if t.get("provider") == "gemini":
        model: TextModel = GeminiModel(cfg.get("gemini_api_key", ""), t["model"], price.get("input", 0),
                                       price.get("output", 0))
    else:
        model = ClaudeModel(cfg.get("anthropic_api_key", ""), t["model"], price.get("input", 0.10),
                            price.get("output", 0.50))
    cv = read_cv(Path(t["cv_path"]))
    out_dir = Path(cfg["db_path"]).parent / "tailored"
    return Tailor(t, model, cv, store, out_dir)
