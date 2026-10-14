# AI scoring (optional)

Keyword filters miss walls hidden in the text: "must hold a local residence permit", "5 years with our in-house framework", "this role is for UAE nationals". With AI scoring on, the bot asks a model to read the full post of every job that passed the keyword filter, and to answer with a score, a hard-wall flag and short positives and warnings.

It is **off** in the example config. The default provider is Google Gemini, whose free tier is enough for one person.

## Turn it on

1. Get a key at aistudio.google.com/apikey and put it in `.env` as `GEMINI_API_KEY`.
2. In `config.yml`:

```yaml
ai:
  enabled: true
  models: [gemini-3.5-flash-lite, gemini-3.5-flash]
```

3. `jobbot ai-models` lists the models your key can use. Put the cheapest fast one first.
4. `jobbot ai-prompt` prints the exact instructions the model gets.

## How it works

- Only jobs with a keyword score of at least `prefilter_min_score` (default 2.5) go to the AI. Jobs the keyword filter dropped never do.
- The answer is JSON: `score` (1 to 5), `hard_wall`, `wall_reason`, `years_required`, `location`, `work_mode`, `positives`, `warnings`.
- `hard_wall: true` drops the job and saves the reason in the database (`reason` starts with `AI:`).
- Otherwise the AI score replaces the keyword score, and the job alerts at `min_score` (default 3.5) or more.
- `models` is a fallback chain. A busy (503), slow or out-of-quota model hands the job to the next one.
- If every model fails, or `max_calls_per_day` is reached, the job still alerts on its keyword score with an "AI check unavailable" warning. The AI never makes you lose a job.
- `min_gap_seconds` spaces the calls (the free tier allows about 10 a minute).

## The prompt

The instructions are built from `profile.yml`: your anonymous `summary`, home city and visa note, languages, tracks (`ai_description`), locations, seniority, salary floor, nationals rules and your `ai.soft_issues` and `ai.notes`. Nothing about you is hard-coded. Edit the profile and check the result with `jobbot ai-prompt`.

## Privacy

Only public job posts and the anonymous parts of your profile are sent. Never your name, contact details or CV. Keep `summary` free of anything that identifies you.

The Gemini free tier may use prompts and answers to improve Google's products. For job posts plus an anonymous summary, that is usually acceptable. If it is not for you, leave AI scoring off or use a paid Gemini key.

## Troubleshooting

| Log line | Meaning |
|---|---|
| `HTTP 503, trying the next model` | The model is overloaded ("high demand"). Normal on free tiers; the chain moves on. Put a less popular model second. |
| `quota or rate limit, trying the next model` | Per-minute or per-day quota hit. Raise `min_gap_seconds` or lower `max_calls_per_day`. |
| `rejected the schema, retrying without it` | The model does not support structured output. The bot retries without it. |
| `AI daily cap (200) reached` | `max_calls_per_day` reached. Alerts continue on keyword scores until midnight UTC. |
