from datetime import datetime, timezone
from briefing.models import Item
from briefing.email import build_html_email, _recipients

def _item(t, st="rss", extra=None):
    return Item.make(source="Src", source_type=st, title=t, url="http://x/1",
                     summary="a summary", published=datetime.now(timezone.utc), extra=extra or {})

def test_build_html_contains_title_and_cards():
    themes = [{"name": "Theme A", "emoji": "X", "items": [_item("Headline One")]}]
    html = build_html_email("Claire's Briefing", themes)
    assert "Claire" in html  # title present (apostrophe may be escaped)
    assert "Theme A" in html
    assert "Headline One" in html
    assert "http://x/1" in html

def test_youtube_item_renders_embed():
    yt = _item("Vid", st="youtube", extra={"embed_url": "http://e/v1", "thumbnail": "http://t/1"})
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [yt]}])
    assert "http://e/v1" in html or "http://t/1" in html

def test_titles_are_html_escaped():
    it = _item("AI raises $10M & acquires <Startup>")
    html = build_html_email("B", [{"name": "T & U", "emoji": "X", "items": [it]}])
    assert "&amp;" in html
    assert "&lt;Startup&gt;" in html
    assert "<Startup>" not in html  # raw angle brackets must not leak through

def test_javascript_url_is_blocked():
    it = _item("Click me")
    it.url = "javascript:alert(1)"
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [it]}])
    assert "javascript:" not in html
    assert 'href=""' in html  # scheme-rejected url renders empty

def test_greeting_is_rendered():
    themes = [{"name": "T", "emoji": "X", "items": [_item("H")]}]
    html = build_html_email("B", themes, greeting="Welcome back.")
    assert "Welcome back." in html

def test_cover_mode_is_short_and_links_to_edition():
    themes = [{"name": "Theme A", "emoji": "X", "items": [_item("Opening")]},
              {"name": "Theme B", "emoji": "Y", "tab": "B short", "items": [_item("Second")]}]
    html = build_html_email("B", themes, edition_url="https://site/ed", cover=True)
    assert "Opening" in html and "Second" in html   # every headline is listed...
    assert "a summary" not in html                 # ...but no story bodies
    order = html.split("Your reading order")[1].split("Skim if you have time")[0]
    assert "Opening" in order and "Second" in order  # no labels: each section's lead story
    assert 'href="https://site/ed"' in html and "Open the full edition" in html
    assert 'href="https://site/ed/archive.html"' in html

def _mk(t, source="Src", **extra):
    return Item.make(source=source, source_type="rss", title=t, url="https://x/" + t.replace(" ", "-"),
                     summary="a summary", published=datetime.now(timezone.utc), extra=extra)

def _triage_themes():
    also = [_mk("GPT-6 lands", source="OpenAI News"), _mk("Opus recap", source="Latent Space")]
    first = _mk("Marketplace", priority="first", rank=0, why="Rail for <vertical> AI.",
                image="https://cdn/a.jpg", minutes=4)
    first2 = _mk("Model Vault", priority="first", rank=1, why="Sovereign.", image="https://cdn/b.jpg")
    today = _mk("Price war", priority="today", rank=2, why="Cheaper.", minutes=6, also=also,
                cluster_title="Opus 5.5 and GPT-6 land on the same day")
    skim = [_mk(f"Skim {n}", priority="later", rank=3 + n) for n in range(5)]
    return [{"name": "Anthropic Empire", "tab": "Anthropic", "emoji": "*",
             "items": [first, today] + skim[:4]},
            {"name": "Follow the Money", "tab": "Money", "emoji": "*", "items": [first2, skim[4]]}]

SUMMARY = [{"lead": "Price war.", "text": "Opus 5.5 and GPT-6 cut frontier prices <40–50%>.",
            "ref": {"stories": [3]}},
           {"lead": "Money moves.", "text": "Deals.", "ref": None}]

def test_cover_is_triage_first():
    from datetime import datetime as dt
    html = build_html_email("The Edge", _triage_themes(), edition_url="https://site/", cover=True,
                            summary=SUMMARY, org="Khare", now=dt(2026, 9, 24, 6, 13),
                            unsubscribe="mailto:u@x.com?subject=Unsubscribe", address="Khare, Zurich")
    assert '<meta name="color-scheme" content="light only">' in html and "<!--[if mso]>" in html
    assert "light dark" not in html and ":root{color-scheme:light only" in html
    assert ">Thursday, 24 Sep</td>" in html
    assert "3 to read</b> (~13 min) &middot; <b" in html and ">5</b> to skim &middot; 3 sources" in html
    # the day in 30 seconds, escaped
    assert "The day in 30 seconds" in html
    assert "<b>Price war.</b> Opus 5.5 and GPT-6 cut frontier prices &lt;40–50%&gt;." in html
    assert html.index("The day in 30 seconds") < html.index("Your reading order") < html.index("Skim if you have time")
    # reading order: numbered, rank order, read times, for-org why, cluster sources
    order = html.split("Your reading order")[1].split("Skim if you have time")[0]
    assert "3 stories &middot; ~13 min" in order
    assert order.index("Marketplace") < order.index("Model Vault") < order.index("Opus 5.5 and GPT-6 land")
    assert "Src &middot; 4 min" in order and "Src &middot; 3 min" in order and "Src &middot; 6 min" in order
    assert '<b style="color:#0047AB;">For Khare:</b> Rail for &lt;vertical&gt; AI.' in order
    assert "Also covered by <a" in order and ">OpenAI News</a> &middot; <a" in order
    assert order.count("<img") == 1 and 'src="https://cdn/a.jpg" width="556"' in order  # #1 only
    assert "font-size:19px" in order and "font-size:17px" in order
    assert 'color:#0047AB;line-height:30px;mso-line-height-rule:exactly;">3</td>' in order
    # skim: at most three headlines, then a link to the rest on the web
    skim = html.split("Skim if you have time")[1]
    assert "Anthropic <span" in skim and "&middot; 4</span>" in skim
    assert "Skim 0" in skim and "Skim 2" in skim and "Skim 3" not in skim
    assert 'href="https://site/#skim-0"' in skim and "1 more in Anthropic &rarr;" in skim
    assert "Skim 4" in skim and "#skim-1" not in skim  # a short section needs no link
    assert "a summary" not in html  # no story bodies in the cover
    # CTA and footer
    assert 'bgcolor="#FF5F15"' in skim and "Open the full edition &rarr;" in skim
    assert "The Edge is curated by Claude from 3 sources for the team at Khare." in skim
    assert 'href="https://site/archive.html"' in skim and 'href="mailto:u@x.com?subject=Unsubscribe"' in skim
    assert "Khare, Zurich" in skim

def test_cover_preheader_leads_with_summary_then_shape():
    from briefing.email import cover_preheader
    themes = _triage_themes()
    pre = cover_preheader(themes, summary=SUMMARY)
    assert pre == ("Price war: Opus 5.5 and GPT-6 cut frontier prices <40–50%>. "
                   "2 to read first, 1 today (~13 min), 5 to skim.")
    assert cover_preheader(themes) == "2 to read first, 1 today (~13 min), 5 to skim."
    long = [{"lead": "Price war.", "text": "word " * 60, "ref": None}]
    pre = cover_preheader(themes, summary=long)
    assert len(pre) <= 140 and "word… 2 to read first" in pre
    short = [dict(SUMMARY[0], short="Opus 5.5 and GPT-6 cut prices 40–50%")]
    assert cover_preheader(themes, summary=short).startswith(
        "Price war: Opus 5.5 and GPT-6 cut prices 40–50%. 2 to read first")
    plain = [{"name": "T", "emoji": "", "items": [_item("Lead")]}]
    assert cover_preheader(plain, "Hi") == "Hi" and cover_preheader(plain) == "Lead"

def test_cover_without_priority_or_summary():
    themes = [{"name": "Theme A", "emoji": "X", "items": [_item("Opening"), _item("Next")]}]
    html = build_html_email("B", themes, edition_url="", cover=True)
    assert "The day in 30 seconds" not in html and "For " not in html
    order = html.split("Your reading order")[1].split("Skim if you have time")[0]
    assert "Opening" in order and "Read first" not in order and "3 min" in order
    assert "Next" in html.split("Skim if you have time")[1]
    assert "Open the full edition" not in html and "more in" not in html  # nowhere to link to
    assert "curated by Claude from 1 source." in html

def test_full_mode_is_light_only():
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [_item("H")]}])
    assert '<meta name="color-scheme" content="light only">' in html

def test_full_mode_shows_cluster_sources():
    it = _mk("Lead", also=[_mk("Dup", source="Other Pub")])
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [it]}])
    assert "Also covered by <a" in html and ">Other Pub</a>" in html

def test_recipients_parsing(monkeypatch):
    monkeypatch.delenv("EMAIL_RECIPIENTS", raising=False)
    monkeypatch.delenv("RECIPIENTS", raising=False)
    monkeypatch.setenv("EMAIL_RECIPIENT", "a@x.com, b@y.com ,")
    assert _recipients() == ["a@x.com", "b@y.com"]

def test_recipients_fallback_env_names(monkeypatch):
    monkeypatch.delenv("EMAIL_RECIPIENT", raising=False)
    monkeypatch.delenv("EMAIL_RECIPIENTS", raising=False)
    monkeypatch.setenv("RECIPIENTS", "only@z.com")
    assert _recipients() == ["only@z.com"]

def test_theme_emoji_is_escaped():
    html = build_html_email("B", [{"name": "T", "emoji": "<img src=x>", "items": [_item("H")]}])
    assert "<img src=x>" not in html

def test_each_recipient_gets_own_message(monkeypatch):
    from unittest.mock import patch, MagicMock
    from briefing.email import send_email
    monkeypatch.setenv("EMAIL_SENDER", "me@x.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "pw")
    monkeypatch.setenv("EMAIL_RECIPIENT", "a@x.com,b@y.com")
    server = MagicMock()
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        send_email("B", "<p>hi</p>")
    calls = server.sendmail.call_args_list
    assert [c.args[1] for c in calls] == [["a@x.com"], ["b@y.com"]]
    assert "b@y.com" not in calls[0].args[2]  # a never sees b's address

def test_preheader_is_hidden_and_escaped():
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [_item("H")]}],
                            preheader="Today <b>big</b> news")
    assert "display:none" in html
    assert "Today &lt;b&gt;big&lt;/b&gt; news" in html

def test_top_pick_subject_trims_at_word():
    from briefing.email import top_pick_subject
    it = _item("European regulators finally agree on the long awaited artificial intelligence rulebook")
    subj = top_pick_subject("Brief", [{"name": "T", "emoji": "X", "items": [it]}], limit=40)
    assert subj.startswith("Brief | European regulators")
    assert subj.endswith("…") and len(subj) <= len("Brief | ") + 41
    assert top_pick_subject("Brief", []) == "Brief"

def test_send_email_uses_subject_override(monkeypatch):
    from unittest.mock import patch, MagicMock
    from briefing.email import send_email
    for k, v in {"EMAIL_SENDER": "me@x.com", "EMAIL_PASSWORD": "pw",
                 "EMAIL_RECIPIENT": "a@x.com"}.items():
        monkeypatch.setenv(k, v)
    server = MagicMock()
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        send_email("B", "<p/>", subject="B | Lead story")
    assert "Subject: B | Lead story" in server.sendmail.call_args.args[2]

def test_palette_applied_to_email():
    from briefing.theme import PALETTE
    html = build_html_email("The Edge", [{"name": "T", "emoji": "X", "items": [_item("H")]}])
    for key in ("orange", "black", "cobalt"):
        assert PALETTE[key] in html
    assert "$" not in html.split("<style>")[1].split("</style>")[0]  # every placeholder filled

def test_from_name_sets_sender_display_name(monkeypatch):
    from unittest.mock import patch, MagicMock
    from briefing.email import send_email
    for k, v in {"EMAIL_SENDER": "me@x.com", "EMAIL_PASSWORD": "pw",
                 "EMAIL_RECIPIENT": "a@x.com"}.items():
        monkeypatch.setenv(k, v)
    server = MagicMock()
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        send_email("The Edge", "<p/>", from_name="The Edge")
        send_email("The Edge", "<p/>")
    first, second = (c.args[2] for c in server.sendmail.call_args_list)
    assert "From: The Edge <me@x.com>" in first
    assert "From: me@x.com" in second
    assert server.sendmail.call_args_list[0].args[0] == "me@x.com"  # envelope stays bare

def _labelled():
    first = _item("Intapp launches <Celeste> for small funds")
    first.extra.update(priority="first", why="Direct competitor moving into our <lane>.")
    today = _item("New eval method"); today.extra["priority"] = "today"
    later = _item("Consumer app news"); later.extra["priority"] = "later"
    return [{"name": "T", "emoji": "X", "items": [first, today, later]}]

def test_priority_badges_why_and_reading_list():
    html = build_html_email("The Edge", _labelled())
    body = html.split("</style>")[1]
    assert "Read first today" in body
    assert body.index("Read first today") < body.index('class="theme-title"')  # list on top
    assert 'badge-first">Read first' in body and 'badge-today">Read today' in body
    assert 'badge-later">Later' in body and "card-first" in body
    assert "Direct competitor moving into our &lt;lane&gt;." in body  # why escaped
    assert "<lane>" not in body and "<Celeste>" not in body

def test_no_labels_no_reading_list():
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [_item("H")]}])
    body = html.split("</style>")[1]
    assert "Read first today" not in body and "badge" not in body

def test_top_pick_subject_prefers_read_first():
    from briefing.email import top_pick_subject
    themes = _labelled()
    themes[0]["items"] = themes[0]["items"][::-1]  # a "later" item leads the theme
    assert "Intapp" in top_pick_subject("The Edge", themes)

def test_email_images_hero_for_first_thumb_for_rest_escaped():
    first = _item("Lead"); first.extra.update(priority="first", image='https://cdn/a.jpg?x=1&y="2"')
    rest = _item("Other"); rest.extra.update(priority="later", image="https://cdn/b.jpg")
    bad = _item("Bad"); bad.extra["image"] = "javascript:alert(1)"
    html = build_html_email("B", [{"name": "T", "emoji": "X", "items": [first, rest, bad]}])
    body = html.split("</style>")[1]
    assert 'class="hero" src="https://cdn/a.jpg?x=1&amp;y=&quot;2&quot;"' in body
    assert '<td class="thumb" width="100" valign="top">' in body and 'src="https://cdn/b.jpg"' in body
    assert "javascript:" not in body


def test_empty_smtp_env_falls_back_to_gmail_defaults(monkeypatch):
    from unittest.mock import patch, MagicMock
    from briefing.email import send_email
    for k, v in {"EMAIL_SENDER": "me@x.com", "EMAIL_PASSWORD": "pw", "EMAIL_RECIPIENT": "a@x.com",
                 "SMTP_HOST": "", "SMTP_PORT": ""}.items():   # unset secrets arrive as ""
        monkeypatch.setenv(k, v)
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = MagicMock()
        send_email("B", "<p/>")
    assert smtp.call_args.args == ("smtp.gmail.com", 587)


def test_email_from_alias_fronts_the_mail_but_login_stays_the_account(monkeypatch):
    from unittest.mock import patch, MagicMock
    from briefing.email import send_email, from_address, unsubscribe_link, feedback_address
    for k, v in {"EMAIL_SENDER": "me@x.com", "EMAIL_PASSWORD": "pw", "EMAIL_RECIPIENT": "a@x.com",
                 "EMAIL_FROM": "newsletter@x.com"}.items():
        monkeypatch.setenv(k, v)
    assert from_address() == "newsletter@x.com"
    assert unsubscribe_link("sender") == "mailto:newsletter@x.com?subject=Unsubscribe"
    assert feedback_address("sender") == "newsletter@x.com"
    server = MagicMock()
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        send_email("B", "<p/>", from_name="The Edge")
    server.login.assert_called_once_with("me@x.com", "pw")
    envelope_from, rcpts, raw = server.sendmail.call_args.args
    assert envelope_from == "newsletter@x.com" and rcpts == ["a@x.com"]
    assert "From: The Edge <newsletter@x.com>" in raw
    monkeypatch.setenv("EMAIL_FROM", "")            # unset secret arrives as ""
    assert from_address() == "me@x.com"


def test_check_login_skips_without_settings_and_logs_in_with_them(monkeypatch):
    from unittest.mock import patch, MagicMock
    from briefing.email import check_login
    monkeypatch.delenv("EMAIL_SENDER", raising=False); monkeypatch.setenv("EMAIL_PASSWORD", "")
    assert check_login() is False
    monkeypatch.setenv("EMAIL_SENDER", "me@x.com"); monkeypatch.setenv("EMAIL_PASSWORD", "app-pw")
    server = MagicMock()
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        assert check_login() is True
    server.login.assert_called_once_with("me@x.com", "app-pw")

def test_gmail_app_password_error_gets_a_hint(monkeypatch):
    import smtplib
    import pytest
    from unittest.mock import patch, MagicMock
    from briefing.email import check_login
    monkeypatch.setenv("EMAIL_SENDER", "me@gmail.com"); monkeypatch.setenv("EMAIL_PASSWORD", "account-pw")
    server = MagicMock()
    server.login.side_effect = smtplib.SMTPAuthenticationError(534, b"5.7.9 Application-specific password required")
    with patch("briefing.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        with pytest.raises(RuntimeError) as err:
            check_login()
    assert "App Password" in str(err.value) and "apppasswords" in str(err.value)


def test_cover_links_the_archive_twice():
    html = build_html_email("The Edge", _triage_themes(), edition_url="https://site/ed/", cover=True)
    body = html.split("</head>")[1]
    masthead = body.split("The day in 30 seconds")[0] if "The day in 30" in body else body.split("Your reading order")[0]
    assert 'href="https://site/ed/archive.html"' in masthead and "Search the archive &rarr;" in masthead
    assert "Search past editions in the Archive &rarr;" in body
    assert body.index("Open the full edition") < body.index("Search past editions")
    assert body.count('href="https://site/ed/archive.html"') == 3  # masthead, button, footer

def test_unsubscribe_sender_uses_the_sending_account(monkeypatch):
    from briefing.email import unsubscribe_link
    monkeypatch.setenv("EMAIL_SENDER", "edge@x.com")
    assert unsubscribe_link("sender") == "mailto:edge@x.com?subject=Unsubscribe"
    html = build_html_email("E", _triage_themes(), edition_url="https://s/", cover=True, unsubscribe="sender")
    assert 'href="mailto:edge@x.com?subject=Unsubscribe"' in html and ">Unsubscribe</a>" in html
    monkeypatch.delenv("EMAIL_SENDER")
    assert unsubscribe_link("sender") == "" and unsubscribe_link("javascript:x") == ""
    assert unsubscribe_link("https://x/unsub") == "https://x/unsub"


def test_followups_are_tagged_in_the_skim():
    themes = _triage_themes()
    themes[0]["items"][2].extra["followup"] = True   # "Skim 0"
    html = build_html_email("E", themes, edition_url="https://s/", cover=True)
    skim = html.split("Skim if you have time")[1]
    assert "Follow-up &middot; Src" in skim and skim.count("Follow-up") == 1


def test_feedback_links_are_mailto_votes_per_story(monkeypatch):
    from briefing.email import feedback_address
    from urllib.parse import unquote
    monkeypatch.setenv("EMAIL_SENDER", "edge@x.com")
    assert feedback_address("sender") == "edge@x.com" and feedback_address("team@x.co") == "team@x.co"
    assert feedback_address("javascript:alert(1)") == "" and feedback_address("a b@x.com") == ""
    html = build_html_email("E", _triage_themes(), edition_url="https://s/", cover=True, feedback="sender")
    order = html.split("Your reading order")[1].split("Skim if you have time")[0]
    assert order.count("Worth it?") == 3 and order.count('href="mailto:edge@x.com?subject=') == 6
    assert unquote("Useful%3A%20Marketplace") in unquote(order)
    assert "Not%20for%20us%3A%20Opus%205.5%20and%20GPT-6%20land%20on%20the%20same%20day" in order
    skim = html.split("Skim if you have time")[1]
    assert "Worth it?" not in skim
    assert "Worth it?" not in build_html_email("E", _triage_themes(), edition_url="https://s/", cover=True)

EXPLAINER = {"concept": "M<C>P", "why": "Story 3 <runs> on it.", "ref": {"stories": [3]},
             "steps": [{"icon": "📦", "text": "Apps <expose> tools"}, {"icon": "🔌", "text": "One plug"},
                       {"icon": "🤖", "text": "Agent calls any tool"}]}

def test_cover_explainer_follows_the_reading_order():
    html = build_html_email("E", _triage_themes(), edition_url="https://s/ed#x", cover=True,
                            explainer=EXPLAINER)
    assert html.index("Your reading order") < html.index("Explain it simply") < html.index("Skim if")
    assert ">M&lt;C&gt;P</td>" in html and "Apps &lt;expose&gt; tools" in html
    assert "Why today:</b> Story 3 &lt;runs&gt; on it." in html
    assert 'href="https://s/ed#order-2"' in html and "Story 3 &rarr;</a>" in html
    no_link = build_html_email("E", _triage_themes(), edition_url="", cover=True, explainer=EXPLAINER)
    assert "Explain it simply" in no_link and "#order-2" not in no_link

def test_explainer_only_in_the_cover():
    assert "Explain it simply" not in build_html_email("E", _triage_themes(), cover=True)
    assert "Explain it simply" not in build_html_email("E", _triage_themes(), explainer=EXPLAINER)
