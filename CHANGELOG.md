# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Sponsored places: `locations.sponsored_regions` and `sponsored_targets` count only when the post offers visa sponsorship or relocation. Refusals ("cannot sponsor", "must have the right to work") drop the job; remote jobs limited to those places alert with a warning (`sponsored_remote`).
- Region pack `eu` (EU countries plus Norway and Switzerland).

## [0.1.0] - 2026-10-14

First public release.

### Added
- Polling of Greenhouse, Lever, Ashby, Workable and SmartRecruiters boards, Workable search, Himalayas, Careerjet and LinkedIn guest search (LinkedIn and Careerjet off by default).
- Profile-driven filtering: tracks with presets (mobile, iOS, backend, frontend, full stack, data, AI/ML, DevOps, QA, product design), seniority, target locations in priority order, remote policy, work modes, work authorization, languages, salary floor with a static rate table, blocked keywords and companies.
- Region packs for the GCC, DACH, the UK and the US, and a GCC company list.
- Telegram alerts with Applied / Skip / undo buttons and `/today`, `/pause`, `/resume`, `/stats`.
- Optional Gemini AI scoring with a model fallback chain, a daily cap and a prompt built from the profile.
- Optional CV tailoring with Claude (or a paid Gemini key), with truth rules, a free-tier privacy guard and daily and monthly caps.
- `jobbot init`, `check-config`, `test-alert` and `ai-prompt` commands, with config validation that points to the file and line.
- systemd deployment script with settings from `deploy/.deploy.env`, Dockerfile and docker-compose, optional health check pings.
- `tools/discover_companies.py` with `--region` and `--countries`.
- Verified company lists for DACH, the UK and the US, and an example list that fits the example profile.
- `jobbot init --track --region --timezone --force`, which also fills in the search sources in config.yml.
- `once --dry-run --max-age-hours H` to test filters on older jobs; `-v` explains old jobs, `-vv` shows every drop; dry runs open the database read-only.
- Local-language support as region data (title aliases, title noise, years phrases, salary minimum markers), used by the DACH pack for German posts.
- Perk amounts (stipends, allowances, budgets) are never read as salary, and a job is only dropped for pay on a clear salary.
- CI with ruff and tests on Python 3.11, 3.12 and 3.13, plus a Docker build.
