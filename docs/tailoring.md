# CV tailoring (optional)

With tailoring on, every alert gets one more button: **✍️ Tailor CV**. Tap it and the bot sends the job post and your CV to a model, then replies in the chat with:

- the tailored CV as a Markdown file (and a `.docx` if you want),
- an optional cover letter,
- a short list of what changed and which job requirements your CV does not show.

It never applies anywhere. You read the result, fix what you want, and apply yourself.

It is **off** by default. When it is off, the button does not exist and the bot never reads your CV.

## Truth rules

The prompt tells the model, without exceptions:

1. Use only facts already in your CV. Reorder, reword, shorten and emphasize them.
2. Never invent or inflate skills, tools, employers, titles, dates, degrees, certifications, projects or metrics.
3. Never add a keyword only because the job asks for it. Missing requirements go to a GAPS list instead.
4. Keep names, employers, dates, links and contact details exactly as written.
5. Mark anything uncertain with `[CHECK]` and explain it.

Models still make mistakes. Read every line before you send it.

## Turn it on

1. Put your CV in the project folder as `cv.md` (recommended) or `cv.docx`. Both names are gitignored.
2. Install the extras:

```bash
pip install -e ".[claude]"          # Claude via the official anthropic SDK
pip install -e ".[claude,docx]"     # plus .docx input and output
```

3. Put `ANTHROPIC_API_KEY` in `.env` (console.anthropic.com).
4. In `config.yml`:

```yaml
tailoring:
  enabled: true
  provider: claude
  model: claude-haiku-5-5
  cv_file: cv.md
  docx: false
  cover_letter: false
  max_per_day: 10
  max_cost_per_month_usd: 2.0
  price_per_mtok: {input: 0.10, output: 0.50}
```

5. `jobbot check-config`, then restart the bot.
   - **systemd:** `bash deploy/deploy.sh --with-cv`. It copies the CV and, because tailoring is on, installs the `anthropic` SDK (and `python-docx` for .docx) on the server.
   - **Docker:** put the CV in a `cv/` folder, set `cv_file: cv/cv.md` (or `cv/cv.docx`), uncomment the `./cv` volume and build with `--build-arg EXTRAS="anthropic python-docx"`.

If something is wrong at startup (missing CV, missing package), the bot logs "CV tailoring is OFF for this run" with the reason and keeps sending alerts without the button.

Tailored files are also saved in `data/tailored/` on the machine that runs the bot.

## Models and cost

Rough cost per tailored CV, for a 2-page CV and a typical job post (about 6,000 input tokens and 4,000 output tokens):

| Model | Price per million tokens (input / output) | About per CV |
|---|---|---|
| `claude-haiku-5-5` (default) | $0.10 / $0.50 | $0.003 |
| `claude-sonnet-5-5` (stronger writing) | $2 / $10 | $0.05 |

Prices as of October 2026; check the provider's pricing page. Set `price_per_mtok` to match your model, because the monthly cap uses it. To switch to Sonnet:

```yaml
  model: claude-sonnet-5-5
  price_per_mtok: {input: 2.0, output: 10.0}
```

## Limits

- `max_per_day`: taps per day (UTC). Failed attempts count too, so a broken setup cannot loop.
- `max_cost_per_month_usd`: stops tailoring for the rest of the month once the estimated spend reaches it.
- Only alerts sent after this version keep the job text needed for tailoring. Older alerts answer "No job text was saved".

## Privacy

A CV is personal data. The bot refuses to tailor with a provider that may train on your data: the Gemini free tier counts as one. If your Gemini key is on a paid plan (or you accept the risk), set `provider: gemini` and `allow_free_tier: true`. The Claude API does not train on API inputs by default; see Anthropic's current policy.

Your CV is sent to the model only when you tap the button, together with that one job post.
