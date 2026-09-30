from datetime import datetime, timezone
from pathlib import Path
from briefing.models import Item
from briefing.web import (build_web_edition, save_edition, build_archive_index,
                          collect_archive, tab_label)

def _item(t, st="rss", extra=None, url="http://x/1"):
    return Item.make(source="Src", source_type=st, title=t, url=url,
                     summary="a summary", published=datetime.now(timezone.utc),
                     extra=extra or {})

def _themes():
    return [{"name": "Theme A", "emoji": "*", "items": [_item("Headline One")]}]

def _body(html):
    return html.split("</style>")[1]

def test_build_web_edition_has_title_greeting_and_story():
    html = build_web_edition("Canopy", _themes(), greeting="Good morning.",
                             edition_label="Morning Edition", edition_date="2026-06-29")
    assert "Canopy" in html and "Good morning." in html
    assert "Theme A" in html and "Headline One" in html and "Morning Edition" in html
    assert "archive.html" in html  # footer + nav link to the archive

def test_web_edition_escapes_html():
    themes = [{"name": "A & B", "emoji": "*", "items": [_item("<script>x</script>")]}]
    html = build_web_edition("T & U", themes)
    assert "&amp;" in html
    assert "<script>x</script>" not in html  # raw markup must not leak

def test_embedded_data_cannot_close_the_script_block():
    themes = [{"name": "T", "emoji": "*", "items": [_item("</script><b>oops</b>", url="https://x/s")]}]
    html = build_web_edition("E", themes, edition_date="2026-06-29", slot_key="morning")
    data = html.split('<script id="edition-data" type="application/json">')[1].split("</script>")[0]
    assert "\\u003c/script>" in data and "</script" not in data
    import json
    row = json.loads(data)[0]
    assert row["title"] == "</script><b>oops</b>" and row["date"] == "2026-06-29"
    assert row["slot"] == "morning" and row["section"] == "T" and row["tab"] == "T"

def test_tab_label_shortens_on_word_boundary():
    assert tab_label("Price war") == "Price war"
    assert tab_label("Building on someone else's platform") == "Building on someone…"
    assert tab_label("Averyveryverylongsinglewordname") == "Averyveryverylongsin…"

def test_youtube_thumbnail_rendered():
    yt = _item("Vid", st="youtube", extra={"thumbnail": "http://t/1.jpg"})
    html = build_web_edition("T", [{"name": "N", "emoji": "*", "items": [yt]}])
    assert "http://t/1.jpg" in html

def test_save_edition_writes_index_and_dated_copy(tmp_path):
    out = str(tmp_path / "docs")
    paths = save_edition(out, "<html>hi</html>", "2026-06-29", "morning")
    assert Path(paths["index"]) == Path(out) / "index.html"
    assert Path(paths["edition"]) == Path(out) / "editions" / "2026-06-29-morning.html"
    assert Path(paths["index"]).read_text() == "<html>hi</html>"

def _edition(tmp_out, date, slot, items, section="Sec"):
    html = build_web_edition("E", [{"name": section, "emoji": "*", "items": items}],
                             edition_date=date, slot_key=slot)
    save_edition(str(tmp_out), html, date, slot)

def test_archive_merges_editions_dedups_and_lists_them(tmp_path):
    out = tmp_path / "docs"
    _edition(out, "2026-06-28", "evening",
             [_item("Old story", url="https://x/old", extra={"priority": "first", "why": "w"})])
    _edition(out, "2026-06-29", "morning",
             [_item("Old story again", url="https://x/old/"),  # same URL: first appearance wins
              _item("New story", url="https://x/new", extra={"priority": "today"})], section="Fresh")
    (out / "editions" / "2026-06-27-morning.html").write_text("legacy page without data")
    rows = collect_archive(str(out))
    assert [r["title"] for r in rows] == ["Old story", "New story"]
    assert rows[0]["date"] == "2026-06-28" and rows[0]["p"] == "first"
    assert rows[1]["section"] == "Fresh" and rows[1]["file"] == "2026-06-29-morning.html"
    html = build_archive_index(str(out), site_title="Canopy")
    assert (out / "archive.html").exists() and "Canopy — Archive" in html
    assert "2 stories · 3 editions" in html
    assert 'id="q"' in html and 'id="archive-data"' in html
    # every edition file is linked, newest first, including the legacy one
    assert html.index("2026-06-29") < html.index("2026-06-28") < html.index("2026-06-27")
    assert "editions/2026-06-27-morning.html" in html

def test_archive_index_empty(tmp_path):
    out = tmp_path / "docs"
    (out / "editions").mkdir(parents=True)
    html = build_archive_index(str(out))
    assert "No past editions yet." in html and "0 editions" in html

def test_palette_applied_to_web_and_archive(tmp_path):
    from briefing.theme import PALETTE
    page = build_web_edition("The Edge", [])
    archive = build_archive_index(str(tmp_path), site_title="The Edge")
    for html in (page, archive):
        style = html.split("<style>")[1].split("</style>")[0]
        assert PALETTE["orange"] in style and PALETTE["cobalt"] in style
        assert "$" not in style


def _mk(t, source="S", summary="s", **extra):
    return Item.make(source=source, source_type="rss", title=t, url="https://x/" + t.replace(" ", "-"),
                     summary=summary, published=datetime.now(timezone.utc), extra=extra)

def _triage_themes():
    also = [_mk("GPT-6 lands", source="OpenAI News"), _mk("Opus 5.5 recap", source="Latent Space")]
    first = _mk("Marketplace", priority="first", rank=0, why="Rail for <vertical> AI.",
                image="https://cdn/a.jpg", minutes=4)
    first2 = _mk("Model Vault", priority="first", rank=1, why="Sovereign demand.", image="https://cdn/b.jpg")
    today = _mk("Price war", priority="today", rank=2, why="Cheaper passes.", image="https://cdn/c.jpg",
                minutes=6, also=also, cluster_title="Opus 5.5 and GPT-6 land on the same day")
    later = [_mk(f"Skim {n}", priority="later", rank=3 + n, summary="" if n == 0 else "gist")
             for n in range(4)]
    return [{"name": "Anthropic Empire", "tab": "Anthropic", "emoji": "*",
             "items": [first, today, later[0], later[1]]},
            {"name": "Follow the Money", "tab": "Money", "emoji": "*",
             "items": [first2, later[2], later[3]]}]

SUMMARY = [{"lead": "Price war.", "text": "Frontier prices fell <40%>.", "ref": {"stories": [3]}},
           {"lead": "Platforms close in.", "text": "Two moves.", "ref": {"stories": [1, 2]}},
           {"lead": "Money moves.", "text": "Deals.", "ref": {"section": 1}}]

def test_triage_page_has_summary_order_and_skim_but_no_decks():
    body = _body(build_web_edition("E", _triage_themes(), summary=SUMMARY, org="Khare",
                                   edition_date="2026-09-24", slot_key="daily"))
    page = body.split('<script id="edition-data"')[0]
    for gone in ('class="deck', 'class="tab"', 'class="panel"', 'class="filter-row', 'class="dcard'):
        assert gone not in page
    assert 'id="summary"' in page and 'id="order-0"' in page and 'id="skim-0"' in page
    # triage bar: numbered jump links with counts, progress hidden until JS runs
    assert '<span class="ix">01</span>Summary</a>' in page
    assert 'href="#order-0"><span class="ix">02</span>Read first<span class="n">2</span>' in page
    assert 'href="#order-2"><span class="ix">03</span>Read today<span class="n">1</span>' in page
    assert 'href="#skim"><span class="ix">04</span>Skim<span class="n">4</span>' in page
    assert '<div class="prog" hidden><span><b id="done">0</b> of 3 read</span>' in page
    # summary: escaped takeaways, jump links from each ref
    assert "<b>Price war.</b> Frontier prices fell &lt;40%&gt;." in page
    assert 'href="#order-2">→ Story 3</a>' in page and 'href="#order-0">→ Stories 1 and 2</a>' in page
    assert 'href="#skim-1">→ Skim: Money</a>' in page
    # time budget: firsts 4+3, all 4+3+6, skim 4 x 0.5
    assert "7 min</span><span class=\"what\">Read stories 1 and 2" in page
    assert "The two that change what Khare does this quarter" in page
    assert "13 min</span><span class=\"what\">All three in the reading order" in page
    assert "+2 min</span><span class=\"what\">Skim the other 4" in page
    # reading order: rank order across themes, cluster title and sources
    order = page.split('id="order"')[1].split('id="skim"')[0]
    assert order.index("Marketplace") < order.index("Model Vault") < order.index("Opus 5.5 and GPT-6")
    assert "3 stories · ~13 min" in order
    assert '<article class="item first" id="order-0" data-n="0">' in order
    assert '<article class="item today" id="order-2" data-n="2">' in order
    assert "Anthropic · 4 min" in order and "Anthropic · 6 min" in order and "Money · 3 min" in order
    assert "· 3 sources, 1 story" in order and "Also covered by" in order and ">OpenAI News</a>" in order
    assert "Why it matters for Khare</b>Rail for &lt;vertical&gt; AI." in order
    # pictures: Read first only by default
    assert 'src="https://cdn/a.jpg"' in order and 'src="https://cdn/b.jpg"' in order
    assert "https://cdn/c.jpg" not in order and 'referrerpolicy="no-referrer"' in order
    # skim: grouped by section, expanded without JS, fallback gist
    skim = page.split('id="skim"')[1]
    assert 'data-expanded="false"' in page and 'id="skim-1"' in skim
    assert skim.count('class="srow"') == 4 and "Marketplace" not in skim and "GPT-6 lands" not in skim
    assert "No summary in the feed; open the article for the full story." in skim
    assert 'aria-expanded="true" aria-controls="gist-0-0"' in skim
    assert "9 stories from 3 sources · 3 worth reading" in page  # cluster members count
    assert "edge-read-2026-09-24-daily" in page

def test_reading_images_option_and_no_summary():
    themes = _triage_themes()
    all_ = _body(build_web_edition("E", themes, reading_images="all"))
    none = _body(build_web_edition("E", themes, reading_images="none", skim_expanded=True))
    assert 'src="https://cdn/c.jpg"' in all_
    assert 'class="item-pic"' not in none and 'data-expanded="true"' in none
    assert 'id="summary"' not in none and "Summary</a>" not in none  # no summary: section hidden
    assert "Why it matters</b>" in none  # no org

def test_unlabelled_edition_leads_with_first_story_and_skims_the_rest():
    body = _body(build_web_edition("E", [{"name": "T", "emoji": "*",
                                          "items": [_mk("Lead"), _mk("Other")]}]))
    order = body.split('id="order"')[1].split('id="skim"')[0]
    assert "Lead" in order and "Other" not in order and "badge" not in order
    assert "Reading order<span" in body and "worth reading" not in body
    assert "3 min" in order  # read time falls back to 3 minutes

def test_edition_data_rows_carry_minutes_and_also(tmp_path):
    import json
    html = build_web_edition("E", _triage_themes(), edition_date="2026-09-24", slot_key="daily")
    rows = json.loads(html.split('<script id="edition-data" type="application/json">')[1]
                      .split("</script>")[0])
    by_title = {r["title"]: r for r in rows}
    assert len(rows) == 7  # cluster members ride along in their lead's "also"
    assert by_title["Price war"]["minutes"] == 6 and by_title["Model Vault"]["minutes"] == 3
    assert by_title["Skim 1"]["minutes"] is None
    assert [a["source"] for a in by_title["Price war"]["also"]] == ["OpenAI News", "Latent Space"]
    assert by_title["Price war"]["cluster"].startswith("Opus 5.5")
    save_edition(str(tmp_path), html, "2026-09-24", "daily")
    assert "Price war" in build_archive_index(str(tmp_path))


def test_edition_links_the_archive_and_embeds_topic_and_summary():
    import json
    themes = _triage_themes()
    themes[0]["items"][0].extra["topic"] = "Governed AI"
    html = build_web_edition("The Edge", themes, summary=SUMMARY, edition_date="2026-09-24")
    page = _body(html).split('<script id="edition-data"')[0]
    bar = page.split('class="tbar"')[1].split("</nav>")[0]
    assert '<a class="abtn" href="archive.html">Search the archive →</a>' in bar
    cta = page.split('class="acta"')[1]
    assert page.index('id="skim"') < page.index('class="acta"')
    assert '<a class="acta" href="archive.html">' in page and "Open the archive →" in cta
    assert "Search every story The Edge has sent, by topic, priority or source." in cta
    rows = json.loads(html.split('<script id="edition-data" type="application/json">')[1].split("</script>")[0])
    by = {r["title"]: r for r in rows}
    assert by["Marketplace"]["topic"] == "Governed AI" and by["Skim 1"]["topic"] == ""
    assert by["Marketplace"]["n"] == 1 and by["Price war"]["n"] == 3 and by["Skim 1"]["n"] is None
    summary = json.loads(html.split('<script id="edition-summary" type="application/json">')[1].split("</script>")[0])
    assert summary[0] == {"lead": "Price war.", "text": "Frontier prices fell <40%>."}

def test_archive_has_topics_day_takes_and_reads_old_editions(tmp_path):
    import json
    from briefing.web import collect_takes
    out = tmp_path / "docs"
    themes = _triage_themes()
    themes[0]["items"][0].extra["topic"] = "Governed AI"
    save_edition(str(out), build_web_edition("E", themes, summary=SUMMARY, edition_date="2026-09-24",
                                             slot_key="daily"), "2026-09-24", "daily")
    # an edition from before topics, minutes and summaries existed
    old = [{"title": "Old one", "url": "https://x/old", "source": "S", "summary": "", "image": "",
            "p": "first", "why": "w", "section": "T", "tab": "T"}]
    (out / "editions").mkdir(exist_ok=True)
    (out / "editions" / "2026-09-20-daily.html").write_text(
        '<script id="edition-data" type="application/json">' + json.dumps(old) + "</script>")
    assert collect_takes(str(out)) == {"2026-09-24": "Price war. Frontier prices fell <40%>."}
    html = build_archive_index(str(out), site_title="The Edge", topics=["Governed AI", "Frontier models"])
    body = _body(html)
    assert 'id="q"' in body and 'placeholder="Headlines, companies, why-it-matters lines"' in body
    assert 'id="tiers"' in body and 'data-v="first"' in body and '<i class="dot-today"></i>' in body
    assert 'data-k="" aria-pressed="true"><span>All topics</span>' in body
    assert body.index('data-k="Governed AI"') < body.index('data-k="Frontier models"') < body.index('data-k="Other"')
    assert 'id="src"' in body and 'id="archive-takes"' in body
    rows = json.loads(body.split('<script id="archive-data" type="application/json">')[1].split("</script>")[0])
    assert {"Old one", "Marketplace"} <= {r["title"] for r in rows}
    assert "\\u003c40%>" in body or "\u003c40%>" in body  # takes escaped inside the script block

EXPLAINER = {"concept": "M<C>P", "why": "Story 3 <runs> on it.", "ref": {"stories": [3]},
             "steps": [{"icon": "📦", "text": "Apps <expose> tools"}, {"icon": "🔌", "text": "One plug"},
                       {"icon": "🤖", "text": "Agent calls any tool"}]}

def test_explainer_sits_between_order_and_skim_and_is_escaped():
    body = _body(build_web_edition("E", _triage_themes(), explainer=EXPLAINER,
                                   edition_date="2026-09-24", slot_key="daily"))
    page = body.split('<script id="edition-data"')[0]
    assert page.index('id="order"') < page.index('id="explain"') < page.index('id="skim"')
    assert "Explain it simply<span>M&lt;C&gt;P</span>" in page
    assert "Apps &lt;expose&gt; tools" in page and "<expose>" not in page
    assert '<p class="why-line"><b>Why today:</b> Story 3 &lt;runs&gt; on it.</p>' in page
    assert '<a class="jump go" href="#order-2">→ Story 3</a>' in page
    assert page.count('<span class="sn">Step') == 3
    assert '<a class="tj go" href="#explain">' in body
    assert '<script id="edition-explainer" type="application/json">' in body

def test_no_explainer_no_section():
    body = _body(build_web_edition("E", _triage_themes(), edition_date="2026-09-24"))
    assert 'id="explain"' not in body and "edition-explainer" not in body
    assert 'href="#explain"' not in body
