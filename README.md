# Daily Briefing

Turn a list of web / news / RSS / YouTube sources into one filtered, themed
briefing — delivered as an **email**, and (optionally) published as a browsable
**web edition** with a permanent **archive** on GitHub Pages. It runs itself on
a schedule via GitHub Actions, curates with Claude, and remembers what it has
already shown so nothing repeats.

This repo is a **template**. The headline `config.yaml` ships a plain themed
email; every richer feature (editor voice, web edition, archive, twice-daily
editions) is opt-in. The companion repos `Newsletter` ("The Curated Canopy")
and `canopy-edition` are a fully built-out instance of this same engine — use
them as inspiration for how far you can take it.

---

## What you get

- **Email** every morning: your items grouped into witty themes by Claude.
- **Optional web edition**: a self-contained, browsable HTML "magazine" page
  published to GitHub Pages — with the email reduced to a short *cover* that
  links out to it.
- **Optional archive**: every edition saved permanently and listed at a
  `/archive.html` index.
- **Optional editor voice**: an AI persona you define — name and tone are yours
  to invent — that writes the daily greeting and names the themes in character.
- **Optional twice-daily editions**: a Morning and an Evening edition.
- **No repeats**: a committed `history.json` tracks everything already sent.
- **Resilient sources**: browser-UA fetch with retries, and a relay fallback
  for publishers that block datacenter IPs.

---

## How it works (the 30-second version)

Every source adapter returns the same `Item` shape, so the pipeline never cares
where an item came from:

```
fetch all sources ─► drop already-seen (history.json) ─► filter ─►
  group into themes (Claude) ─► render ─► email  (+ optional web edition + archive)
```

Adding a new source never touches the pipeline. It's patterned after the
Ellipsis `athena/scrapers/` source-adapter design. See `CLAUDE.md` for the
contract and `briefing/pipeline.py` for the orchestration.

---

## Step-by-step setup

### Step 1 — Make your own copy

Click **"Use this template" → Create a new repository**. A **private** repo is
recommended (your interests and recipients live in config; only secrets are
hidden). You now own a full copy you can edit freely.

### Step 2 — Get your API keys

| Key | Where | Needed for |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API keys (pay-as-you-go, ~cents/day) | Theming, the `interests`/`claude_curate` filters, `claude_fetch`, editor voice |
| `YOUTUBE_API_KEY` | Google Cloud Console → enable **YouTube Data API v3** → create an API key | Only if you use `youtube` sources |

> Your Claude **Max/Pro** plan is for *building* this repo with Claude. The
> automated daily runs bill the `ANTHROPIC_API_KEY` instead.

### Step 3 — Set up email sending (Gmail example)

1. Turn on **2-Step Verification** on the sending Google account.
2. Create an **App Password**: Google Account → Security → App passwords →
   generate one for "Mail". You get a 16-character password — that's
   `EMAIL_PASSWORD` (not your normal login password).
3. Defaults are Gmail's SMTP (`smtp.gmail.com:587`). For another provider set
   `SMTP_HOST` / `SMTP_PORT` accordingly.

### Step 4 — Add your secrets

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret | Required? | Example / notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | `sk-ant-...` |
| `EMAIL_SENDER` | ✅ | the sending address, e.g. `you@gmail.com` |
| `EMAIL_PASSWORD` | ✅ | the 16-char Gmail **App Password** |
| `EMAIL_FROM` | optional | the From: address readers see, e.g. a Workspace alias like `newsletter@company.com`. Must be a verified "Send mail as" address of `EMAIL_SENDER`; defaults to `EMAIL_SENDER` |
| `EMAIL_RECIPIENT` | ✅ | who receives it. **Comma-separate for several:** `me@x.com, mum@y.com` |
| `SMTP_HOST` | optional | defaults to `smtp.gmail.com` |
| `SMTP_PORT` | optional | defaults to `587` |
| `YOUTUBE_API_KEY` | optional | only for `youtube` sources |
| `EDITION_DEPLOY_TOKEN` | optional | publish the web edition to a *separate* public repo (see Step 8) |

> **Never** put sources or interests in secrets — those live in `config.yaml`.
> Secrets are only for keys and credentials.

### Step 5 — Configure `config.yaml`

`config.yaml` is the whole briefing. Only `briefing`, `filter`, and `sources`
are required; everything else is optional and off by default. A minimal config:

```yaml
briefing:
  title: "My Daily Briefing"

filter:
  mode: interests          # see Step 7
  interests:
    - "AI policy in Europe"
    - "longevity research"
  max_items: 25
  per_source_cap: 5
  recency_hours: 24        # ignore items older than this

sources:
  - { type: rss,  name: "BBC World", url: "http://feeds.bbci.co.uk/news/world/rss.xml" }
  - { type: site, name: "Seedcamp", module: "seedcamp" }
```

`config.example.yaml` is the annotated reference with every option. You can also
just **ask Claude** ("add Hacker News and The Verge to my briefing") — `CLAUDE.md`
tells it exactly how.

### Step 6 — Add your sources

Pick the lightest type that works. The decision order:

1. **RSS — easiest, most reliable.** Most sites have a feed; try `https://SITE/feed`,
   `/rss`, or `/feed.xml`. One line:
   ```yaml
   - { type: rss, name: "The Verge", url: "https://www.theverge.com/rss/index.xml" }
   ```
   If a publisher blocks GitHub's datacenter IPs (Cloudflare 403s — common for
   Atlas Obscura, Science News), add `proxy: true` and the fetch retries through
   a public read-through relay:
   ```yaml
   - { type: rss, name: "Atlas Obscura", url: "https://atlasobscura.com/feeds/latest", proxy: true }
   ```

2. **`site` — a bespoke parser, most powerful.** For a real site with no usable
   feed. Copy `briefing/sources/sites/_example.py` to `briefing/sources/sites/<name>.py`,
   edit the CSS selectors so `fetch(cfg)` returns a `list[Item]`, then:
   ```yaml
   - { type: site, name: "Your Site", module: "<name>" }
   ```
   `seedcamp.py` is a worked example. Add a fixture-based test in
   `tests/sources/sites/` (the HTTP helper is imported as `http_get` so tests
   can patch it).

3. **`scrape` — quick but brittle.** A static page via inline CSS selectors:
   ```yaml
   - { type: scrape, name: "Static Site", url: "https://example.com/news",
       item_selector: ".post", title_selector: "h2 a", link_selector: "h2 a",
       summary_selector: "p.excerpt" }
   ```

4. **`claude_fetch` — zero effort, costs tokens.** Claude reads the page and
   extracts headlines. Good for JS-gated or one-off pages:
   ```yaml
   - { type: claude_fetch, name: "No-Feed Site", url: "https://example.com" }
   ```

5. **`youtube` — latest videos from a channel** (needs `YOUTUBE_API_KEY`):
   ```yaml
   - { type: youtube, name: "Veritasium", channel_id: "UCHnyfMqiRRG1u-2MsSQLbXA" }
   ```

Every adapter **fails soft**: one dead source is logged and skipped, never
killing the run.

### Step 7 — Choose a filter mode (`filter.mode`)

The filter decides which fetched items make the cut. `max_items` caps the whole
briefing regardless.

| Mode | Uses AI? | What it does |
|---|---|---|
| `recent` | no | newest items first, up to `max_items` |
| `per_source_cap` | no | at most `per_source_cap` per source, newest first |
| `interests` | yes | Claude scores every item 0–100 against your `interests`; keeps the high scorers |
| `claude_curate` | yes | Claude free-picks the genuinely most interesting items (your `interests` gently steer it) |

Free filters run first, so only survivors ever reach Claude — that's what keeps
cost down.

### Step 8 — (Optional) Publish a web edition + archive

Turn the briefing into a browsable page on GitHub Pages and shorten the email to
a cover that links to it.

In `config.yaml`:

```yaml
email:
  mode: cover            # email becomes a short cover; omit/“full” to email everything
web:
  enabled: true
  output_dir: "docs"     # the page is written here
  edition_url: "https://YOURNAME.github.io/YOURREPO/"   # linked from the cover email
```

Each run writes `docs/index.html` (current edition), a permanent
`docs/editions/YYYY-MM-DD-<slot>.html`, and rebuilds `docs/archive.html` (an
index of every past edition). The workflow commits these back automatically.

**To serve it — two options:**

- **Same repo (simplest):** Settings → Pages → Source: *Deploy from a branch* →
  branch `main`, folder `/docs`. Your edition is live at
  `https://YOURNAME.github.io/YOURREPO/` and the archive at `…/archive.html`.
  *Note:* this makes the `docs/` folder public even if the repo is private.

- **Separate public repo (keeps this repo private):** create a second public
  repo, enable Pages on it the same way, generate a fine-grained **PAT** with
  *Contents: write* on it, and save it as the `EDITION_DEPLOY_TOKEN` secret.
  Then set `EDITION_REPO: "owner/repo"` in the "Publish web edition" step of
  `.github/workflows/daily.yml`. This mirrors how `Newsletter` publishes to
  `canopy-edition`. The step skips silently if the token/repo aren't set.
  Optionally also set `EDITION_URL` in the "Verify web edition is live" step:
  it checks the new page is actually served and, if Pages stalled, pushes an
  empty commit to the public repo to kick a rebuild.

### Step 9 — (Optional) Give it an editor voice — make it your own

Your briefing can have an **AI editor persona** — entirely yours to invent. When
enabled, Claude writes a short daily greeting in that voice and names the themes
in character. It **fails soft**: any hiccup just drops the greeting and the
briefing still ships.

```yaml
voice:
  enabled: true
  name: "Your editor's name"          # invent a persona — it signs the greeting
  tone: "warm, cozy, slightly witty"  # this line is the prompt — see below
```

**How to prompt it.** The `tone` string is fed straight to Claude, so it's the
lever that shapes everything. Treat it like a brief: describe the *personality*
and *writing style* you want, not the content. A few vivid adjectives or short
phrases work best. Mix and match — for example:

| `name` | `tone` | Feels like |
|---|---|---|
| `"Sage"` | `"warm, cozy, slightly witty; like a friend writing you a morning note"` | A gentle daily hello |
| `"Scout"` | `"dry, deadpan, concise; never gushes, one sharp observation"` | A wry desk editor |
| `"The Almanac"` | `"elegant and literary, a little old-fashioned, fond of a good metaphor"` | A New Yorker columnist |
| `"Bolt"` | `"energetic and punchy, lots of momentum, short sentences"` | A hype newsletter |

Tips:
- Keep `tone` to a handful of descriptors — long paragraphs dilute the steer.
- It shapes both the **greeting** *and* the **theme names**, so a consistent
  personality reads best across the whole edition.
- Want different voices for the Morning vs. Evening edition? Keep two configs
  (e.g. `config.yaml` and `config.local.yaml`) — but a single persona usually
  feels more like a real publication.

**Going deeper.** If `name` + `tone` aren't enough control, edit the prompts
directly in `briefing/voice.py`: `compose_greeting()` builds the greeting
prompt, and `theme_steer()` is the clause folded into the theme-naming prompt in
`briefing/enrich.py`. That's where you'd add house rules ("never use exclamation
marks", "open with the weather", "sign off with a seasonal note").

### Step 10 — (Optional) Twice-daily editions

To run a Morning and an Evening edition, list them in `config.yaml` (the local
hour picks which one runs) and add the matching cron in the workflow:

```yaml
editions:
  - { key: morning, label: "Morning Edition", until_hour: 12 }
  - { key: evening, label: "Evening Edition" }   # the catch-all after noon
```

```yaml
# .github/workflows/daily.yml
on:
  schedule:
    - cron: '23 6 * * *'   # ~07:00 UTC
    - cron: '23 15 * * *'  # ~16:00 UTC  (uncomment this line)
```

The edition `label` is appended to the title and used in the archive filename.

### Step 11 — Test it

- **From GitHub:** the **Actions** tab → enable workflows → open *Daily
  Briefing* → **Run workflow**. Watch the logs; check your inbox.
- **Locally:**
  ```bash
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=...  EMAIL_SENDER=...  EMAIL_PASSWORD=...  EMAIL_RECIPIENT=...
  python main.py
  ```
  With the web edition enabled, open the generated `docs/index.html` in a
  browser to preview.

### Step 12 — Let it run

It then runs on the schedule in `.github/workflows/daily.yml` (default 06:23
UTC, landing around 07:00). Cron is in **UTC** — convert from your timezone.
GitHub starts on-the-hour crons late (often 30-90 min), so keep an off-hour
minute and schedule a little before the time you want the email. Each run's
summary page lists every source with its item count, and failed sources show
up as warnings. The **Tests** workflow runs `pytest` on every PR; the optional
**Claude PR Review** workflow needs a `CLAUDE_CODE_OAUTH_TOKEN` secret and
skips itself without one. After each run the
workflow commits the updated `history.json` (and `docs/` if the web edition is
on) so the next run knows what's already been sent.

---

## Cost

Free filters run first; only survivors reach Claude, so a daily briefing is
typically a **few cents/day** on `ANTHROPIC_API_KEY`. GitHub's free Actions
minutes (~2,000/mo for private repos) easily cover one or two runs a day.
GitHub Pages hosting is free.

---

## Running & developing locally

```bash
pip install -r requirements.txt          # runtime deps
pip install -r requirements-dev.txt      # + pytest
pytest -q                                # run the test suite before committing
python main.py                           # one full run (needs the env vars above)
```

Tests mock the network and the Anthropic/YouTube APIs, so they run offline and
for free.

---

## Project layout

```
main.py                     entry point: load config, run the pipeline
config.yaml                 your live config (sources, filter, optional features)
config.example.yaml         annotated reference for every option
history.json                seen-item memory (committed back each run)
briefing/
  pipeline.py               orchestration: fetch → dedup → filter → theme → render
  config.py                 parse + validate config.yaml
  models.py                 the shared Item shape
  filter.py                 the four filter modes (interests/recent/cap/curate)
  enrich.py                 group items into themes (Claude), voice-aware
  voice.py                  optional editor persona: greeting + theme steering
  editions.py               which edition (AM/PM) is running now
  email.py                  build + send the email (full or cover; multi-recipient)
  web.py                    build the web edition + dated archive (docs/)
  history.py                load/save/dedup against history.json
  sources/
    _fetch.py               hardened HTTP (browser UA, retries, relay fallback)
    rss.py scrape.py claude_fetch.py youtube.py   the built-in source types
    sites/                  bespoke per-site parsers (_example.py, seedcamp.py)
.github/workflows/daily.yml the schedule + publish/commit steps
docs/                       the published web edition + archive (when enabled)
```

---

## Extending with Claude

This repo is meant to be grown by asking Claude. `CLAUDE.md` documents the
adapter contract and the decision order for adding sources, so a prompt like
*"add the MIT Technology Review feed and cap it at 3 items"* or *"write a site
parser for example.com's blog"* lands correct, tested code. Run `pytest -q`
before committing — that invariant is in `CLAUDE.md` too.

---

## Troubleshooting

- **No email arrived.** Check the Actions log. Gmail needs an **App Password**,
  not your account password. Confirm `EMAIL_SENDER`/`EMAIL_RECIPIENT` are set.
- **"nothing new; skipping edition".** Everything fetched was already in
  `history.json`. To re-send during testing, reset it to `{"seen_ids": []}`.
- **A source is empty.** Look for `[source:NAME] FAILED` in the log. If it's a
  403/Cloudflare block on an RSS feed, add `proxy: true`. For a scraped site,
  the selectors probably changed — fix them or switch to `claude_fetch`.
- **Pages 404.** Confirm Settings → Pages points at the `/docs` folder (or the
  separate repo), and that at least one run has committed `docs/index.html`.
