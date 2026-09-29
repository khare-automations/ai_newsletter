# CLAUDE.md - how to extend this repo

This is a daily-briefing generator. Sources are adapters that all return `briefing.models.Item`.
The pipeline (`briefing/pipeline.py`) is source-agnostic: fetch -> dedup -> filter -> theme ->
render (email + optional web edition).

## Optional features (all off by default, config-driven)
- **email.mode** (`email.py`): `full` emails everything; `cover` emails a triage-first cover
  (tables + inline styles): the day in 30 seconds, a numbered reading order with read times, at
  most 3 skim headlines per section with an "N more" link to `#skim-<n>` on the web edition, and
  a CTA, plus archive links (masthead, a secondary button, footer). `email.unsubscribe` (`sender` =
  mailto the sending account) / `email.address` add footer lines, `email.feedback` adds
  "Useful / Not for us" mailto: links per reading-order story (all default off). `EMAIL_RECIPIENT` may be a comma-separated list (each reader gets
  their own message). `email.subject: top_pick` puts the lead headline in the subject line;
  `email.from_name` sets the inbox sender name.
- **priority** (`priority.py`): one Claude call after filtering labels each item `first` /
  `today` / `later` (in `item.extra["priority"]`, plus `extra["why"]`) against a company profile
  in `priority.context`; themes are re-sorted by it. The same call clusters duplicate coverage
  (`same_as`): the lead keeps the others in `extra["also"]`, gets `extra["cluster_title"]` and the
  group's best tier, and `prioritize` returns the list without them. `extra["rank"]` is Claude's
  order; with no labels at all `triage` uses each of the first 3 sections' lead story. With topics (`Config.topics()`: `archive.topics`, else labels from `filter.interests`) it
  also sets `extra["topic"]` (validated, "" if none). The last 2 days' reading-order headlines
  (`history.recent_order`, via `recent_titles` / `remember_order`) go into the prompt; a story that
  only follows one up is demoted to `later` with `extra["followup"]` ("Follow-up ·" in skim). `priority.triage(themes)` gives the renderers' (reading order, skim) split. Fails soft to
  unlabeled, unclustered items.
- **summary** (`summary.py`): "The day in 30 seconds": one Claude call after theming, written for
  the priority profile (`org` + `context`) when priority is on, 3
  `{lead, text, short, ref}` takeaways (`ref` = `{"stories": [..]}` or `{"section": n}`). Off by
  default; [] on failure and the section is hidden.
- **images** (`images.py`): after filtering, sets `item.extra["image"]` from the feed's own media
  (RSS `media:content` / enclosures, YouTube thumbnails) or the article's `og:image`. Fails soft per
  item. The same fetch sets `item.extra["minutes"]` (article words / 230 wpm; unset for stubs, and
  renderers fall back to 3). The cover email shows one image (story 1); the web edition shows them
  on Read first items (`web.reading_images: first|all|none`).
- **palette** (`theme.py`): every colour the email and web edition use lives in `PALETTE`; CSS in
  `email.py` / `web.py` references `$name` placeholders filled by `theme.css()`.
- **voice** (`voice.py`): an editor persona that writes the daily greeting and steers theme names.
  Always fails soft (no greeting on any error / when disabled). Recent greetings are kept in
  `history.json` (`recent_greetings`) and fed back as an avoid-list for variety.
- **web** (`web.py`): builds `docs/index.html` (a sticky triage bar with jump links and a read
  progress bar, the day in 30 seconds + a time budget, the numbered reading order with "Mark as
  read" kept in localStorage, and a skim list per section, `id="skim-<n>"`, with tap-for-gist rows;
  `web.skim_expanded` opens them all), a permanent `docs/editions/<date>-<slot>.html` that embeds its stories as
  JSON (`<script id="edition-data">`, rows carry `topic`, `n`, `minutes`, `also`) plus its summary
  (`edition-summary`), and rebuilds `docs/archive.html` from those: every story ever sent, grouped
  by day with a "That day" line, searchable (highlighted), filterable by priority, topic and source,
  state mirrored in the URL hash (`#q=..&tier=..&topic=..&source=..`). Old editions without the new
  fields still load (no topic = "Other"). Served by GitHub Pages (`/docs`).
  All markup is server-rendered and works without JS; the inline JS only adds read state, gist
  toggles, smooth jumps and the archive filters.
- **editions** (`editions.py`): AM/PM editions chosen by local hour; match the Claude routine's schedule.
- **Runs** (`daily.yml` -> `main.py` -> `pipeline.run`): no GitHub cron. A Claude routine
  dispatches the workflow at 06:13 Zurich on weekdays if `history.json` `last_sent` isn't today
  (GitHub cron started runs hours late and double-sent). `BRIEFING_ONLY_IF_UNSENT` makes
  `pipeline.run` skip when `last_sent` is today. A manual run can set `preview_to` (email only that address, "[Preview]" subject, save no
  history or web edition) and `edition` (auto / daily / weekly, which overrides the weekday).
- **schedule** (`weekly.py`): `skip_weekends` sends nothing Sat/Sun (checked before login or any
  fetch; the Claude routine is weekdays-only too). On `weekly_day` (Friday) the edition is the
  "Week in 5": `week_candidates` reads this week's Read first/today rows back from the archive plus
  today's reading order, one Claude call (`pick_week`) picks `weekly_picks` and writes "The week in
  30 seconds", and `weekly_themes` puts the picks in a `pinned` theme that `triage` uses as the whole
  reading order (today's other stories are skim). Fallback: the week's Read first, newest first; no
  candidates at all = a normal daily edition. Saved as `editions/<date>-weekly.html`.

## Adding a source when asked (decision order)
1. **Has an RSS feed?** Add one line to `config.yaml`: `{ type: rss, name: "X", url: "<feed>" }`.
   If the publisher 403s datacenter IPs (Cloudflare), add `proxy: true` to route through a relay.
2. **No feed, real site?** Write a bespoke parser: copy `briefing/sources/sites/_example.py` to
   `briefing/sources/sites/<name>.py`, edit selectors so `fetch(cfg)` returns `list[Item]`, then add
   `{ type: site, name: "X", module: "<name>" }`. Mirror `seedcamp.py`. Add a fixture-based test in
   `tests/sources/sites/`. The HTTP helper is imported as `http_get` so tests can patch it.
3. **Trivial static page?** Use a `scrape` config line with `item_selector` / `title_selector` /
   `link_selector` (and optional `summary_selector`).
4. **JS-gated / zero effort?** Use `{ type: claude_fetch, name: "X", url: "<page>" }`. Links Claude
   returns are checked against the page's real `<a href>`s when the page is readable.

Dedup: item ids are sha1 of the *normalised* URL (`models.normalize_url`: no www, fragment,
tracking params); `history.drop_seen` also matches a title fingerprint so the same story from two
feeds only runs once.

## Invariants
- Every adapter returns `list[Item]` and uses `briefing.sources._fetch.fetch` for HTTP (browser UA +
  retries). Use `fetch_with_fallback` for bot-blocked publishers (relay retry on 403/429/etc).
- Adapters fail soft (the registry wraps each in `safe_fetch`); raising on a real error is fine.
- LLM steps that return JSON go through `briefing.llm.claude_json` (retries once, returns None,
  never raises); callers must have a non-LLM fallback so a Claude outage never skips an edition.
- Optional features stay optional: new config keys must default to off so a minimal config still works.
- Never put sources/interests in Secrets - only API keys + email creds. Config lives in `config.yaml`.
- Render/voice helpers (`web.py`, `voice.py`) take no network at import and escape all user/source text.
- Run `./.venv/Scripts/python.exe -m pytest -q` (or `pytest -q`) before committing.
