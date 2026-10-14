# Contributing

Thanks for helping. Small, focused pull requests are the easiest to review.

## Setup

```bash
git clone https://github.com/7pak/job-alert-bot.git
cd job-alert-bot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Checks

```bash
ruff check .
python -m unittest discover -s tests -t .
```

Both run in CI on Python 3.11, 3.12 and 3.13. Tests never touch the network or need secrets: use fakes and saved sample responses. Tests load fixture profiles from `tests/fixtures/`, never your own `profile.yml`.

## Style

- Small modules, plain `requests`, dataclasses and `Protocol` interfaces. No heavy frameworks.
- New dependencies only when they are clearly worth it. Optional features go in an extra (`pip install .[name]`).
- Comments explain why, not what. Plain English, no em-dashes.
- Anything user-specific is data in `profile.yml`, `config.yml` or a preset, never code.
- The bot never applies for anyone. Pull requests that submit applications or contact recruiters will not be merged.

## Adding a source

See [docs/sources.md](docs/sources.md#adding-a-source). Only public endpoints, no logins, no CAPTCHA bypassing, polite intervals. Include a test with a saved sample response.

## Adding a preset

- A role: `presets/tracks/<name>.yml` with one track (see the existing ones and [docs/configuration.md](docs/configuration.md#tracks)). Add its name and a matching title to `tests/test_profiles.py` (`Presets`).
- A region: `presets/regions/<name>.yml` with `locations` (targets, remote-OK terms), and optionally `work_authorization` and `salary.currency`.
- A company list: `presets/companies/<region>.yml`, ideally built with `tools/discover_companies.py --region <name>`.

## Adding a notifier

Notifiers implement the `Notifier` protocol in `jobbot/notify/__init__.py`:

```python
class Notifier(Protocol):
    def send_text(self, text: str) -> str | None: ...
    def send_alert(self, alert: Alert) -> str | None: ...   # raise on failure, the job is retried next cycle
```

Add the module in `jobbot/notify/`, a name in `NOTIFIERS` (`jobbot/config.py`), the wiring in `make_notifier` (`jobbot/__main__.py`), docs and a test. Telegram is the only notifier with buttons and commands; others can be send-only.

## Reporting bugs

Open an issue with the output of `jobbot check-config` and the relevant log lines. Never paste tokens, keys, chat ids or your CV.
