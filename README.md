# job-alert-bot

[![CI](https://github.com/7pak/job-alert-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/7pak/job-alert-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Get a Telegram message within minutes of a matching job being posted, so you can apply while the post is fresh.**

job-alert-bot polls company job boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) and a few job search APIs, drops the jobs you cannot or do not want to get, scores the rest, and sends you a short alert. It runs on your own server for free. You set the roles, countries, seniority, languages, salary floor and polling speed in YAML files, with no Python edits.

**It never applies for you.** It finds jobs. You read them and apply yourself.

```
🟢 4.4/5  Backend Engineer, Acme
📍 Berlin · Hybrid · posted 12 min ago
✅ Python, PostgreSQL, Django, 2-4 yrs, ~70k EUR/yr
⚠️ German mentioned as a plus
[Open job] [Applied] [Skip]
```

## Features

- **Fast.** Company boards are polled every few minutes, straight from the ATS APIs, which usually show jobs before the big aggregators do.
- **Your targeting, as data.** Roles as tracks (with presets for mobile, iOS, backend, frontend, full stack, data, AI/ML, DevOps, QA and product design), seniority, target countries in priority order, remote policy, work authorization, languages, salary floor, blocked stacks and companies.
- **Hard filters that read the post.** "5+ years", "fluent German required", "US only", "nationals only", "graduate programme", low salaries.
- **Telegram control.** Buttons for Applied / Skip with undo, plus `/today`, `/pause`, `/resume` and `/stats`.
- **Optional AI check** (Gemini free tier) that reads the full post for hidden walls, with a fallback chain and a daily cap.
- **Optional CV tailoring** (Claude): a button that sends back your CV reworded for that job, using only facts already in it.
- **Polite by design.** Per-host request spacing, ETag caching, enforced minimum intervals, and long backoffs after HTTP 429.
- **Cheap to run.** Free-tier server, SQLite, a few small dependencies.

## What it never does

- It never applies, sends messages to recruiters or fills in forms.
- It never logs in anywhere or bypasses blocks and CAPTCHAs.
- It never polls faster than the enforced minimums, and it backs off when a site asks.
- It never sends your name, contact details or CV anywhere, except your CV to the model you chose when you tap ✍️ Tailor CV.

## What you fill in

Everything about you lives in a few files that `jobbot init` creates for you. They are gitignored, so they never end up in git or on GitHub. You never edit Python.

| What | File | Where to get it | Needed? |
|---|---|---|---|
| Telegram bot token | `.env` → `TELEGRAM_BOT_TOKEN` | Message **@BotFather** in Telegram, send `/newbot` | Yes |
| Your Telegram chat id | `.env` → `TELEGRAM_CHAT_ID` | Send your bot `/start`, then run `jobbot chat-id` | Yes |
| Roles, region, countries, languages, salary floor | `profile.yml` | `jobbot init` fills it in from your answers | Yes |
| Search words and which sources to use | `config.yml` | `jobbot init` fills it in from your roles and region | Yes |
| Companies to watch | `companies.yml` | `jobbot init` copies a checked list for your region | Yes |
| AI check of each post (Gemini) | `.env` → `GEMINI_API_KEY`, then `ai.enabled: true` in `config.yml` | Free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Optional |
| CV tailoring (Claude or Gemini) | `.env` → `ANTHROPIC_API_KEY` for Claude (or the `GEMINI_API_KEY` above), then `tailoring:` in `config.yml` (`enabled: true`, `provider: claude` or `gemini`, `model`) | Claude key at [console.anthropic.com](https://console.anthropic.com) | Optional |
| Your CV | `cv.md` or `cv.docx` next to `config.yml` ([docs/tailoring.md](docs/tailoring.md)) | Your own CV | Only for tailoring |
| Your server | `deploy/.deploy.env` → `JOBBOT_HOST=user@your-server-ip`, `JOBBOT_KEY=~/.ssh/id_ed25519` | Any Linux server you can SSH into | Only for 24/7 |

Then run `jobbot check-config`. It checks every file, tells you what is missing and points to the line of any mistake.

## Quickstart (about 15 minutes)

You need Python 3.11 or newer and a Telegram account.

**1. Install**

```bash
git clone https://github.com/7pak/job-alert-bot.git
cd job-alert-bot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

**2. Create your files**

```bash
jobbot init
```

It asks for your roles, region and timezone, then creates `profile.yml`, `config.yml` (search queries and locations filled in), `companies.yml` (a verified list for your region) and `.env` from the examples. Without a terminal, or to skip the questions:

```bash
jobbot init --track data --region us --timezone America/New_York
```

It never replaces a file you already have unless you add `--force`.

**3. Create the Telegram bot**

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Open your new bot and send it `/start`.
3. Run `jobbot chat-id` and copy the number into `.env` as `TELEGRAM_CHAT_ID`.
4. Run `jobbot test-alert`. A sample alert arrives.

**4. Make it yours**

Edit `profile.yml` (roles, locations, languages, salary) and `config.yml` (search queries). Then:

```bash
jobbot check-config                # validates everything, points to the line of any mistake
jobbot once --dry-run -v           # one real pass: prints what would be sent and why others were dropped
```

Adjust until the dry run looks right. `-v` lists dropped jobs with the reason (`-vv` also lists jobs that are not one of your roles at all), and the summary groups every drop reason. Jobs older than `max_job_age_hours` (48 h) never alert, so a first run may show none: add `--max-age-hours 336` to a dry run to test your filters on the last two weeks of jobs.

**5. Run it**

```bash
jobbot run
```

**6. Put it on a server (optional, for 24/7 alerts)**

Fill in `deploy/.deploy.env` (copy it from `deploy/.deploy.env.example`) with your server's address and SSH key, then:

```bash
scp deploy/setup_server.sh user@your-server-ip:/tmp/ && ssh user@your-server-ip 'sudo bash /tmp/setup_server.sh'   # once
bash deploy/deploy.sh --with-secrets    # first deploy, also copies .env
bash deploy/deploy.sh                   # every update after that
```

Prefer Docker? `mkdir -p data && docker compose up -d --build`. Full guide, with notes for Oracle Cloud, Google Cloud, AWS, Hetzner and Raspberry Pi: [docs/deployment.md](docs/deployment.md).

## Commands

| Command | What it does |
|---|---|
| `jobbot init` | Create your config files from the examples (`--track`, `--region`, `--timezone`, `--force`). |
| `jobbot check-config` | Validate every file and show what will run. |
| `jobbot once --dry-run -v` | One pass over all sources. Prints alerts and dropped jobs with reasons. Writes nothing (the database is opened read-only). |
| `jobbot once --dry-run -v --max-age-hours 336` | Same, but treats jobs from the last two weeks as new, to tune your filters. |
| `jobbot once --dry-run --source lever` | Same, one source only (repeatable). |
| `jobbot once` | One pass, sends alerts, saves to SQLite. |
| `jobbot run` | Runs forever, each source on its own timer and thread. |
| `jobbot stats` | Job counts by status. |
| `jobbot test-alert` / `test-telegram` | Send a sample alert / a test message. |
| `jobbot ai-models` / `ai-prompt` | List your Gemini models / print what the AI is told about you. |
| `python tools/discover_companies.py --region dach` | Find company boards hiring in your region. |

`python -m jobbot ...` works too.

In Telegram: `/today` (today's matches), `/pause` and `/resume` (alerts off and on, matches still saved), `/stats` (counts and source health).

## Presets

Pick role presets in `profile.yml` and override any field:

```yaml
region: dach              # gcc, dach, uk, us (presets/regions/)
tracks:
  - preset: backend        # mobile, ios, backend, frontend, fullstack, data, ai-ml, devops, qa, product-design
  - preset: data
    levels: [junior, mid]
```

Or write your own tracks from scratch. Everything is explained in [docs/configuration.md](docs/configuration.md).

## Sources

| Source | Type | Default interval |
|---|---|---|
| Greenhouse, Lever, Ashby | Company boards from `companies.yml` | 3 min |
| Workable, SmartRecruiters | Company boards from `companies.yml` | 10 min |
| Workable search | Every Workable employer, by keyword and location | 20 min |
| Himalayas | Remote jobs open to your country | 30 min |
| Careerjet | Aggregator, snippets only (off in the example) | 45 min |
| LinkedIn guest search | **Off by default**, against LinkedIn's terms, 429-prone. Your choice and your risk. | 15 min |

Read each site's terms before enabling it. Details, limits and how to add a source: [docs/sources.md](docs/sources.md).

## AI scoring (optional)

Turn on `ai.enabled` and add a free `GEMINI_API_KEY`. The model reads the full post of jobs that passed the keyword filter, drops hidden walls and gives the final score. If it is busy or out of quota, alerts still go out on the keyword score. The prompt is built from your profile; see it with `jobbot ai-prompt`. More: [docs/ai-scoring.md](docs/ai-scoring.md).

## CV tailoring (optional)

Turn on `tailoring.enabled` and every alert gets a **✍️ Tailor CV** button. The bot replies with your CV reworded for that job (Markdown, optional .docx), an optional cover letter and a list of changes. It only reorders and rewords facts already in your CV. It refuses providers that may train on your data unless you opt in, and has daily and monthly caps. With Claude Haiku 5.5 a CV costs a fraction of a cent. More: [docs/tailoring.md](docs/tailoring.md).

## FAQ and troubleshooting

**Telegram says `409 Conflict` in the logs.** Two copies of the bot are polling the same token (often one on your PC and one on the server). Stop one.

**LinkedIn: `rate limited by www.linkedin.com`.** LinkedIn answers 429 quickly. The bot backs off (up to `max_backoff_seconds`, and the backoff survives restarts). Lower the number of queries, raise the interval, or leave LinkedIn off.

**`board 'xyz' not found (404). Token may be stale.`** The company moved or renamed its board. Fix the token in `companies.yml` or set `enabled: false`. Run `tools/discover_companies.py` monthly to refresh your list.

**Gemini `HTTP 503` or "high demand".** Free-tier models get overloaded. The bot tries the next model in `ai.models` and, if all fail, alerts on the keyword score.

**No alerts at all.** Jobs older than `max_job_age_hours` never alert, so the first run is quiet on purpose. Run `jobbot once --dry-run -v --max-age-hours 336`: it treats the last two weeks as new and shows what would match and why the rest was dropped. Add `--ignore-seen` to include jobs already in your database.

**Too many alerts.** Raise `alert_min_score`, add `blocked.title_keywords`, narrow `levels`, or turn on AI scoring.

**Timezone for `/today`.** Set `timezone` in `profile.yml` to an IANA name such as `Europe/Berlin`.

## Privacy

Everything runs on your machine or server. Your config, profile, CV and database stay there (all gitignored). The bot sends job posts plus the anonymous parts of your profile to Gemini only if you enable AI scoring, and your CV to the model you chose only when you tap ✍️ Tailor CV. Note that the Gemini free tier may use prompts for training.

## Contributing

Issues and pull requests are welcome: new sources with public APIs, presets, region packs, notifiers and fixes. See [CONTRIBUTING.md](CONTRIBUTING.md). Report security problems privately, see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
