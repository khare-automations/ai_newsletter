from __future__ import annotations
import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape
from urllib.parse import quote
from briefing.theme import css, PALETTE
from briefing.priority import (LABELS, reading_list, triage, all_items, read_minutes,
                               display_title)

SKIM_MAX = 3         # headlines per section in the cover email; the rest are on the web
PREHEADER_MAX = 140  # characters of inbox preview
# Every colour here is chosen for a light background, so tell mail apps not
# to restyle it for dark mode. Apple Mail and Outlook honour this; the Gmail
# apps may still invert, which the palette's contrast survives.
_LIGHT_ONLY = ('<meta name="color-scheme" content="light only">'
               '<meta name="supported-color-schemes" content="light only">')

_CSS = css(
    "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:$paper;"
    "color:$ink;margin:0}"
    ".wrapper{max-width:640px;margin:0 auto;padding:24px}"
    ".header{background:$black;border-bottom:4px solid $orange;border-radius:10px 10px 0 0;"
    "padding:20px 22px}"
    ".header h1{margin:0 0 4px;color:$white;letter-spacing:.5px}"
    ".date{color:$orange;font-size:13px;text-transform:uppercase;letter-spacing:1.5px}"
    ".theme-title{font-size:18px;font-weight:700;margin:24px 0 8px;color:$ink;"
    "border-left:4px solid $orange;padding-left:10px}"
    ".card{background:$white;border:1px solid $rule;border-radius:10px;padding:14px;"
    "margin:10px 0}"
    ".card a{color:$ink;text-decoration:none;font-weight:600}"
    ".card p{color:$muted}"
    ".src{color:$cobalt;font-size:12px;font-weight:700;text-transform:uppercase;"
    "letter-spacing:.5px}"
    ".footer{color:$muted;font-size:12px;margin-top:24px}"
    ".greeting{font-style:italic;color:$ink;background:$orange_tint;"
    "border-left:3px solid $cobalt;padding:12px 16px;margin:16px 0}"
    ".readmore{display:inline-block;margin:16px 0;padding:10px 18px;background:$orange;"
    "color:$black;border-radius:8px;text-decoration:none;font-weight:700}"
    ".toc{color:$ink;font-size:14px}.toc li{margin:2px 0}.toc li::marker{color:$cobalt}"
    # Reading-priority labels (priority.py): orange = read first, cobalt = today.
    ".badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.8px;"
    "text-transform:uppercase;padding:2px 7px;border-radius:4px;margin-right:6px;"
    "vertical-align:1px}"
    ".badge-first{background:$orange;color:$black}"
    ".badge-today{background:$white;color:$cobalt;border:1px solid $cobalt}"
    ".badge-later{background:$paper;color:$muted}"
    ".card-first{border-left:4px solid $orange}"
    ".card img.hero{display:block;width:100%;height:auto;border-radius:6px;margin:0 0 10px}"
    ".card td.thumb{padding-right:12px}"
    ".card td.thumb img{display:block;width:88px;height:auto;border-radius:4px}"
    ".why{color:$ink;font-size:14px;margin:6px 0}"
    ".reading{background:$white;border:2px solid $black;border-radius:10px;"
    "padding:14px 18px;margin:16px 0}"
    ".reading-title{display:inline-block;margin:0 0 8px;font-size:13px;font-weight:700;"
    "text-transform:uppercase;letter-spacing:1px;color:$black;"
    "border-bottom:3px solid $orange}"
    ".reading ol{margin:0;padding-left:20px}.reading li{margin:8px 0}"
    ".reading li::marker{color:$orange;font-weight:700}"
    ".reading a{color:$ink;font-weight:700;text-decoration:none}"
    ".reading .why{margin:2px 0 0;color:$muted}"
)

def _safe_url(url) -> str:
    """Only allow http(s) URLs into href/src; blank out anything else
    (e.g. javascript:, data:) to prevent script-URI injection."""
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else ""

def _safe_link(url) -> str:
    """Like _safe_url, but also allows mailto: (for an unsubscribe link)."""
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://", "mailto:")) else ""

def _badge(item) -> str:
    tier = item.extra.get("priority")
    return (f'<span class="badge badge-{tier}">{escape(LABELS[tier])}</span>'
            if tier in LABELS else "")

def _why(item) -> str:
    why = item.extra.get("why")
    return f'<p class="why"><b>Why it matters:</b> {escape(why)}</p>' if why else ""

def _reading_list(themes) -> str:
    """'Read first today' box at the top: the day's must-reads and why."""
    items = reading_list(themes)
    if not items:
        return ""
    rows = "".join(
        f'<li><a href="{escape(_safe_url(i.url), quote=True)}">{escape(i.title)}</a>'
        f' <span class="src">{escape(i.source)}</span>'
        + (f'<p class="why">{escape(i.extra["why"])}</p>' if i.extra.get("why") else "")
        + "</li>" for i in items)
    return f'<div class="reading"><p class="reading-title">Read first today</p><ol>{rows}</ol></div>'

def _image_url(item) -> str:
    return _safe_url(item.extra.get("image") or item.extra.get("thumbnail", ""))

def _card(item) -> str:
    href = escape(_safe_url(item.url), quote=True)
    img = escape(_image_url(item), quote=True)
    first = " card-first" if item.extra.get("priority") == "first" else ""
    text = (f'<div class="src">{_badge(item)}{escape(item.source)}</div>'
            f'<a href="{href}">{escape(item.title)}</a>{_why(item)}'
            f'<p>{escape(item.summary)}</p>{_also_line(item)}')
    if img and (first or item.source_type == "youtube"):
        # The big picture goes to what to read first (and videos) only.
        return (f'<div class="card{first}"><a href="{href}"><img class="hero" src="{img}" '
                f'alt="" width="100%"></a>{text}</div>')
    if img:
        # A small thumbnail beside the text. A table, because Gmail ignores
        # floats, flex and grid.
        return (f'<div class="card{first}"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0"><tr><td class="thumb" width="100" valign="top">'
                f'<a href="{href}"><img src="{img}" alt="" width="88"></a></td>'
                f'<td valign="top">{text}</td></tr></table></div>')
    return f'<div class="card{first}">{text}</div>'

def _also_line(item) -> str:
    """'Also covered by' links for a cluster lead (full mode)."""
    also = item.extra.get("also") or []
    if not also:
        return ""
    links = " · ".join(f'<a href="{escape(_safe_url(a.url), quote=True)}">{escape(a.source)}</a>'
                       for a in also)
    return f'<p class="why">Also covered by {links}</p>'

# ── Cover mode (email.mode: cover) ────────────────────────────────────────────
# A triage-first email: the day in 30 seconds, one numbered reading order with
# read times, then a short skim list per section and a button to the web
# edition. Tables and inline styles only, so Gmail and Outlook render it.

_F = "font-family:Arial,Helvetica,sans-serif;"
_LH = "mso-line-height-rule:exactly;"
_T = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
_P = PALETTE
_ON_BLACK = "#CFCFCF"  # secondary text on the black masthead

def _href(url) -> str:
    return escape(_safe_url(url), quote=True)

def _plural(n, one, many) -> str:
    return f"{n} {one if n == 1 else many}"

def _section_label(left, right) -> str:
    return (f'<tr><td style="padding:28px 0 10px 0;border-bottom:2px solid {_P["black"]};">'
            f'<table {_T}><tr><td style="{_F}font-size:12px;font-weight:bold;letter-spacing:1.5px;'
            f'text-transform:uppercase;color:{_P["black"]};">{left}</td>'
            f'<td align="right" style="{_F}font-size:12px;color:{_P["muted"]};">{right}</td>'
            f'</tr></table></td></tr>')

def _archive_url(link) -> str:
    return link.split("#")[0].rstrip("/") + "/archive.html" if link else ""

def from_address() -> str:
    """The address readers see in From: (and reply to). EMAIL_FROM lets a
    Workspace alias like newsletter@company.com front the mail while the SMTP
    login stays EMAIL_SENDER (Gmail honours a From: that is a verified "Send
    mail as" alias of the logged-in account). Defaults to EMAIL_SENDER."""
    return ((os.environ.get("EMAIL_FROM") or os.environ.get("EMAIL_SENDER")) or "").strip()

def unsubscribe_link(value) -> str:
    """The cover's Unsubscribe href. `sender` means a mailto: to the sending
    address (`from_address`), so the address never has to sit in config.yaml."""
    value = (value or "").strip()
    if value.lower() == "sender":
        sender = from_address()
        return f"mailto:{sender}?subject=Unsubscribe" if sender else ""
    return _safe_link(value)

def _cover_masthead(title, date_label, order, n_skim, n_sources, link="") -> str:
    shape = []
    if order:
        minutes = sum(read_minutes(i) for i in order)
        shape.append(f'<b style="color:{_P["white"]};">{len(order)} to read</b> (~{minutes} min)')
    if n_skim:
        shape.append(f'<b style="color:{_P["white"]};">{n_skim}</b> to skim')
    shape.append(_plural(n_sources, "source", "sources"))
    if link:
        shape.append(f'<a href="{escape(_archive_url(link), quote=True)}" style="color:{_P["orange"]};'
                     f'text-decoration:underline;font-weight:bold;">Search the archive &rarr;</a>')
    return (f'<tr><td bgcolor="{_P["black"]}" style="background:{_P["black"]};'
            f'border-bottom:4px solid {_P["orange"]};padding:20px 22px;"><table {_T}><tr>'
            f'<td valign="bottom" style="{_F}font-size:28px;font-weight:bold;color:{_P["white"]};'
            f'letter-spacing:.5px;line-height:32px;{_LH}">{escape(title)}</td>'
            f'<td valign="bottom" align="right" style="{_F}font-size:12px;color:{_P["orange"]};'
            f'letter-spacing:1.5px;text-transform:uppercase;line-height:18px;{_LH}">'
            f'{escape(date_label)}</td></tr>'
            f'<tr><td colspan="2" style="padding-top:10px;{_F}font-size:13px;color:{_ON_BLACK};'
            f'line-height:18px;{_LH}">{" &middot; ".join(shape)}</td></tr></table></td></tr>')

def _cover_summary(summary, weekly=False) -> str:
    if not summary:
        return ""
    rows = ""
    for n, s in enumerate(summary):
        pad = "8px 22px 20px 22px" if n == len(summary) - 1 else "8px 22px 8px 22px"
        rows += (f'<tr><td style="padding:{pad};"><table {_T}><tr>'
                 f'<td width="22" valign="top" style="{_F}font-size:15px;font-weight:bold;'
                 f'color:{_P["orange"]};line-height:22px;{_LH}">&#9632;</td>'
                 f'<td valign="top" style="{_F}font-size:15px;color:{_P["ink"]};line-height:22px;{_LH}">'
                 f'<b>{escape(s["lead"])}</b> {escape(s["text"])}</td></tr></table></td></tr>')
    return (f'<tr><td style="padding:24px 0 0 0;"><table {_T} style="background:{_P["white"]};'
            f'border:1px solid {_P["rule"]};"><tr><td style="padding:20px 22px 8px 22px;{_F}'
            f'font-size:12px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;'
            f'color:{_P["black"]};">The {"week" if weekly else "day"} in 30 seconds</td></tr>'
            f'{rows}</table></td></tr>')

def _cover_badge(tier) -> str:
    base = (f"{_F}font-size:10px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;"
            "border-radius:2px;")
    if tier == "first":
        return (f'<span style="background:{_P["orange"]};color:{_P["black"]};{base}padding:2px 6px;">'
                f'{LABELS["first"]}</span> ')
    if tier == "today":
        return (f'<span style="color:{_P["cobalt"]};border:1px solid {_P["cobalt"]};{base}'
                f'padding:1px 6px;">{LABELS["today"]}</span> ')
    return ""

def feedback_address(value) -> str:
    """Where the cover's "Useful / Not for us" links send a vote: `sender`
    means the sending address (`from_address`), else a plain email address."""
    value = (value or "").strip()
    if value.lower() == "sender":
        value = from_address()
    return value if re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+", value) else ""

def _feedback(item, to) -> str:
    """Two mailto: links under a reading-order story. Each opens a ready-made
    email whose subject names the vote and the story, for tuning the priority
    profile. Nothing is tracked; a reply is the whole mechanism."""
    if not to:
        return ""
    def link(label, verdict):
        subject = quote(f"{verdict}: {display_title(item)}"[:150])
        body = quote(f"{display_title(item)}\n{_safe_url(item.url)}")
        href = f"mailto:{to}?subject={subject}&body={body}"
        return (f'<a href="{escape(href, quote=True)}" style="color:{_P["cobalt"]};'
                f'text-decoration:underline;">{label}</a>')
    return (f'<div style="{_F}font-size:12px;color:{_P["muted"]};line-height:18px;{_LH}'
            f'padding-top:8px;">Worth it? {link("Useful", "Useful")} &middot; '
            f'{link("Not for us", "Not for us")}</div>')

def _order_row(n, item, org, feedback_to="") -> str:
    tier = item.extra.get("priority")
    weekly_pick = bool(item.extra.get("weekly_pick"))
    href = _href(item.url)
    num_color = _P["cobalt"] if tier == "today" else _P["orange"]
    big = n < 2
    title = escape(display_title(item))
    img = _image_url(item) if n == 0 else ""
    pic = (f'<tr><td colspan="2" style="padding:0 0 14px 0;"><a href="{href}">'
           f'<img src="{escape(img, quote=True)}" width="556" alt="{escape(display_title(item), quote=True)}" '
           f'style="display:block;width:100%;max-width:556px;height:auto;border:0;"></a></td></tr>'
           if img else "")
    why = item.extra.get("why")
    why_html = (f'<div style="{_F}font-size:14px;color:{_P["ink"]};line-height:20px;{_LH}'
                f'padding-top:6px;"><b style="color:{_P["cobalt"]};">'
                f'{escape(f"For {org}:" if org else "Why it matters:")}</b> {escape(why)}</div>'
                if why else "")
    also = item.extra.get("also") or []
    also_html = (f'<div style="{_F}font-size:13px;color:{_P["muted"]};line-height:19px;{_LH}'
                 f'padding-top:8px;">Also covered by ' + " &middot; ".join(
                     f'<a href="{_href(a.url)}" style="color:{_P["cobalt"]};text-decoration:underline;">'
                     f'{escape(a.source)}</a>' for a in also) + "</div>" if also else "")
    return (f'<tr><td style="padding:18px 0;border-bottom:1px solid {_P["rule"]};"><table {_T}>{pic}<tr>'
            f'<td width="44" valign="top" style="{_F}font-size:30px;font-weight:bold;color:{num_color};'
            f'line-height:30px;{_LH}">{n + 1}</td><td valign="top">'
            f'<div style="padding-bottom:6px;">{"" if weekly_pick else _cover_badge(tier)}'
            f'<span style="{_F}font-size:11px;'
            f'letter-spacing:.8px;text-transform:uppercase;color:{_P["muted"]};">'
            f'{"&nbsp;" if tier in ("first", "today") and not weekly_pick else ""}'
            f'{escape(item.source)} &middot; '
            + (f'{escape(item.extra["day_label"])} &middot; ' if item.extra.get("day_label") else "")
            + f'{read_minutes(item)} min</span></div>'
            f'<a href="{href}" style="{_F}font-size:{19 if big else 17}px;font-weight:bold;'
            f'color:{_P["ink"]};text-decoration:none;line-height:{25 if big else 23}px;{_LH}">{title}</a>'
            f'{why_html}{also_html}{_feedback(item, feedback_to)}</td></tr></table></td></tr>')

def _cover_skim(skim, edition_url) -> str:
    link = _safe_url(edition_url).split("#")[0]
    out = ""
    for n, (theme, items) in enumerate(skim):
        name = theme.get("tab") or theme["name"]
        # Three headlines per section when the web edition holds the rest.
        shown = items[:SKIM_MAX] if link else items
        out += (f'<tr><td style="padding:16px 0 4px 0;{_F}font-size:11px;font-weight:bold;'
                f'letter-spacing:1px;text-transform:uppercase;color:{_P["cobalt"]};">{escape(name)} '
                f'<span style="color:{_P["muted"]};font-weight:normal;">&middot; {len(items)}</span>'
                f'</td></tr>')
        out += "".join(
            f'<tr><td style="padding:6px 0;{_F}font-size:14px;line-height:20px;{_LH}">'
            f'<a href="{_href(i.url)}" style="color:{_P["ink"]};text-decoration:none;">{escape(i.title)}</a> '
            f'<span style="color:{_P["muted"]};font-size:12px;">{_followup(i)}{escape(i.source)}</span></td></tr>'
            for i in shown)
        if len(items) > len(shown):
            out += (f'<tr><td style="padding:2px 0 4px 0;{_F}font-size:13px;">'
                    f'<a href="{escape(f"{link}#skim-{n}", quote=True)}" style="color:{_P["cobalt"]};'
                    f'text-decoration:underline;">{len(items) - len(shown)} more in {escape(name)} '
                    f'&rarr;</a></td></tr>')
    return out

def _followup(item) -> str:
    """"Follow-up · " before the source of a story that only updates one from
    an earlier reading order (priority.py)."""
    return "Follow-up &middot; " if item.extra.get("followup") else ""

def _cover_footer(title, n_sources, org, link, unsubscribe, address) -> str:
    line = f"{escape(title)} is curated by Claude from {_plural(n_sources, 'source', 'sources')}"
    line += f" for the team at {escape(org)}." if org else "."
    a = f'style="color:{_P["cobalt"]};"'
    links = []
    if link:
        links.append(f'<a href="{escape(link, quote=True)}" {a}>Read on the web</a>')
        links.append(f'<a href="{escape(_archive_url(link), quote=True)}" {a}>Search the archive</a>')
    unsub = unsubscribe_link(unsubscribe)
    if unsub:
        links.append(f'<a href="{escape(unsub, quote=True)}" {a}>Unsubscribe</a>')
    lines = [line] + ([" &middot; ".join(links)] if links else []) + (
        [escape(address)] if address else [])
    return (f'<tr><td style="padding:16px 0 0 0;{_F}font-size:12px;color:{_P["muted"]};'
            f'line-height:19px;{_LH}">{"<br>".join(lines)}</td></tr>')

def _cover_email(title, themes, *, greeting, edition_url, preheader, summary, org, now,
                 unsubscribe, address, feedback="", weekly=False) -> str:
    order, skim = triage(themes)
    n_skim = sum(len(its) for _, its in skim)
    n_sources = len({i.source for i in all_items(themes)})
    date_label = now.strftime("%A, %d %b").replace(" 0", " ")
    link = _safe_url(edition_url)
    body = _cover_summary(summary, weekly)
    if greeting:
        body += (f'<tr><td style="padding:20px 0 0 0;{_F}font-size:14px;font-style:italic;'
                 f'color:{_P["ink"]};line-height:21px;{_LH}">{escape(greeting)}</td></tr>')
    if order:
        minutes = sum(read_minutes(i) for i in order)
        body += _section_label(f"The week in {len(order)}" if weekly else "Your reading order",
                               f'{_plural(len(order), "story", "stories")} &middot; ~{minutes} min')
        to = feedback_address(feedback)
        body += "".join(_order_row(n, i, org, to) for n, i in enumerate(order))
    if skim:
        body += _section_label("Skim if you have time", _plural(n_skim, "headline", "headlines"))
        body += _cover_skim(skim, link)
    if link:
        body += (f'<tr><td style="padding:28px 0 8px 0;"><table {_T}><tr><td align="center" '
                 f'bgcolor="{_P["orange"]}" style="background:{_P["orange"]};border-radius:4px;">'
                 f'<a href="{escape(link, quote=True)}" style="display:block;padding:14px 18px;{_F}'
                 f'font-size:15px;font-weight:bold;color:{_P["black"]};text-decoration:none;">'
                 f'Open the full edition &rarr;</a></td></tr></table></td></tr>'
                 f'<tr><td style="padding:4px 0 8px 0;"><table {_T}><tr><td align="center" '
                 f'bgcolor="{_P["white"]}" style="background:{_P["white"]};border:2px solid {_P["black"]};'
                 f'border-radius:4px;"><a href="{escape(_archive_url(link), quote=True)}" '
                 f'style="display:block;padding:12px 18px;{_F}font-size:15px;font-weight:bold;'
                 f'color:{_P["black"]};text-decoration:none;">Search past editions in the Archive &rarr;'
                 f'</a></td></tr></table></td></tr>')
    body += _cover_footer(title, n_sources, org, link, unsubscribe, address)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'{_LIGHT_ONLY}'
        f'<title>{escape(title)}</title>'
        '<!--[if mso]><style>table,td{font-family:Arial,Helvetica,sans-serif!important}</style><![endif]-->'
        '<style>:root{color-scheme:light only;supported-color-schemes:light only}'
        '@media (max-width:620px){.px{padding-left:16px!important;padding-right:16px!important}}</style>'
        f'</head><body style="margin:0;padding:0;background:{_P["paper"]};">{_preheader(preheader)}'
        f'<table {_T} bgcolor="{_P["paper"]}" style="background:{_P["paper"]};"><tr>'
        '<td align="center" style="padding:24px 12px;">'
        '<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->'
        f'<table {_T} style="max-width:600px;">'
        f'{_cover_masthead(title, date_label, order, n_skim, n_sources, link)}'
        f'<tr><td class="px" style="padding:0 22px 28px 22px;background:{_P["paper"]};">'
        f'<table {_T}>{body}</table></td></tr></table>'
        '<!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>')

def _trim(text, limit) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:-–—")

def cover_preheader(themes, greeting="", summary=None) -> str:
    """Inbox preview line for a cover email: the first takeaway, then the
    day's shape, e.g. "Price war: Opus 5.5 and GPT-6 cut prices 40–50%. 2 to
    read first, 2 today (~15 min), 18 to skim." """
    order, skim = triage(themes)
    firsts = sum(1 for i in order if i.extra.get("priority") == "first")
    todays = sum(1 for i in order if i.extra.get("priority") == "today")
    if not firsts and not todays and not summary:
        items = [i for t in themes for i in t["items"]]
        return greeting or (items[0].title if items else "")
    n_skim = sum(len(its) for _, its in skim)
    minutes = sum(read_minutes(i) for i in order)
    if any(t.get("pinned") for t in themes):  # the Friday Week in 5
        shape = f"The week in {len(order)} (~{minutes} min), {n_skim} to skim."
    elif firsts or todays:
        shape = f"{firsts} to read first, {todays} today (~{minutes} min), {n_skim} to skim."
    else:
        shape = f"{len(order)} to read (~{minutes} min), {n_skim} to skim."
    if not summary:
        return shape
    lead = summary[0]["lead"].rstrip(".!?") + ":"
    room = max(PREHEADER_MAX - len(shape) - len(lead) - 3, 0)
    point = " ".join((summary[0].get("short") or summary[0]["text"]).split()).rstrip(".!?")
    if len(point) > room:
        point = _trim(point, room - 1).rstrip(".!?") + "…"
        return f"{lead} {point} {shape}" if point != "…" else shape
    return f"{lead} {point}. {shape}" if point else shape

def _preheader(text) -> str:
    """Hidden inbox-preview line (the grey snippet after the subject). Padded
    with zero-width spaces so clients don't pull body text in after it."""
    if not text:
        return ""
    pad = "&#8203;&nbsp;" * 60
    return ('<div style="display:none;max-height:0;overflow:hidden;opacity:0;'
            f'mso-hide:all">{escape(text[:PREHEADER_MAX])}{pad}</div>')

def build_html_email(title, themes, *, greeting="", edition_url="", cover=False,
                     preheader="", summary=None, org="", now=None, unsubscribe="",
                     address="", feedback="", weekly=False) -> str:
    """The email. `cover=True` builds the short triage cover (see above);
    `summary` (summary.py), `org` (priority.org, for "For <org>:"), the
    footer's `unsubscribe` link and postal `address`, and `feedback` (where
    "Useful / Not for us" votes go) apply to the cover only. `weekly` titles
    the cover as the Friday Week in 5 (weekly.py)."""
    now = now or datetime.now(timezone.utc)
    if cover:
        return _cover_email(title, themes, greeting=greeting, edition_url=edition_url,
                            preheader=preheader, summary=summary or [], org=org, now=now,
                            unsubscribe=unsubscribe, address=address, feedback=feedback,
                            weekly=weekly)
    greet_html = f'<div class="greeting">{escape(greeting)}</div>' if greeting else ""
    body = ""
    for theme in themes:
        cards = "".join(_card(i) for i in theme["items"])
        body += (f'<p class="theme-title">{escape(theme.get("emoji", ""))} '
                 f'{escape(theme["name"])}</p>{cards}')
    header = (f'<div class="header"><h1>{escape(title)}</h1>'
              f'<div class="date">{now.strftime("%A, %B %d")}</div></div>')
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">{_LIGHT_ONLY}'
            f'<style>:root{{color-scheme:light only}}{_CSS}</style></head><body>{_preheader(preheader)}<div class="wrapper">'
            f'{header}{greet_html}{_reading_list(themes)}{body}'
            f'<div class="footer">Curated by Claude</div></div></body></html>')

def _recipients() -> list:
    """Recipients from EMAIL_RECIPIENT / EMAIL_RECIPIENTS / RECIPIENTS
    (whichever is set), comma-separated. Supports multiple readers."""
    raw = (os.environ.get("EMAIL_RECIPIENT")
           or os.environ.get("EMAIL_RECIPIENTS")
           or os.environ.get("RECIPIENTS", ""))
    return [a.strip() for a in raw.split(",") if a.strip()]

def top_pick_subject(title, themes, limit=60) -> str:
    """`Title | <lead headline>`, trimmed at a word boundary. The lead is the
    first "Read first" item when priority labels are on, else the first item.
    Falls back to the plain title when there are no items."""
    must = reading_list(themes)
    first = must[0] if must else next((t["items"][0] for t in themes if t.get("items")), None)
    if not first or not display_title(first).strip():
        return title
    lead = " ".join(display_title(first).split())
    if len(lead) > limit:
        lead = lead[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return f"{title} | {lead}"

def _smtp_settings() -> tuple:
    """(sender, password, host, port) from the environment. A secret that isn't
    set arrives from the workflow as "", not as missing."""
    sender = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 587)
    return sender, password, host, port


def _login(server, sender, password) -> None:
    try:
        server.login(sender, password)
    except smtplib.SMTPAuthenticationError as e:
        hint = ""
        if b"Application-specific password" in e.smtp_error or e.smtp_code == 534:
            hint = (" Gmail needs a 16-character App Password in EMAIL_PASSWORD, not the "
                    "account password: https://myaccount.google.com/apppasswords")
        raise RuntimeError(f"SMTP login failed for {sender}: {e.smtp_code} "
                           f"{e.smtp_error.decode(errors='replace')}.{hint}") from e


def check_login() -> bool:
    """Log in to the mail server and disconnect, so a bad password fails the
    run before any fetching or Claude spend. Skipped (returns False) when
    the email settings aren't configured at all."""
    if not os.environ.get("EMAIL_SENDER") or not os.environ.get("EMAIL_PASSWORD"):
        return False
    sender, password, host, port = _smtp_settings()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo(); server.starttls(); _login(server, sender, password)
    print(f"[email] login ok as {sender} via {host}:{port}", flush=True)
    return True


def send_email(title, html, subject=None, from_name="") -> None:
    """`subject` overrides the default "<title> - <date>" subject line.
    `from_name` is the sender name the inbox shows (e.g. "The Edge");
    blank shows the mailbox's own account name. The From: address is
    `from_address()` (EMAIL_FROM, else the login account)."""
    sender, password, host, port = _smtp_settings()
    sender_addr = from_address()
    recipients = _recipients()
    if not recipients:
        raise KeyError("EMAIL_RECIPIENT")
    subject = subject or f"{title} - {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
    # One message per reader, each addressed only to them, so a multi-reader
    # list never exposes everyone's address in a shared To: header.
    with smtplib.SMTP(host, port) as server:
        server.ehlo(); server.starttls(); _login(server, sender, password)
        for rcpt in recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr((from_name, sender_addr)) if from_name else sender_addr
            msg["To"] = rcpt
            msg.attach(MIMEText(html, "html", "utf-8"))
            server.sendmail(sender_addr, [rcpt], msg.as_string())
    print(f"[email] sent to {len(recipients)} recipient(s)", flush=True)
