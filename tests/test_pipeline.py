from datetime import datetime, timezone
from unittest.mock import patch
from briefing.models import Item
from briefing.config import Config
from briefing.pipeline import run

def _cfg():
    return Config(title="B", filter_mode="recent", interests=[], max_items=5,
                  per_source_cap=2, recency_hours=24,
                  sources=[{"type": "rss", "name": "S", "url": "http://x"}])

def _item(uid):
    return Item.make(source="S", source_type="rss", title="T", url=f"http://x/{uid}",
                     summary="s", published=datetime.now(timezone.utc), id=uid)

def test_run_dedups_filters_and_sends(tmp_path):
    hist_path = str(tmp_path / "h.json")
    sent = {}
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a"), _item("b")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": ["a"]}), \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": items}]), \
         patch("briefing.pipeline.send_email",
               side_effect=lambda title, html, **kw: sent.update(title=title, html=html)), \
         patch("briefing.pipeline.save_history") as save:
        run(_cfg(), history_path=hist_path)
    assert "b" in sent["html"] or "T" in sent["html"]
    saved = save.call_args[0][1]["seen_ids"]
    assert "b" in saved and "a" in saved

def test_run_writes_web_edition_when_enabled(tmp_path):
    docs = tmp_path / "docs"
    cfg = Config(title="B", filter_mode="recent", interests=[], max_items=5,
                 per_source_cap=2, recency_hours=24,
                 sources=[{"type": "rss", "name": "S", "url": "http://x"}],
                 web={"enabled": True, "output_dir": str(docs)},
                 editions=[{"key": "morning", "label": "Morning", "until_hour": 12}])
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": []}), \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": items}]), \
         patch("briefing.pipeline.send_email"), \
         patch("briefing.pipeline.save_history"):
        run(cfg, history_path=str(tmp_path / "h.json"),
            now=datetime(2026, 6, 29, 9, 0, 0))  # 09:00 -> morning edition
    assert (docs / "index.html").exists()
    assert (docs / "editions" / "2026-06-29-morning.html").exists()
    assert (docs / "archive.html").exists()
    assert "Morning" in (docs / "index.html").read_text()

def test_run_no_fresh_items_skips_send(tmp_path):
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": ["a"]}), \
         patch("briefing.pipeline.send_email") as send, \
         patch("briefing.pipeline.save_history"):
        run(_cfg(), history_path=str(tmp_path / "h.json"))
    send.assert_not_called()

def test_run_prioritizes_before_theming_and_leads_with_read_first(tmp_path):
    cfg = Config(title="B", filter_mode="recent", interests=[], max_items=5,
                 per_source_cap=2, recency_hours=24,
                 sources=[{"type": "rss", "name": "S", "url": "http://x"}],
                 priority={"enabled": True, "context": "x"}, email_subject="top_pick")
    def label(items, pcfg, topics=(), recent=()):
        items[1].extra.update(priority="first", why="w")
        return items
    sent = {}
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a"), _item("b")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": []}), \
         patch("briefing.pipeline.prioritize", side_effect=label) as pr, \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": list(items)}]), \
         patch("briefing.pipeline.send_email",
               side_effect=lambda title, html, **kw: sent.update(html=html, **kw)), \
         patch("briefing.pipeline.save_history"):
        run(cfg, history_path=str(tmp_path / "h.json"))
    assert pr.call_args[0][1] == cfg.priority
    assert "Read first today" in sent["html"]
    assert sent["html"].index("badge-first") < sent["html"].index("http://x/a")  # b sorted first

def test_run_adds_images_to_selected_items(tmp_path):
    cfg = Config(title="B", filter_mode="recent", interests=[], max_items=5,
                 per_source_cap=2, recency_hours=24,
                 sources=[{"type": "rss", "name": "S", "url": "http://x"}], images={"enabled": True})
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": []}), \
         patch("briefing.pipeline.add_images") as imgs, \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": items}]), \
         patch("briefing.pipeline.send_email"), patch("briefing.pipeline.save_history"):
        run(cfg, history_path=str(tmp_path / "h.json"))
    assert [i.id for i in imgs.call_args[0][0]] == ["a"] and imgs.call_args[0][1] == {"enabled": True}

def test_run_folds_clusters_summarizes_and_sends_cover(tmp_path):
    cfg = Config(title="B", filter_mode="recent", interests=[], max_items=5,
                 per_source_cap=2, recency_hours=24,
                 sources=[{"type": "rss", "name": "S", "url": "http://x"}],
                 priority={"enabled": True, "context": "x", "org": "Khare"},
                 summary={"enabled": True}, email_mode="cover",
                 web={"enabled": True, "output_dir": str(tmp_path / "docs"),
                      "edition_url": "https://site/"})
    def label(items, pcfg, topics=(), recent=()):
        a, b = sorted(items, key=lambda i: i.id)
        a.extra.update(priority="first", why="w", also=[b])
        return [a]  # b folded into a
    seen = {}
    def grouped(items, voice=None):
        seen["themed"] = [i.id for i in items]
        return [{"name": "T", "emoji": "X", "items": list(items)}]
    summary = [{"lead": "Big day.", "text": "Something happened.", "ref": {"stories": [1]}}]
    sent = {}
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a"), _item("b")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": []}), \
         patch("briefing.pipeline.prioritize", side_effect=label), \
         patch("briefing.pipeline.group_into_themes", side_effect=grouped), \
         patch("briefing.pipeline.summarize", return_value=summary) as summ, \
         patch("briefing.pipeline.send_email",
               side_effect=lambda title, html, **kw: sent.update(html=html)), \
         patch("briefing.pipeline.save_history") as save:
        run(cfg, history_path=str(tmp_path / "h.json"))
    assert seen["themed"] == ["a"] and summ.call_args[0][1] == {"enabled": True}
    assert summ.call_args.kwargs["profile"] == cfg.priority
    assert "<b>Big day.</b> Something happened." in sent["html"]
    assert "For Khare:" in sent["html"] and "Big day: Something happened." in sent["html"]
    assert "Big day." in (tmp_path / "docs" / "index.html").read_text()
    assert set(save.call_args[0][1]["seen_ids"]) >= {"a", "b"}  # the folded duplicate is seen too


def test_run_feeds_recent_reading_orders_to_priority_and_remembers_today(tmp_path):
    cfg = Config(title="B", filter_mode="recent", interests=[], max_items=5,
                 per_source_cap=2, recency_hours=24,
                 sources=[{"type": "rss", "name": "S", "url": "http://x"}],
                 priority={"enabled": True, "context": "x"})
    hist = {"seen_ids": [], "recent_order": [{"date": "2026-09-23", "title": "Yesterday's lead"}]}
    def label(items, pcfg, topics=(), recent=()):
        seen["recent"] = list(recent)
        items[0].extra.update(priority="first", why="w")
        return items
    seen = {}
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a")]), \
         patch("briefing.pipeline.load_history", return_value=hist), \
         patch("briefing.pipeline.prioritize", side_effect=label), \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": list(items)}]), \
         patch("briefing.pipeline.send_email"), patch("briefing.pipeline.save_history") as save:
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 24, 6, 13))
    assert seen["recent"] == ["Yesterday's lead"]
    saved = save.call_args[0][1]["recent_order"]
    assert {"date": "2026-09-24", "title": "T"} in saved

def _sched_cfg(tmp_path, **kw):
    return Config(title="The Edge", filter_mode="recent", interests=[], max_items=5,
                  per_source_cap=2, recency_hours=24,
                  sources=[{"type": "rss", "name": "S", "url": "http://x"}],
                  priority={"enabled": True, "context": "x", "org": "Khare"}, email_mode="cover",
                  web={"enabled": True, "output_dir": str(tmp_path / "docs"), "edition_url": "https://s/"},
                  schedule={"weekly_day": "friday", "skip_weekends": True}, **kw)

def test_run_sends_nothing_at_weekends(tmp_path):
    with patch("briefing.pipeline.check_login") as login, patch("briefing.pipeline.fetch_all") as fetch, \
         patch("briefing.pipeline.send_email") as send:
        run(_sched_cfg(tmp_path), history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 26, 6, 13))
    login.assert_not_called(); fetch.assert_not_called(); send.assert_not_called()

def test_friday_is_the_week_in_5(tmp_path):
    from briefing.web import build_web_edition, save_edition
    cfg = _sched_cfg(tmp_path, email_subject="top_pick")
    docs = str(tmp_path / "docs")
    mon = Item.make(source="Sifted", source_type="rss", title="Monday's big one", url="https://x/mon",
                    summary="s", published=datetime.now(timezone.utc), extra={"priority": "first", "why": "w"})
    save_edition(docs, build_web_edition("E", [{"name": "T", "items": [mon]}], edition_date="2026-09-21",
                                         slot_key="daily"), "2026-09-21", "daily")
    def label(items, pcfg, topics=(), recent=()):
        items[0].extra.update(priority="first", why="today w")
        return items
    weekly_reply = {"picks": [{"i": 0, "why": "Set the week's agenda."}, {"i": 1}],
                    "summary": [{"lead": "Big week.", "text": "Monday set it up.", "ref": {"stories": [1]}}]}
    sent = {}
    from tests.test_weekly import _client as weekly_client
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a"), _item("b")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": []}), \
         patch("briefing.pipeline.prioritize", side_effect=label), \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": list(items)}]), \
         patch("briefing.weekly._client", return_value=weekly_client(weekly_reply)), \
         patch("briefing.pipeline.summarize") as daily_summary, \
         patch("briefing.pipeline.send_email", side_effect=lambda title, html, **kw: sent.update(title=title, html=html, **kw)), \
         patch("briefing.pipeline.save_history"):
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 25, 6, 13))
    daily_summary.assert_not_called()
    assert sent["title"] == "The Edge — Week in 5" and sent["subject"] == "The Edge — Week in 5 | Monday's big one"
    html = sent["html"]
    assert "The week in 30 seconds" in html and "The week in 2" in html and "Your reading order" not in html
    order = html.split(">The week in 2<")[1].split("Skim if you have time")[0]
    assert order.index("Monday") < order.index("http://x/") and "Sifted &middot; Mon &middot;" in order
    assert "Read first</span>" not in order  # every pick is a top story; no badge needed
    assert sent["html"].count("The week in 2 (~") == 1  # inbox preview
    assert "Set the week&#x27;s agenda." in order or "Set the week's agenda." in order
    page = (tmp_path / "docs" / "editions" / "2026-09-25-weekly.html").read_text()
    assert "Week in 5" in page and "The week in 30 seconds" in page and "Mon · " in page

def test_friday_without_a_week_to_pick_from_sends_a_daily(tmp_path):
    cfg = _sched_cfg(tmp_path)
    cfg.web = {}
    sent = {}
    with patch("briefing.pipeline.fetch_all", return_value=[_item("a")]), \
         patch("briefing.pipeline.load_history", return_value={"seen_ids": []}), \
         patch("briefing.pipeline.prioritize", side_effect=lambda items, *a, **k: items), \
         patch("briefing.pipeline.group_into_themes",
               side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": list(items)}]), \
         patch("briefing.pipeline.summarize", return_value=[]) as daily_summary, \
         patch("briefing.pipeline.send_email", side_effect=lambda title, html, **kw: sent.update(title=title, html=html)), \
         patch("briefing.pipeline.save_history"):
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 25, 6, 13))
    daily_summary.assert_called_once()
    assert sent["title"] == "The Edge" and "Your reading order" in sent["html"]

def _quick_patches(tmp_path, sent, hist=None, saved=None):
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("briefing.pipeline.fetch_all", return_value=[_item("a")]))
    stack.enter_context(patch("briefing.pipeline.load_history", return_value=hist or {"seen_ids": []}))
    stack.enter_context(patch("briefing.pipeline.prioritize", side_effect=lambda items, *a, **k: items))
    stack.enter_context(patch("briefing.pipeline.group_into_themes",
                              side_effect=lambda items, voice=None: [{"name": "T", "emoji": "X", "items": list(items)}]))
    stack.enter_context(patch("briefing.pipeline.summarize", return_value=[]))
    stack.enter_context(patch("briefing.pipeline.send_email",
                              side_effect=lambda title, html, **kw: sent.update(title=title, html=html, **kw)))
    save = stack.enter_context(patch("briefing.pipeline.save_history"))
    return stack, save

def test_preview_sends_but_saves_nothing(tmp_path):
    cfg = _sched_cfg(tmp_path)
    sent = {}
    # every story was already sent: a preview still builds from them
    stack, save = _quick_patches(tmp_path, sent, hist={"seen_ids": ["a"]})
    with stack:
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 24, 8, 30),
            edition="daily", preview=True)
    assert sent["subject"] == "[Preview] The Edge - Sep 24, 2026"
    save.assert_not_called()
    assert not (tmp_path / "docs").exists()  # no web edition, no archive rebuild

def test_forced_edition_overrides_the_weekday_and_weekends(tmp_path):
    cfg = _sched_cfg(tmp_path)
    sent = {}
    stack, _ = _quick_patches(tmp_path, sent)
    with stack:  # a Saturday, forced daily: runs; Friday forced daily: no Week in 5
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 26, 9), edition="daily")
        assert sent["title"] == "The Edge"
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 25, 9), edition="daily")
        assert sent["title"] == "The Edge"
    import pytest
    with pytest.raises(ValueError):
        run(cfg, history_path=str(tmp_path / "h.json"), edition="monthly")

def test_backup_run_skips_when_today_already_went_out(tmp_path):
    cfg = _sched_cfg(tmp_path)
    sent = {}
    stack, save = _quick_patches(tmp_path, sent, hist={"seen_ids": [], "last_sent": "2026-09-24"})
    with stack:
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 24, 7, 15), only_if_unsent=True)
        assert sent == {}
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 25, 7, 15), only_if_unsent=True)
    assert sent and save.call_args[0][1]["last_sent"] == "2026-09-25"

EXPLAINER = {"concept": "MCP", "why": "w", "ref": {"stories": [1]},
             "steps": [{"icon": "📦", "text": "One"}, {"icon": "🔌", "text": "Two"},
                       {"icon": "🤖", "text": "Three"}]}

def test_explainer_is_rendered_and_remembered(tmp_path):
    cfg = _sched_cfg(tmp_path, explain={"enabled": True})
    sent = {}
    hist = {"seen_ids": [], "recent_explainers": [f"C{n}" for n in range(20)]}
    stack, save = _quick_patches(tmp_path, sent, hist=hist)
    with stack, patch("briefing.pipeline.explain", return_value=EXPLAINER) as ex:
        run(cfg, history_path=str(tmp_path / "h.json"), now=datetime(2026, 9, 24, 6, 13))
    assert ex.call_args[0][1] == {"enabled": True}
    assert ex.call_args.kwargs["recent"] == [f"C{n}" for n in range(20)]
    assert "Explain it simply" in sent["html"]
    assert 'id="explain"' in (tmp_path / "docs" / "index.html").read_text()
    remembered = save.call_args[0][1]["recent_explainers"]
    assert len(remembered) == 20 and remembered[-1] == "MCP" and "C0" not in remembered

def test_preview_does_not_remember_the_explainer(tmp_path):
    sent = {}
    stack, save = _quick_patches(tmp_path, sent)
    with stack, patch("briefing.pipeline.explain", return_value=EXPLAINER):
        run(_sched_cfg(tmp_path), history_path=str(tmp_path / "h.json"),
            now=datetime(2026, 9, 24, 6, 13), preview=True)
    assert "Explain it simply" in sent["html"]
    save.assert_not_called()
