# Sources

Every source is a small module in `jobbot/sources/`. They only read public job listings, at a polite pace, and back off when a site says slow down (HTTP 429). Read each site's terms of use before you enable it: you run the bot, so you are the one making the requests.

| Source | What it reads | Default interval | Notes |
|---|---|---|---|
| Greenhouse | Public board API per company (`boards-api.greenhouse.io`) | 3 min | List call is small; the full post is fetched only for jobs that pass the title check. ETag cache: an unchanged board costs almost nothing. |
| Lever | Public postings API per company (`api.lever.co`, EU: `api.eu.lever.co`) | 3 min | Full posts in one call. |
| Ashby | Public job board API per company | 3 min | Includes compensation when published. |
| Workable | Public widget API per company | 10 min | Some big names are empty placeholder accounts. |
| SmartRecruiters | Public postings API per company, optional country filter | 10 min | An unknown company returns zero jobs, not 404. |
| Workable search | `jobs.workable.com` search across every Workable customer | 20 min | Finds employers you have never heard of. |
| Himalayas | Remote jobs open to one country | 30 min | Uses the country's ISO code. |
| Careerjet | Legacy public search API (aggregator) | 45 min | Snippets only, so hidden walls are often invisible. Off in the example config. It may need a free affiliate id and may be retired without notice. |
| LinkedIn | Public guest search pages | 15 min | **Off by default.** Automated access is against LinkedIn's terms of use, and it answers 429 after a handful of requests. If you turn it on, you accept that risk. The bot runs one query per cycle (round robin), waits 8 s between requests and backs off for hours after a 429. |

Not supported: boards that block plain HTTP (Bayt, GulfTalent, Naukrigulf, Dubizzle) and Indeed. See [research-notes.md](research-notes.md) for the full survey of free sources.

The minimum intervals in [configuration.md](configuration.md#sources) are enforced. Faster polling does not find jobs much sooner and does get IPs banned.

## How a source works

A source yields `Job` objects (`jobbot/models.py`):

```python
class Source(Protocol):
    name: str
    interval: float  # seconds between fetches

    def fetch(self) -> Iterable[Job]:
        """Yield every job currently listed. A failing company must not stop the rest."""

    def enrich(self, job: Job) -> None:
        """Fill in the description for a job with needs_detail=True."""
```

The worker runs each source in its own thread on its own timer:

1. `fetch()` lists jobs.
2. Jobs already in the database are skipped.
3. The title check runs (`JobFilter.precheck`). Only jobs that pass, and are recent, get `enrich()`, so detail pages are fetched sparingly.
4. The main thread runs the full filter, the optional AI check, and sends alerts.

Use the shared `Http` client (`jobbot/http.py`). It spaces out requests per host (`min_interval`), keeps one session per thread, retries 5xx, raises `RateLimited` on 429 (the worker then backs off, and the backoff survives restarts) and supports ETags with `get_json(url, cache=True)`.

## Adding a source

1. **Check the terms.** Only public, documented or clearly public endpoints. No logins, no CAPTCHAs, no bypassing blocks.
2. Write `jobbot/sources/<name>.py`:
   - A per-company ATS board: subclass `BoardSource` and implement `list_jobs(company)`. It gets the `companies.yml` entries and handles errors per board.
   - A search or feed: a plain class with `name`, `interval`, `fetch()` and `enrich()`. Catch errors per query, but re-raise `RateLimited`.
   - Set `posted_at` (UTC) when the source has it, `date_only=True` if it only gives a day, `needs_detail=True` if the description needs another call, `snippet_only=True` for short excerpts.
3. Register it in `jobbot/worker.py` (`BOARD_SOURCES` for boards, or `build_sources` for search sources).
4. Add its keys to `CONFIG_SPEC` in `jobbot/schema.py`, a minimum interval in `MIN_INTERVALS` (`jobbot/config.py`), and an example block in `config.example.yml`.
5. Add a test with a saved sample response (no network in tests) and a row to the table above.

Try it without sending anything:

```bash
jobbot once --dry-run -v --source <name>
```
