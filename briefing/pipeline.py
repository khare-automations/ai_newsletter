from __future__ import annotations
from datetime import datetime
from briefing.sources import fetch_all
from briefing.history import (load_history, save_history, drop_seen, mark_seen,
                              recent_titles, remember_order)
from briefing.filter import apply_filter
from briefing.enrich import group_into_themes
from briefing.priority import prioritize, order_themes, reading_list, triage, display_title
from briefing.images import add_images
from briefing.summary import summarize
from briefing.explain import explain, RECENT_KEEP as EXPLAIN_KEEP
from briefing.voice import compose_greeting, RECENT_KEEP
from briefing.editions import pick_edition
from briefing.email import build_html_email, send_email, top_pick_subject, check_login, cover_preheader
from briefing.web import build_web_edition, save_edition, build_archive_index, collect_archive
from briefing.weekly import (is_weekly, skips_today, picks_wanted, week_candidates, pick_week,
                             weekly_themes, WEEKLY_LABEL, WEEKLY_SLOT)

EDITIONS = ("auto", "daily", "weekly")

def run(cfg, history_path="history.json", now=None, *, edition="auto", preview=False,
        only_if_unsent=False) -> None:
    """One edition, start to finish.

    `edition` forces "daily" or "weekly" regardless of the day ("auto" follows
    `schedule`; a forced edition also runs at weekends). `preview` sends the
    email with a "[Preview]" subject, ignores which stories were already sent,
    and saves nothing: no history, no web edition, so the real edition still
    has every story. `only_if_unsent` is
    for a run that must not double-send: skip if history says an edition already went out today.
    """
    now = now or datetime.now()  # local time decides which edition (AM/PM) runs
    today = now.strftime("%Y-%m-%d")
    if edition not in EDITIONS:
        raise ValueError(f"edition must be one of {EDITIONS}, got {edition!r}")
    if edition == "auto" and skips_today(cfg.schedule, now):
        print(f"[pipeline] {now:%A}: no edition at weekends (schedule.skip_weekends)", flush=True)
        return
    if only_if_unsent and load_history(history_path).get("last_sent") == today:
        print(f"[pipeline] today's edition already went out; run not needed", flush=True)
        return
    weekly = is_weekly(cfg.schedule, now) if edition == "auto" else edition == "weekly"
    slot = pick_edition(cfg.editions, now.hour)
    title = f"{cfg.title} — {slot['label']}" if slot.get("label") else cfg.title

    check_login()  # fail fast on a bad mail password, before fetching or paying for Claude
    raw = fetch_all(cfg)
    print(f"[pipeline] fetched {len(raw)} items", flush=True)
    hist = load_history(history_path)
    # A preview shows what an edition built from today's news looks like, even
    # right after the real one went out, so it doesn't skip stories already sent.
    fresh = list(raw) if preview else drop_seen(raw, hist)
    print(f"[pipeline] {len(fresh)} fresh after dedup", flush=True)
    if not fresh:
        print("[pipeline] nothing new; skipping edition", flush=True)
        return
    selected = apply_filter(fresh, cfg)
    print(f"[pipeline] {len(selected)} after filter ({cfg.filter_mode})", flush=True)

    add_images(selected, cfg.images)    # optional: preview image + read time per item
    # optional: labels read first / today / later and folds duplicate coverage
    # of one event into its lead story (the others ride along in extra["also"])
    selected = prioritize(selected, cfg.priority, topics=cfg.topics(),
                          recent=recent_titles(hist, today))
    themes = order_themes(group_into_themes(selected, cfg.voice))
    if weekly:
        # Friday: the week's top stories (from the archive + today) replace the
        # daily reading order; today's other stories stay as the skim list.
        past = collect_archive(cfg.web.get("output_dir", "docs")) if cfg.web.get("enabled") else []
        picks, summary = pick_week(week_candidates(past, themes, now), picks_wanted(cfg.schedule),
                                   profile=cfg.priority)
        if picks:
            themes = weekly_themes(picks, themes)
            slot = {"key": WEEKLY_SLOT, "label": WEEKLY_LABEL}
            title = f"{cfg.title} — {WEEKLY_LABEL}"
        else:
            print("[pipeline] no stories this week to pick from; sending a daily edition", flush=True)
            weekly = False
    if not weekly:
        summary = summarize(themes, cfg.summary, profile=cfg.priority)  # optional: "The day in 30 seconds"
    # optional: "Explain it simply", one concept from the reading order in emoji steps
    explainer = explain(themes, cfg.explain, recent=hist.get("recent_explainers"))
    greeting = compose_greeting(cfg.voice, themes, recent=hist.get("recent_greetings"))
    org = cfg.priority.get("org", "") if cfg.priority.get("enabled") else ""

    # Web edition (optional): write the browsable page + permanent archive copy.
    if cfg.web.get("enabled") and not preview:
        out_dir = cfg.web.get("output_dir", "docs")
        page = build_web_edition(title, themes, greeting=greeting,
                                 edition_label=slot.get("label", ""),
                                 date_str=now.strftime("%A %d %B %Y").replace(" 0", " "),
                                 edition_date=now.strftime("%Y-%m-%d"), slot_key=slot["key"],
                                 summary=summary, org=org,
                                 reading_images=cfg.web.get("reading_images", "first"),
                                 skim_expanded=bool(cfg.web.get("skim_expanded", False)),
                                 weekly=weekly, explainer=explainer)
        paths = save_edition(out_dir, page, now.strftime("%Y-%m-%d"), slot["key"])
        build_archive_index(out_dir, site_title=cfg.title, topics=cfg.topics())
        print(f"[pipeline] web edition -> {paths['edition']}", flush=True)

    must = reading_list(themes)
    lead = must[0].title if must else next(
        (t["items"][0].title for t in themes if t.get("items")), "")
    cover = cfg.email_mode == "cover"
    html = build_html_email(title, themes, greeting=greeting,
                            edition_url=cfg.web.get("edition_url", ""), cover=cover,
                            preheader=(cover_preheader(themes, greeting, summary) if cover
                                       else (greeting or lead)),
                            summary=summary, org=org, now=now,
                            unsubscribe=cfg.email_unsubscribe, address=cfg.email_address,
                            feedback=cfg.email_feedback, weekly=weekly, explainer=explainer)
    subject = top_pick_subject(title, themes) if cfg.email_subject == "top_pick" else None
    if preview:
        subject = "[Preview] " + (subject or f"{title} - {now:%b %d, %Y}")
    send_email(title, html, subject=subject, from_name=cfg.email_from_name)
    if preview:
        print("[pipeline] preview sent; history and web edition left untouched", flush=True)
        return

    mark_seen(hist, fresh)
    hist["last_sent"] = today  # only_if_unsent (and the Claude routine) check this
    remember_order(hist, [display_title(i) for i in triage(themes)[0]], today)
    if greeting:
        hist["recent_greetings"] = (hist.get("recent_greetings", []) + [greeting])[-RECENT_KEEP:]
    if explainer:
        hist["recent_explainers"] = (hist.get("recent_explainers", [])
                                     + [explainer["concept"]])[-EXPLAIN_KEEP:]
    save_history(history_path, hist)
