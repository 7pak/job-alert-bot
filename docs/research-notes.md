# Research notes: free job-listing APIs and feeds

> Snapshot from 2026-10-14. Endpoints and limits change, so treat this as a starting point and re-check before you build on it. The live sources the bot uses are documented in [sources.md](sources.md).

Live checks done on 2026-10-14 from a residential line in the Gulf, plain `curl` / Python `urllib`, browser User-Agent, no login, no keys, about 1 request per second per host. "Verified" means the endpoint returned real job data that day. Anything not confirmed is marked unverified.

The checks focused on software roles in the GCC (UAE, KSA, Qatar, Kuwait, Bahrain, Oman) and remote roles open to the region, so the "GCC relevance" column reflects that. The API notes apply anywhere.

## (a) Summary table

| Source | Type | Free? Key? | Verified today | Description | Posted timestamp | GCC relevance | Notes |
|---|---|---|---|---|---|---|---|
| Greenhouse job board API | ATS, per company, JSON | Free, no key | yes, 200 | yes (`content=true`) | yes, `first_published` + `updated_at` | high | Careem, Tamara, BRKZ, Bybit, Deliveroo, OKX. EU-hosted boards are readable on the normal US host |
| Lever postings API | ATS, per company, JSON | Free, no key | yes, 200 | yes | yes, `createdAt` (epoch ms) | high | Aldar, Binance, Crypto.com, Palantir. EU host exists, not confirmed with a real EU tenant |
| Ashby posting API | ATS, per company, JSON | Free, no key | yes, 200 | yes (html + plain) | yes, `publishedAt` | high | Ziina, Lean, Kraken, Cohere, OpenAI |
| Workable widget API | ATS, per company, JSON | Free, no key | yes, 200 (after 302) | yes with `details=true` | date only, `published_on` | high | Salla, Foodics, Lucidya, Mozn. Behind Cloudflare |
| Workable v3 jobs (POST) | ATS, per company, JSON | Free, no key | yes, 200 | no (use v2 detail) | `published` (midnight UTC, date only) | high | Paginated with `nextPage` token |
| Workable job search (jobs.workable.com) | Cross-company search, JSON | Free, no key | yes, 200 | yes | yes, `created` ISO | high | Searches every Workable customer by keyword + location. Best Workable source |
| SmartRecruiters postings API | ATS, per company, JSON | Free, no key | yes, 200 | detail call only | yes, `releasedDate` | med-high | Delivery Hero (talabat, InstaShop, HungerStation), Namshi. Has `country=ae` filter |
| Teamtailor RSS | ATS, per company, RSS | Free, no key | yes, 200 | yes | yes, `pubDate` | med | Property Finder (32 jobs) |
| Oracle HCM Candidate Experience | ATS, per company, JSON | Free, no key | yes, 200 | short text in list | yes, `PostedDate` (date) | med-high | Emirates NBD (30 jobs). Common with GCC banks and gov |
| Workday CXS | ATS, per tenant, JSON (POST) | Free, no key | yes, 200 | detail call only | list: "Posted Today" text; detail: `startDate` | high for big corps | Mastercard Dubai search = 13 jobs |
| BambooHR careers | ATS, per company, JSON | Free, no key | yes, 200 | detail call only | detail only, `datePosted` | med | 360VUZ, Fasset, Tumodo |
| Recruitee | ATS, per company, JSON | Free, no key | yes, 200 (bunq) | yes | yes, `published_at` | low | No GCC company found |
| Breezy HR | ATS, per company, JSON | Free, no key | yes, 200 | no | yes, `published_date` | low | No GCC company found |
| Personio XML | ATS, per company, XML | Free, no key | yes, 200 (personio) | field exists, empty in test | `createdAt` | low | DACH-focused |
| JazzHR | ATS, HTML only | n/a | no | n/a | n/a | low | No public JSON/RSS found |
| Zoho Recruit | ATS | n/a | no (unverified) | n/a | n/a | low | Could not find a public JSON feed or a GCC test tenant |
| Taleo | ATS | n/a | not tested | n/a | n/a | low | Legacy HTML, skip |
| Careerjet (legacy public API) | Aggregator, JSON | Free, no key, needs `Referer` header | yes, 200 | snippet | yes, `date` (day precision) | high | `locale_code=en_AE` works. Found a talabat Flutter role. v4 API needs a key |
| LinkedIn guest endpoints | Aggregator, HTML fragments | Free, no key | yes, 200, then 429 | yes (detail endpoint) | date + "3 hours ago" | high | Rate-limited hard: 429 after about 7 calls in 30 min |
| Himalayas | Remote board, JSON | Free, no key | yes, 200 | yes | yes, `pubDate` (epoch) | med | `country=AE` returns 641 jobs open to UAE |
| Remote OK | Remote board, JSON | Free, no key | yes, 200 | yes | yes, `epoch` | low-med | 99 newest jobs only, backlink required by ToS |
| We Work Remotely RSS | Remote board, RSS | Free, no key | yes, 200 | yes | yes, `pubDate` | low-med | `<region>` field per item |
| Working Nomads | Remote board, JSON | Free, no key | yes, 200 | yes | yes, `pub_date` | low-med | ~51 latest jobs |
| Jobicy | Remote board, JSON | Free, no key | yes, 200 | yes | yes, `pubDate` | low-med | Has `geo=united-arab-emirates` slug |
| HN Who's Hiring (Algolia) | Forum thread, JSON | Free, no key | yes, 200 | yes (comment text) | yes, `created_at_i` | med (remote, AI) | Oct 2026 thread = 313 top-level comments |
| HN jobstories (Firebase) | YC jobs, JSON | Free, no key | yes, 200 | via item call | yes, `time` | low | US-heavy |
| Remotive | Remote board, JSON | Free, no key | yes, 200 | yes | yes, `publication_date` | low | Returned the same 16 jobs for every query today. 24h delay, max 4 calls/day |
| Arbeitnow | Board, JSON | Free, no key | yes, 200 | yes | yes, `created_at` | low | Germany-focused |
| The Muse | Board, JSON | Free, no key | yes, 200 | yes | yes, `publication_date` | low | Dubai location filter did not return Dubai jobs |
| Jooble | Aggregator, JSON (POST) | Key via form | no (Cloudflare 403 without key) | unverified | unverified | med (ae.jooble.org exists) | Key needs a form with phone + website |
| Adzuna | Aggregator, JSON | Key (signup) | 401 without key | yes | yes | none | 19 countries, no GCC (third-party list, not official) |
| JSearch (RapidAPI) | Google Jobs data, JSON | Key (signup) | 429 without key | yes | yes | high in theory | Free quota unverified (commonly quoted ~200 req/month) |
| Google Jobs | n/a | No free official API | no | n/a | n/a | high in theory | Only via paid/signup proxies (JSearch, SerpApi) |
| Findwork.dev | Board, JSON | Token required | 401 | unverified | unverified | low | |
| USAJobs, Reed | Gov / UK boards | Key | not tested | | | none | Irrelevant for GCC |
| Bayt | GCC board | n/a | no, 403 Cloudflare challenge | | | high but blocked | No working RSS |
| GulfTalent | GCC board | n/a | no, 403 Cloudflare + captcha | | | high but blocked | |
| Naukrigulf | GCC board | n/a | no, connection hangs (timeout, 0 bytes) | | | high but blocked | Looks like bot tarpit |
| Dubizzle jobs | GCC board | n/a | no, 200 but Imperva "Pardon Our Interruption" page | | | med but blocked | |
| Wuzzuf | Egypt board | n/a | no, 403 Cloudflare | | | low | |
| Akhtaboot | Jordan/GCC board, RSS | Free | yes, 200 | no | yes, `pubDate` | low | `search.rss` ignores keyword, mostly Jordan |
| Indeed UAE RSS | Board | n/a | no, 403 captcha | | | n/a | RSS also long discontinued |
| Feashliaa/job-board-data (GitHub) | Daily dataset of ATS jobs | Free | yes, 200 | no | `first_seen` | discovery only | 1.47M jobs, 28,873 active companies. Used to find GCC employers |

## (b) Per-source notes

### Greenhouse
- `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs` (add `?content=true` for HTML description, departments, offices).
- Single job: `GET /v1/boards/{token}/jobs/{id}`.
- Fields: `title`, `location.name`, `absolute_url`, `first_published`, `updated_at`, `id`. `first_published` is present in the list even without `content=true` (checked on Careem).
- `content` is HTML-escaped (`&lt;h3&gt;`), unescape it.
- EU: `boards-api.eu.greenhouse.io` did not resolve (DNS) today. Tamara's job URLs point to `job-boards.eu.greenhouse.io` but its API works on the normal host.
- Limits: none documented. Docs only say GET needs no auth.
- Unknown token returns 404 `{"status":404,"error":"Job not found"}`. Tokens die: `hala` was live on 2026-10-09 and 404 today.

### Lever
- `GET https://api.lever.co/v0/postings/{company}?mode=json` (supports `&limit=`, `&skip=`, `&location=`, `&team=`).
- Fields: `text` (title), `categories.location`, `categories.allLocations`, `country` (ISO2), `createdAt` (ms), `hostedUrl`, `descriptionPlain`, `workplaceType`.
- Unknown company: 404 `{"ok":false,"error":"Document not found"}`. Existing account with no jobs: `[]`.
- EU host `api.eu.lever.co` responds (404 for slugs I tried). Unverified with a real EU tenant. Kitopi's careers page links `jobs.lever.co/kitopi` but both hosts return 404, so the link is stale.

### Ashby
- `GET https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true`
- Fields: `title`, `location`, `secondaryLocations[].location`, `address.postalAddress.addressCountry`, `isRemote`, `workplaceType`, `publishedAt`, `jobUrl`, `descriptionPlain`, `descriptionHtml`.
- Org name can contain dots (Kraken is `kraken.com`). No limits documented. Responses can be large (Kraken 1.3 MB).

### Workable
- Widget: `GET https://www.workable.com/api/accounts/{x}?details=true` now 302-redirects to `https://apply.workable.com/api/v1/widget/accounts/{x}?details=true`. Call the second URL directly. Fields: `title`, `shortcode`, `city`, `country`, `locations[]`, `published_on` (date), `created_at`, `url`, `description` (with details=true).
- v3 list: `POST https://apply.workable.com/api/v3/accounts/{x}/jobs` body `{"query":"","location":[],"department":[],"worktype":[],"remote":[]}`. Fields: `title`, `shortcode`, `location.city/country/countryCode`, `published` (date at 00:00Z), `workplace`. Paginate with `nextPage` token in body as `token`.
- Detail: `GET https://apply.workable.com/api/v2/accounts/{x}/jobs/{shortcode}` gives `description`, `requirements`, `benefits`.
- Cross-company search: `GET https://jobs.workable.com/api/v1/jobs?query=flutter&location=United%20Arab%20Emirates`. Fields: `title`, `description`, `requirementsSection`, `location.city/countryName`, `created`, `updated`, `company.title`, `url`, `workplace`. `totalSize` + `nextPageToken`. Test: "developer" in Dubai = 104 jobs; "flutter" in UAE = 3 (one real Flutter role).
- Gotchas: Cloudflare in front (CF-RAY DXB). Many names exist as empty placeholder accounts (`careem`, `tabby`, `noon` return 200 with `jobs: []`), so a 200 does not mean the company really uses Workable. Unknown account returns 404.

### SmartRecruiters
- `GET https://api.smartrecruiters.com/v1/companies/{x}/postings?limit=100&offset=0` with optional `country=ae`, `q=flutter`.
- Detail: `GET .../postings/{id}` gives `jobAd.sections.jobDescription/qualifications`, `postingUrl`, `applyUrl`.
- Fields: `name`, `location.city/country/remote`, `releasedDate`, `id`. Delivery Hero with `country=ae` = 47 jobs today (talabat, InstaShop).
- Gotcha: unknown company returns 200 with `totalFound: 0`, not 404.

### Teamtailor
- `GET https://{x}.teamtailor.com/jobs.rss`. Items have `title`, `description` (HTML), `pubDate`, `link`, `remoteStatus`, `tt:locations/tt:location/tt:city/tt:country`, `tt:department`.
- The official JSON API needs a company key. RSS is enough.

### Oracle HCM (Candidate Experience)
- `GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber={CX_n},limit=25,keyword=engineer,sortBy=POSTING_DATES_DESC`
- Fields in `items[0].requisitionList[]`: `Id`, `Title`, `PostedDate`, `PrimaryLocation`, `PrimaryLocationCountry`, `ShortDescriptionStr`. Total in `items[0].TotalJobsCount`.
- Emirates NBD: host `fa-evlo-saasfaprod1.fa.ocs.oraclecloud.com`, site `CX_1`, 30 jobs. Without `expand=requisitionList` you only get the count.

### Workday CXS
- `POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` body `{"appliedFacets":{},"limit":20,"offset":0,"searchText":"Dubai"}`.
- List fields: `title`, `externalPath`, `locationsText`, `postedOn` ("Posted Today", "Posted 3 Days Ago"), `total`.
- Detail: `GET .../wday/cxs/{tenant}/{site}{externalPath}` gives `jobPostingInfo.jobDescription`, `startDate`, `endDate`, `country`.
- Max `limit` is 20. Facets (`locationMainGroup`, `jobFamilyGroup`) can filter by country once you read their IDs from the first response.

### BambooHR
- List: `GET https://{x}.bamboohr.com/careers/list` (send `Accept: application/json`). Fields: `id`, `jobOpeningName`, `location.city`, `isRemote`, `departmentLabel`. No date.
- Detail: `GET https://{x}.bamboohr.com/careers/{id}/detail` gives `description`, `datePosted`, `location`.
- To detect "new", diff the id list, then fetch detail for new ids only.

### Recruitee, Breezy, Personio
- Recruitee: `GET https://{x}.recruitee.com/api/offers/`. Fields `title`, `city`, `country_code`, `published_at`, `description`, `careers_url`.
- Breezy: `GET https://{x}.breezy.hr/json`. Fields `name`, `location`, `published_date`, `url`. No description.
- Personio: `GET https://{x}.jobs.personio.de/xml` (or `.com`). XML `<position>` with `name`, `office`, `createdAt`, `jobDescriptions`.

### Careerjet (legacy public API)
- `GET http://public.api.careerjet.net/search?locale_code=en_AE&keywords=flutter&location=Dubai&sort=date&pagesize=20&user_ip=...&user_agent=...`
- Must send a `Referer` header, or you get 403 "Undeclared referrer". No `affid` was needed today.
- Fields: `title`, `company`, `locations`, `date`, `description` (snippet), `url` (jobviewtrack redirect). "developer" in UAE sorted by date = 349 hits, newest from 2026-10-13.
- The new v4 API (`search.api.careerjet.net/v4/query`) needs a key. The legacy one may be retired without notice.

### LinkedIn guest endpoints
- Search: `GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=flutter&location=United%20Arab%20Emirates&f_TPR=r86400&sortBy=DD&start=0` returns an HTML fragment with 10 cards. Parse `urn:li:jobPosting:{id}`, `base-search-card__title`, `job-search-card__location`, `<time datetime=...>`.
- Detail: `GET https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}` returns HTML with full description (`show-more-less-html__markup`), "posted X hours ago", applicant count, criteria.
- Gotchas: keyword match is loose ("flutter" returned SRE and QA roles). `f_TPR=r3600` and `r7200` returned empty pages twice, then a 429 on the next call. Treat it as fragile: a few queries per hour at most, back off on 429.

### Himalayas
- `GET https://himalayas.app/jobs/api?limit=20` (latest), or `GET https://himalayas.app/jobs/api/search?q=flutter&country=AE&sort=recent`.
- Fields: `title`, `companyName`, `locationRestrictions` (empty = worldwide), `timezoneRestrictions`, `pubDate` (epoch), `description`, `applicationLink`. Use the `nextCursor` value as `?cursor=` (offset is deprecated).

### Other remote boards
- Remote OK: `GET https://remoteok.com/api`. First element is the legal notice. Fields `position`, `company`, `location`, `epoch`, `date`, `description`, `url`, `tags`.
- WWR: `https://weworkremotely.com/categories/remote-programming-jobs.rss` (25 items) or `/remote-jobs.rss`. Title is "Company: Role". Has `<region>`.
- Working Nomads: `GET https://www.workingnomads.com/api/exposed_jobs/`. Fields `title`, `company_name`, `location`, `pub_date`, `tags`.
- Jobicy: `GET https://jobicy.com/api/v2/remote-jobs?count=50&geo=united-arab-emirates&tag=flutter`. Invalid geo returns 400. Geo list at `?get=locations`.
- Remotive: `GET https://remotive.com/api/remote-jobs`. Today `search=` and `category=` were ignored (same 16 job ids every time). ToS: max 4 calls per day, jobs delayed 24h.
- HN: thread list `GET https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring`, then comments `GET https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_{id}&hitsPerPage=100`. Filter `parent_id == story_id` for top-level posts. Only 2 comments mention Dubai, so value is in "REMOTE" posts.

### GCC job boards
- Bayt, GulfTalent, Wuzzuf: Cloudflare "Just a moment" challenge (403). Not fetchable with plain HTTP.
- Dubizzle: Imperva block page. Naukrigulf: TCP connects, no response until timeout.
- Indeed AE: 403 captcha on both `/jobs` and `/rss`.
- Akhtaboot: `https://www.akhtaboot.com/en/jobs/search.rss?keywords=...` works but ignores the keyword and is mostly Jordan.
- Practical route to these jobs: Careerjet `en_AE` and LinkedIn guest surface many of the same postings.

## (c) Verified GCC company boards (checked 2026-10-14)

"GCC jobs" means jobs whose location text matches a GCC city or country (word-boundary match). "Total" is the whole board.

| Company | Country | ATS | Token | Total jobs | GCC jobs | Verified |
|---|---|---|---|---|---|---|
| Careem | UAE | Greenhouse | `careem` | 16 | 9 | yes |
| Tamara | KSA / UAE | Greenhouse | `tamara` | 39 | 23 | yes |
| BRKZ | KSA | Greenhouse | `brkz` | 23 | 17 | yes |
| Bybit | UAE (Dubai HQ) | Greenhouse | `bybit` | 158 | 51 | yes |
| Deliveroo (UAE, Kuwait, Qatar ops) | UAE | Greenhouse | `deliveroo` | 220 | 21 | yes |
| OKX | UAE | Greenhouse | `okx` | 349 | 6 (26 mobile roles board-wide) | yes |
| Decima International | KSA | Greenhouse | `decimainternational` | 35 | 8 | yes |
| Kitchen Park | KSA | Greenhouse | `kitchenpark` | 6 | 5 | yes |
| AudioMob | UAE (Abu Dhabi) | Greenhouse | `audiomob` | 8 | 8 | yes |
| Scale AI | Qatar / UAE | Greenhouse | `scaleai` | 183 | 16 | yes |
| Anduril | UAE (Abu Dhabi) | Greenhouse | `andurilindustries` | 2490 | 15 | yes |
| Artefact | UAE / KSA | Greenhouse | `artefact` | 136 | 11 | yes |
| DataCamp | UAE (remote incl. Dubai) | Greenhouse | `datacamp` | 39 | 8 | yes |
| Lucid Motors | KSA | Greenhouse | `lucidmotors` | 456 | 41 | yes |
| Geotab | UAE | Greenhouse | `geotab` | 67 | 4 | yes |
| Elastic | UAE | Greenhouse | `elastic` | 382 | 4 | yes |
| Aldar | UAE | Lever | `aldar` | 49 | 49 | yes |
| eConstruct | UAE | Lever | `econstruct` | 22 | 10 | yes |
| Flow | KSA (Riyadh) | Lever | `flowlife` | 36 | 9 | yes |
| 1inch | UAE | Lever | `1inch` | 4 | 4 | yes |
| Binance | UAE | Lever | `binance` | 33 | 6 | yes |
| Crypto.com | UAE | Lever | `crypto` | 85 | 5 | yes |
| Palantir | UAE (Abu Dhabi) | Lever | `palantir` | 312 | 4 | yes |
| Trendyol | KSA | Lever | `trendyol` | 40 | 8 | yes |
| Xsolla | UAE | Lever | `xsolla` | 190 | 6 | yes |
| Loft Orbital | UAE (Abu Dhabi) | Lever | `loftorbital` | 65 | 9 | yes |
| Ziina | UAE | Ashby | `ziina` | 13 | 13 | yes |
| Lean Technologies | KSA | Ashby | `leantech` | 7 | 7 | yes |
| Thndr | UAE / Egypt | Ashby | `thndr` | 13 | 5 | yes |
| Kraken | UAE | Ashby | `kraken.com` | 83 | 19 | yes |
| MEX Digital | UAE | Ashby | `mexdigital` | 14 | 9 | yes |
| Cohere | UAE / KSA | Ashby | `cohere` | 116 | 8 | yes |
| ElevenLabs | UAE | Ashby | `elevenlabs` | 144 | 6 | yes |
| Cognition | KSA | Ashby | `cognition` | 103 | 5 | yes |
| OpenAI | UAE (Abu Dhabi) | Ashby | `openai` | 806 | 3 | yes |
| Taptap Send | UAE | Ashby | `taptapsend` | 33 | 10 | yes |
| Salla | KSA | Workable | `salla` | 40 | 40 (1 mobile) | yes |
| Foodics | KSA | Workable | `foodics` | 28 | 24 | yes |
| Lucidya | KSA | Workable | `lucidya` | 46 | 28 | yes |
| Mozn | KSA | Workable | `mozn-ai` | 17 | 17 (all KSA, not split) | yes |
| Delivery Hero (talabat, InstaShop, HungerStation) | UAE / KSA / Kuwait | SmartRecruiters | `deliveryhero` | 47 with `country=ae` | 47 (UAE filter) | yes |
| Namshi | UAE | SmartRecruiters | `namshi` | 6 | 6 | yes |
| Property Finder | UAE | Teamtailor | `propertyfinder` | 32 (2 mobile) | not split | yes |
| Emirates NBD | UAE | Oracle HCM | `fa-evlo-saasfaprod1.fa.ocs.oraclecloud.com` / `CX_1` | 30 | 30 | yes |
| Mastercard | UAE | Workday | `mastercard` / `wd1` / `CorporateCareers` | 13 for "Dubai" | 13 | yes |
| 360VUZ | UAE | BambooHR | `360vuz` | 18 | most | yes |
| Fasset | UAE | BambooHR | `fasset` | 10 | some | yes |
| Tumodo | KSA | BambooHR | `tumodo` | 13 | some | yes |

Not found or dead today: `hala` (Greenhouse 404, was live 10-09), `huspy`, `propertyfinder`, `mrsool`, `ziina`, `stc` on Greenhouse (404 even though old datasets list them), `kitopi` on Lever (404 on US and EU), `rain` on Ashby (a different, US company, 0 GCC jobs). Tabby, Noon, Huspy, Sarwa, Baraka, Stake, Anghami, Wio, G42, Alaan and Bayzat career pages are JS apps with no ATS link in the HTML, so their ATS is unverified.

## (d) How to discover 200 to 500 GCC boards

1. Best method found: the public GitHub dataset `Feashliaa/job-board-data` (`data/chunks/jobs_chunk_{0..58}.json.gz`, about 76 MB, rebuilt daily). Each job has `company`, `ats`, `location`, `url`, `first_seen`. Filtering locations for GCC cities gives 578 companies (Workday 241, Greenhouse 151, BambooHR 74, Ashby 54, Lever 53). Slug lists per ATS are in `Feashliaa/job-board-aggregator/data/{greenhouse,lever,ashby,workday,bamboohr}_companies.json` (8,333 / 4,368 / 3,161 / 12,884 entries). Of 186 boards I re-fetched live, 104 had at least one GCC job today. Run this monthly to refresh the list, then poll the boards directly.
2. Workable cross-company search (`jobs.workable.com/api/v1/jobs?location=...`): each result names the company, which reveals Workable accounts hiring in Dubai, Riyadh, Doha.
3. Scan careers pages for ATS links with a regex (`boards.greenhouse.io/`, `jobs.lever.co/`, `jobs.ashbyhq.com/`, `apply.workable.com/`, `*.teamtailor.com`, `*.myworkdayjobs.com`, `oraclecloud.com/hcmUI/CandidateExperience`). This found Property Finder, Kraken, Mozn and Emirates NBD. It fails on JS-only pages.
4. `site:boards.greenhouse.io "Dubai"` style searches: the search tool I had ignored `site:`. Untested on Google or Bing directly.
5. Guessing slugs across ATS hosts works but the hit rate was low (about 10 of 160 names). Watch for Workable and SmartRecruiters placeholder accounts that return 200 with zero jobs.
6. Location-matching gotcha: a plain substring check for "oman" matches "Romania", and "uae" can match other words. Use word boundaries and also check ISO country codes (`AE`, `SA`, `QA`, `KW`, `BH`, `OM`).

## (e) Recommendation

**Phase 2 (add now)**
1. Greenhouse, Lever, Ashby per-company polling for the GCC list above plus dataset-derived boards. Fastest signal, real timestamps, no keys, no blocking seen.
2. Workable: v3 per-account polling for GCC accounts plus `jobs.workable.com` search for `flutter`, `android`, `kotlin`, `mobile`, `ai engineer` in UAE, Saudi Arabia, Qatar.
3. SmartRecruiters with `country=ae` / `sa` for Delivery Hero and Namshi.
4. Careerjet `en_AE` with `sort=date` for keyword sweeps across GCC boards (covers jobs from blocked sites like Bayt). Poll every 30 to 60 min, not every few minutes.
5. Himalayas `country=AE` and LinkedIn guest search with very low frequency (a handful of queries per hour, `f_TPR=r86400`, dedupe by job id, stop on 429).

**Later**
- Teamtailor RSS (Property Finder), Oracle HCM (Emirates NBD and other banks), Workday tenants with GCC offices, BambooHR (diff ids, fetch details for new ones).
- HN Who's Hiring monthly thread, Remote OK, We Work Remotely, Working Nomads, Jobicy (`geo=united-arab-emirates`).
- JSearch and Jooble only if you accept a signup and key. Both are unverified here.

**Skip**
- Bayt, GulfTalent, Naukrigulf, Dubizzle, Wuzzuf, Indeed (all blocked for plain HTTP).
- Adzuna (no GCC), Remotive (filters ignored, 24h delay), Arbeitnow, The Muse, Findwork, USAJobs, Reed, JazzHR, Taleo, Zoho Recruit, Recruitee, Breezy, Personio (no GCC value found).
