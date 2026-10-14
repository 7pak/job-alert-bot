# Configuration reference

You configure everything in four files. Each one is gitignored and has a committed `*.example` twin. `jobbot init` creates all four for you.

| File | What goes in it |
|---|---|
| `profile.yml` | Who you are and which jobs you want: roles, seniority, locations, languages, salary, blocked words. |
| `config.yml` | How the bot runs: sources and speed, notifier, AI scoring, CV tailoring, limits. |
| `companies.yml` | The company job boards to poll. |
| `.env` | Secrets only: Telegram token and chat id, API keys. |

If a file is missing, the bot uses its example and tells you so. After every edit, run:

```bash
jobbot check-config
```

It points to the file and line of each problem. Unknown keys are warnings (with a "did you mean" hint) and wrong types are errors. It never prints your secrets.

Set `JOBBOT_HOME=/some/folder` to keep these files outside the code folder. Relative paths (`db_path`, `cv_file`, ...) are then relative to that folder.

---

## profile.yml

### Word lists

Most keys are lists of words. Two rules cover all of them:

- A plain entry matches as a whole word and ignores case. `react native` matches "React Native" but not "reactive".
- An entry starting with `re:` is a regular expression, for example `"re:(?:python|go) developer"`. Use YAML quotes.

In location lists only, a short all-caps entry (`US`, `UK`, `EU`, `U.S.`) is matched case-sensitively, so "join us" is not read as the US.

### Top level

| Key | Default | Meaning |
|---|---|---|
| `name` | `my profile` | A label for the profile. Not your name. |
| `summary` | empty | Anonymous summary sent to the AI scorer. Never put your name or contact details here. |
| `years_experience` | empty | For your own reference and the AI summary. |
| `timezone` | `UTC` | IANA name (`Europe/Berlin`, `America/New_York`, `Asia/Dubai`). Used for "today" in `/today` and `/stats`. |
| `region` | none | A region pack from `presets/regions/` (`gcc`, `dach`, `uk`, `us`). It fills in `locations`, local rules and the salary currency. Anything you set yourself wins. |
| `skills.main`, `skills.secondary` | empty | Shown as positives in an alert when the post mentions them, written the way you list them. |
| `tracks` | required | The roles you want. See below. |

### tracks

A track is one kind of role. The first track whose title rules match a job wins, so put your favorite first.

Start from a preset and override any field:

```yaml
tracks:
  - preset: backend
  - preset: data
    levels: [junior, mid]
```

Presets: `mobile`, `ios`, `backend`, `frontend`, `fullstack`, `data`, `ai-ml`, `devops`, `qa`, `product-design`. Open the files in `presets/tracks/` to see what each one contains. You can also copy one into `profile.yml` and edit it freely.

| Key | Meaning |
|---|---|
| `name`, `label` | Id and display name. The label shows up in messages, e.g. "not a backend role". |
| `title_any` | One of these in the title is enough. |
| `title_with_role` | Needs a role word too (`role_words`: engineer, developer, ...). Example: `mobile` matches "Mobile Engineer" but not "Mobile Marketing Lead". |
| `title_exclude` | Never this track when the title has one of these. |
| `allow_title_words` | Remove words from the global `exclude_titles` for this track. The `data` preset allows `analyst`, the `qa` preset allows `qa` and `tester`. |
| `description_signals` | Pull a generic title ("Software Engineer", "Full Stack Engineer") into this track when the description mentions these at least `generic_titles.min_signals` times (default 2). |
| `levels` | Which levels you accept: `intern`, `junior`, `mid`, `senior`, `lead`. Without `senior`, "Senior ..." titles are dropped. With only `junior` (and `intern`), the post needs a junior title or at most `seniority.junior_max_years` years. With `lead`, `blocked_title_words` (staff, lead, head, ...) do not apply to this track. With `intern`, graduate titles and programs are allowed. |
| `weight` | Added to the base keyword score of 3.0. |
| `bonus` | Score bonuses: `{terms: [...], title: 0.5, description: 0.2}` adds `title` when the title has a term, otherwise `description` when the description has one. `{junior_title: 0.2}` rewards junior titles. |
| `avoid` | Stack rules, see below. |
| `note` | A warning added to every alert of this track, e.g. "General software role". |
| `fallback` | `true` puts the track after every other track and after the description signals. Use it for a broad catch-all such as "any junior software role". |
| `ai_description` | How the AI scorer should read this track. Generated from `label` and `levels` when empty. |

#### avoid rules

Drop jobs built on a stack you do not want, unless they also involve one you do. Each rule:

| Key | Meaning |
|---|---|
| `name` | Used in messages: "React Native role", "React Native only", "Mentions React Native". |
| `title_terms` | The title is this stack... |
| `title_ok_with` | ...unless it also names one of these. Otherwise the job is dropped... |
| `rescued_by` | ...unless one of these appears anywhere in the post: then it is kept with a warning. |
| `description_terms` | The description mentions this stack... |
| `description_ok_with` | ...dropped unless one of these appears anywhere. Leave it out (or `null`) to only add a warning. |

Example: Flutter and Android, but not React Native only and not iOS only.

```yaml
avoid:
  - name: React Native
    title_terms: [react native]
    title_ok_with: [flutter]
    description_terms: [react native]
    description_ok_with: [flutter, kotlin, android]
  - name: iOS
    title_terms: [ios, swift, swiftui]
    title_ok_with: [android, flutter, kotlin, cross-platform]
    rescued_by: [flutter]
```

### seniority

| Key | Default | Meaning |
|---|---|---|
| `max_years` | 5 | Drop posts that require this many years or more. |
| `junior_max_years` | 2 | For junior-only tracks: a junior title, or at most this many years required. |
| `comfortable_years` | 3 | Small score bonus when the post asks this many years or fewer. |
| `blocked_title_words` | staff, principal, lead, head, director, vp, vice president, chief, architect, manager | Titles with these words are dropped, except on tracks with the `lead` level. |
| `senior_title_words` | senior, sr, expert, experienced, ... | What counts as a senior title. |
| `junior_title_words` | junior, jr, associate, entry level, "Engineer I", ... | What counts as a junior title. |
| `graduate_title_words`, `graduate_description_patterns` | graduate, intern, trainee, campus, ... | Graduate programs and internships. |
| `allow_graduate_programs` | false | Keep graduate programs and internships. |

### locations

| Key | Default | Meaning |
|---|---|---|
| `home`, `home_country` | empty | Your city and country, used in messages and the AI prompt. |
| `region_name` | "your target locations" | Shown in messages such as "on-site outside DACH". Region packs set it. |
| `targets` | from the region pack | Where you want to work, in priority order: `[{name, terms, bonus}]`. A job whose location matches any term passes. The first matching target adds its `bonus` (default 0.2) to the score. |
| `remote` | `region` | `region`: remote jobs pass unless they are locked to a region that excludes you. `anywhere`: every remote job passes. `none`: remote jobs outside your targets are dropped. |
| `remote_ok_terms` | worldwide, anywhere, global, ... | Remote regions that include you ("Remote, EMEA" for someone in Europe). |
| `confirm_remote_terms` | empty | Remote-OK terms that still deserve a "confirm your country is allowed" warning, e.g. `emea`. |
| `region_lock_terms` | US, UK, EU, Europe, Canada, APAC, ... | "Must be based in the US" or "EU only" in a remote post drops it, unless the same sentence names one of your targets or remote-OK terms. |
| `work_modes` | on-site, hybrid, remote | Remove a mode you do not want. |
| `ai_description` | generated | How the AI scorer should read your location rules. |

To prefer one city or country, write your own `targets` (a list replaces the pack's list):

```yaml
locations:
  targets:
    - {name: Berlin, bonus: 0.4, terms: [berlin]}
    - {name: Germany, bonus: 0.2, terms: [germany, munich, hamburg, cologne]}
```

### work_authorization

| Key | Meaning |
|---|---|
| `citizenship`, `visa`, `note` | Optional, for the AI scorer ("Lives in Berlin on a Blue Card."). |
| `nationals_only_patterns` | Regexes. A post that matches is dropped, e.g. `"citizens only"`, `"security clearance"`, `"emirati[sz]ation"`. The `gcc` pack ships a full list. |
| `nationals_examples` | Short examples for the AI prompt. |

### languages

```yaml
languages:
  - {name: english, level: fluent}
  - {name: german, level: B1}
```

A post that requires any other language is dropped. "German is a plus" only adds a warning. "English or French" counts as fine because you speak one of them. A post written in another language (when the source reports it) is dropped too.

### salary

```yaml
salary: {min: 55000, currency: EUR, period: year}
```

`period` is `month` or `year`. Salaries in other currencies are converted with the static `currency_rates` table in `config.yml`. `min: 0` turns the floor off but still shows the salary in alerts.

A job is only dropped for pay when the post clearly states a salary: a pay word (salary, compensation, pay, base, ...) or a range. A post without a salary always passes. Perks are never read as salary: amounts next to words like stipend, allowance, budget, reimbursement, home office, internet, card, bonus or equity are ignored.

### blocked

```yaml
blocked:
  title_keywords: [salesforce, sap, wordpress]
  companies: [Some Agency]
```

### ai

| Key | Meaning |
|---|---|
| `soft_issues` | Things the AI should only warn about, never drop for. |
| `notes` | Extra instructions for the AI, one paragraph. |

See exactly what the AI receives with `jobbot ai-prompt`.

### Advanced keys

`role_words`, `exclude_titles`, `exclude_titles_unless_engineering`, `engineering_titles` and `generic_titles` (`titles`, `exclude`, `min_signals`) control the generic title logic. The defaults in `jobbot/profile.py` work for most people.

### Posts in other languages

Region packs can teach the filter local wording, without code. The `dach` pack is the example:

| Key | Meaning |
|---|---|
| `title_aliases` | Words rewritten in titles before matching: `{entwickler: developer, ingenieur: engineer}`. "Python-Entwickler" is read as "Python developer", so the English track presets work. |
| `title_noise` | Regexes removed from titles before matching, e.g. gender markers like `(m/w/d)`. |
| `seniority.years_patterns` | Extra "years of experience" phrases as regexes, group 1 = years (group 2 = optional upper bound), e.g. "Mindestens 7 Jahre Berufserfahrung". |
| `salary.minimum_markers` | Words that mark a stated salary as a legal minimum, not the offer ("overpayment", "Überzahlung", "Kollektivvertrag"). Such a post is never dropped for pay; it gets a warning instead. |

English "N+ years" needs words such as "experience" next to it, except a bare "7+ years." at the end of a requirement line. "For 20+ years" (company history) is ignored.

### How a job is checked

The first rule that fails gives the drop reason you see in `jobbot once --dry-run -v`.

1. Blocked company or title keyword.
2. Track: title rules in track order, then description signals for generic titles, then fallback tracks. No track: "not a ... role".
3. Title checks: graduate titles, blocked seniority words, and senior titles on tracks without `senior` (only when the title is not a generic one such as "Senior Software Engineer", which may still turn out to be a match from its description).
4. Graduate programs in the description, nationals-only patterns, languages, the track's `avoid` rules.
5. Work mode, location and remote rules.
6. Years required (`max_years`), then senior titles on tracks without `senior` (the generic titles from step 3), then junior-only rules.
7. Salary floor.
8. Score: 3.0 + track `weight` + `bonus` + location `bonus` + 0.2 for comfortable years, minus 0.4 for a senior title and 0.2 for an unclear location. Capped to 1 to 5.

So "Senior Software Engineer" in a city outside your targets is reported as a location drop, because step 5 comes before step 6.

A job alerts at `alert_min_score` (config.yml). With AI scoring on, jobs at `prefilter_min_score` or more go to the AI, which can drop them or give the final score.

### Example: data analyst in the US

```yaml
name: data in the US
timezone: America/Chicago
region: us
tracks:
  - preset: data
    levels: [junior, mid]
languages: [english]
salary: {min: 70000, currency: USD, period: year}
locations:
  home: Chicago
  home_country: the US
  remote: region
```

---

## config.yml

| Key | Default | Meaning |
|---|---|---|
| `poll_seconds` | 180 | Default interval for company boards (minimum 60). |
| `max_job_age_hours` | 48 | Jobs posted earlier are saved but never alerted. The first run does not flood you. |
| `alert_min_score` | 3.0 | Keyword score needed for an alert. |
| `max_alerts_per_cycle` | 15 | Flood guard per source run. The rest wait for the next run. |
| `max_backoff_seconds` | 14400 | Longest pause after HTTP 429. Backoffs survive restarts. |
| `request_timeout_seconds` | 30 | HTTP timeout for sources. |
| `db_path` | `data/jobs.db` | SQLite database. |
| `profile_file`, `companies_file` | `profile.yml`, `companies.yml` | Paths, e.g. `presets/companies/gcc.yml`. |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`. |
| `notifier` | `telegram` | `telegram`, or `console` to print alerts (testing). |
| `healthcheck_url` | empty | Pinged (HTTP GET) after good runs, at most every 5 minutes. Works with healthchecks.io and similar. |
| `currency_rates` | built-in table in USD | `{USD: 1, EUR: 1.08, ...}`: the value of one unit in a common base. Only ratios matter. |

### sources

Every source accepts `enabled` (default true) and `interval_seconds`. The bot enforces a minimum interval so nobody gets their IP banned:

| Source | Extra keys | Minimum interval |
|---|---|---|
| `greenhouse`, `lever`, `ashby` | `workers` (parallel boards, default 6) | 60 s |
| `workable`, `smartrecruiters` | `workers` | 120 s |
| `workable_search` | `queries`, `locations`, `pages` (default 2) | 300 s |
| `himalayas` | `queries`, `country` (ISO code, e.g. `DE`) | 300 s |
| `careerjet` | `queries`, `locales` (e.g. `de_DE`, `en_GB`), `affiliate_id` | 600 s |
| `linkedin` | `queries` (`{keywords, location}`), `time_window`, `min_request_gap_seconds`, `city_fix` | 600 s |

Board sources read their boards from `companies.yml`. Details and terms of use per source: [sources.md](sources.md).

### ai

See [ai-scoring.md](ai-scoring.md). Keys: `enabled`, `provider` (gemini), `models` (fallback chain), `timeout_seconds`, `min_score`, `prefilter_min_score`, `max_calls_per_day`, `min_gap_seconds`, `max_desc_chars`.

### tailoring

See [tailoring.md](tailoring.md). Keys: `enabled`, `provider`, `model`, `cv_file`, `docx`, `cover_letter`, `max_per_day`, `max_cost_per_month_usd`, `price_per_mtok`, `allow_free_tier`, `max_desc_chars`.

---

## companies.yml

```yaml
greenhouse:
  - {name: Elastic, token: elastic}
lever:
  - {name: Palantir, token: palantir}
  - {name: Some EU Co, token: someco, host: api.eu.lever.co}
ashby:
  - {name: OpenAI, token: openai}
workable:
  - {name: Salla, token: salla}
smartrecruiters:
  - {name: Delivery Hero, token: deliveryhero, countries: [ae, sa]}
```

The token is the board id in the careers URL (`boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>`). Add `enabled: false` to pause a board. A board that returns 404 is logged once as "token may be stale".

Find boards for your region with `python tools/discover_companies.py --region dach` or `--countries "Germany,Berlin"`. Ready-made lists live in `presets/companies/`.

---

## .env

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_API_KEY=        # optional, AI scoring
ANTHROPIC_API_KEY=     # optional, CV tailoring with Claude
```
