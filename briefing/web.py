"""Web edition — the browsable version of the day's briefing, plus the Archive.

Layout (desktop first, works on a phone), built for triage:

* a sticky triage bar: jump links to Summary / Read first / Read today / Skim
  and a "2 of 4 read" progress bar;
* "The day in 30 seconds" (summary.py) beside a time budget (5 min, 15 min,
  +10 min), only when a summary exists;
* one numbered reading order: Read first, then Read today, in Claude's rank
  order, each with a read time, the why line, other sources for a cluster, a
  "Mark as read" toggle and (Read first by default) a picture;
* "Explain it simply" (explain.py): one concept from the day in a few emoji
  steps, only when an explainer exists;
* everything else as a skim list per section; tap a headline for its gist.

Without JavaScript the page still reads top to bottom: every gist is open
and every jump link is a plain anchor; the script only adds the read state
(kept in this browser's localStorage), the gist toggles and smooth scrolling.

Each edition embeds its stories as JSON in `<script id="edition-data">`, so
`build_archive_index` can rebuild the Archive from the saved editions alone:
every story ever sent, searchable, filterable by priority and source, grouped
by week, keeping the label it got on the day.

Three entry points, all filesystem-only (no network, no API keys):

* `build_web_edition(title, themes, ...)` -> HTML string
* `save_edition(out_dir, html, date_str, slot_key)` -> writes index.html and
  editions/<date>-<slot>.html
* `build_archive_index(out_dir, site_title)` -> (re)writes archive.html

Publish by pointing GitHub Pages at `out_dir` (default `docs/`).
"""
from __future__ import annotations
import os
import glob
import json
import re
from datetime import datetime, timezone
from html import escape
from briefing.theme import css
from briefing.priority import LABELS, TIERS, triage, all_items, read_minutes, display_title
from briefing.summary import ref_target

_EDITION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.html$")
_DATA_RE = re.compile(r'<script id="edition-data" type="application/json">(.*?)</script>', re.S)
_SUMMARY_RE = re.compile(r'<script id="edition-summary" type="application/json">(.*?)</script>', re.S)
OTHER_TOPIC = "Other"  # archive label for stories without a topic

TAB_MAX = 20  # characters; long section names overflow the tab bar

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@'
         '62..125,400..900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@'
         '0,400;0,500;0,600;0,700;1,400&display=swap">')

# Shared by the edition and the archive: palette, type, badges, cards.
_BASE_CSS = css(
    "*{box-sizing:border-box;min-width:0}"
    "[hidden]{display:none!important}"
    "html{overflow-x:clip}"
    "body{margin:0;background:$white;color:$ink;"
    "font:15px/1.55 'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif}"
    "a{color:inherit}"
    ":focus-visible{outline:2px solid $orange;outline-offset:2px}"
    "img{max-width:100%}"
    ".mono{font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace}"
    ".mast{background:$black;color:$white;border-bottom:5px solid $orange;padding:18px 40px;"
    "display:flex;justify-content:space-between;align-items:center;gap:12px 24px;flex-wrap:wrap}"
    ".word{font:900 30px/1 Archivo,'Arial Narrow',Arial,sans-serif;font-stretch:125%;"
    "letter-spacing:.03em;color:$white;text-decoration:none}"
    ".nav{display:flex;gap:18px;font:500 12px 'IBM Plex Mono',monospace;letter-spacing:.08em;"
    "text-transform:uppercase}"
    ".nav a{color:#BDBDBD;text-decoration:none}.nav a.on{color:$orange}"
    ".wrap{max-width:1180px;margin:0 auto;padding:0 40px}"
    ".dateline{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 16px;"
    "font:500 12px 'IBM Plex Mono',monospace;letter-spacing:.08em;text-transform:uppercase;"
    "color:$muted;padding:22px 0 0}"
    ".dateline b{color:$ink;font-weight:500}"
    ".greeting{font-style:italic;background:$orange_tint;border-left:4px solid $cobalt;"
    "border-radius:0 8px 8px 0;padding:14px 18px;margin:20px 0 0}"
    ".h{display:flex;align-items:center;gap:12px;font:800 12.5px Archivo,Arial,sans-serif;"
    "font-stretch:112%;letter-spacing:.16em;text-transform:uppercase;margin:0 0 14px}"
    ".h::after{content:'';flex:1;height:2px;background:$black}"
    ".h span{font:500 11px 'IBM Plex Mono',monospace;letter-spacing:.06em;color:$muted}"
    ".meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;"
    "font:500 11px 'IBM Plex Mono',monospace;letter-spacing:.05em;text-transform:uppercase;"
    "color:$cobalt}"
    ".meta time{color:$muted}"
    ".badge{display:inline-block;font:700 10px/1.6 'IBM Plex Sans',Arial,sans-serif;"
    "letter-spacing:.08em;text-transform:uppercase;padding:1px 7px;border-radius:2px;"
    "white-space:nowrap}"
    ".badge-first{background:$orange;color:$black}"
    ".badge-today{color:$cobalt;box-shadow:inset 0 0 0 1px $cobalt;background:$white}"
    ".badge-later{background:$paper;color:$muted}"
    "a.t{color:$ink;text-decoration:none}a.t:hover{color:$cobalt;text-decoration:underline}"
    ".why{font-size:13.5px;line-height:1.4}.why b{color:$cobalt;font-weight:600}"
    ".preview{color:$muted;font-size:13.5px;line-height:1.5;margin:0;"
    "display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}"
    ".dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px}"
    ".dot.first{background:$orange}.dot.today{background:$cobalt}"
    ".chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}"
    ".chips .lbl{font:500 11px 'IBM Plex Mono',monospace;letter-spacing:.08em;"
    "text-transform:uppercase;color:$muted;margin-right:4px}"
    ".chip{appearance:none;cursor:pointer;font:500 12.5px 'IBM Plex Sans',sans-serif;"
    "padding:5px 11px;border-radius:999px;border:1px solid $rule;background:$white;color:$ink}"
    ".chip em{font:400 11px 'IBM Plex Mono',monospace;font-style:normal;color:$muted;margin-left:4px}"
    ".chip[aria-pressed=true]{background:$black;border-color:$black;color:$white}"
    ".chip[aria-pressed=true] em{color:#BDBDBD}"
    "footer{background:$black;color:#BDBDBD;padding:20px 40px;margin-top:40px;"
    "font:12px 'IBM Plex Mono',monospace;letter-spacing:.04em;display:flex;flex-wrap:wrap;"
    "justify-content:space-between;gap:8px}"
    "footer a{color:$orange}"
    "@media (max-width:640px){.wrap{padding:0 16px}.mast{padding:14px 16px}"
    ".word{font-size:24px}footer{padding:18px 16px}}"
    "@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}"
)

_EDITION_CSS = css(
    "#summary,#order,#explain,#skim,.item,.skim-col{scroll-margin-top:64px}"
    # Sticky triage bar: jump links on the left, reading progress on the right.
    ".tbar{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.95);"
    "-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);border-bottom:1px solid $rule}"
    ".tbar-in{max-width:1180px;margin:0 auto;padding:0 40px;display:flex;align-items:center;"
    "justify-content:space-between;gap:0 24px;flex-wrap:wrap}"
    ".tjump{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}"
    ".tjump::-webkit-scrollbar{display:none}"
    ".tj{flex:none;white-space:nowrap;padding:15px 11px 13px;font:700 11.5px 'IBM Plex Sans',sans-serif;"
    "letter-spacing:.06em;text-transform:uppercase;color:$ink;text-decoration:none}"
    ".tj:hover{color:$cobalt}"
    ".tj .ix{font:500 12px 'IBM Plex Mono',monospace;color:$orange;margin-right:7px;letter-spacing:0}"
    ".tj .n{font:500 11px 'IBM Plex Mono',monospace;color:$muted;margin-left:6px;letter-spacing:0}"
    ".tright{display:flex;align-items:center;flex-wrap:wrap;gap:10px 18px;padding:8px 0}"
    ".abtn{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;padding:6px 12px;"
    "border:2px solid $black;border-radius:4px;font:700 11.5px 'IBM Plex Sans',sans-serif;"
    "letter-spacing:.06em;text-transform:uppercase;color:$black;text-decoration:none}"
    ".abtn:hover{background:$black;color:$white}"
    ".prog{display:flex;align-items:center;gap:10px;font:500 12px 'IBM Plex Mono',monospace;"
    "color:$muted}"
    ".prog b{color:$ink;font-weight:500}"
    ".track{display:block;width:96px;height:6px;background:$paper;border-radius:3px;overflow:hidden}"
    ".fill{display:block;height:100%;width:0;background:$orange;transition:width .25s ease}"
    # The day in 30 seconds + time budget.
    ".sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));"
    "gap:28px 40px;padding:26px 0 36px;align-items:start}"
    ".sum-main{grid-column:span 2;min-width:min(100%,340px)}"
    ".sum .h{margin:0 0 18px}"
    ".takeaways{list-style:none;margin:0;padding:0;display:grid;gap:18px}"
    ".takeaways li{display:grid;grid-template-columns:34px minmax(0,1fr);gap:6px}"
    ".takeaways .ix{font:500 13px/2.1 'IBM Plex Mono',monospace;color:$orange}"
    ".takeaways p{font:500 22px/1.32 Archivo,Arial,sans-serif;margin:0;text-wrap:pretty;"
    "letter-spacing:-.005em}"
    ".takeaways p b{font-weight:800}"
    ".jump{display:inline-block;white-space:nowrap;padding:6px 0 0;font:500 11.5px 'IBM Plex Mono',monospace;"
    "letter-spacing:.06em;text-transform:uppercase;color:$cobalt;text-decoration:none}"
    ".jump:hover{text-decoration:underline}"
    ".budget{border:2px solid $black;border-radius:4px;padding:18px 20px 12px}"
    ".budget .bt{font:800 12.5px Archivo,Arial,sans-serif;font-stretch:112%;letter-spacing:.16em;"
    "text-transform:uppercase;margin:0 0 6px}"
    ".brow{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;align-items:baseline;"
    "border-top:1px solid $rule;padding:12px 0;color:$ink;text-decoration:none}"
    ".brow:hover{color:$cobalt}"
    ".brow .time{font:500 16px 'IBM Plex Mono',monospace;color:$orange}"
    ".brow .what{font:600 14.5px/1.4 'IBM Plex Sans',sans-serif}"
    ".brow .what span{display:block;font-weight:400;font-size:13px;color:$muted}"
    # Reading order.
    ".order{padding:0 0 40px}.order .h{margin:0 0 4px}"
    ".sum+.order{padding-top:0}.dateline+.order,.greeting+.order{padding-top:26px}"
    ".item{display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:4px 20px;padding:22px 0;"
    "border-bottom:1px solid $rule;transition:opacity .2s ease}"
    ".item.read{opacity:.5}"
    ".num{font:900 40px/1 Archivo,Arial,sans-serif;font-stretch:112%;color:$orange;padding-top:2px}"
    ".item.today .num{color:$cobalt}.item.read .num{color:$muted}"
    ".item-body{display:grid;gap:9px;align-content:start;max-width:720px}"
    ".meta .quiet{color:$muted;white-space:nowrap}"
    ".h span{white-space:nowrap}"
    ".item h3{font:700 25px/1.18 Archivo,Arial,sans-serif;margin:0;text-wrap:balance}"
    ".whybox{background:$orange_tint;padding:9px 12px;border-radius:2px;font-size:14.5px;line-height:1.45}"
    ".whybox b{display:block;font:500 10.5px 'IBM Plex Mono',monospace;letter-spacing:.08em;"
    "text-transform:uppercase;color:#8A3207;margin-bottom:2px}"
    ".gist{color:$muted;font-size:14px;line-height:1.5;margin:0}"
    ".also{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13.5px;color:$muted}"
    ".also a{color:$cobalt}"
    ".acts{display:flex;gap:10px;align-items:center;padding-top:4px}"
    ".mark{appearance:none;cursor:pointer;white-space:nowrap;font:500 12.5px 'IBM Plex Sans',sans-serif;"
    "padding:5px 12px;border-radius:999px;border:1px solid $rule;background:$white;color:$ink}"
    ".mark[aria-pressed=true]{background:$black;border-color:$black;color:$white}"
    ".open-link{font:500 12.5px 'IBM Plex Sans',sans-serif;color:$cobalt}"
    ".item-pic{display:block;width:260px}"
    ".item-pic img{display:block;width:260px;aspect-ratio:16/9;object-fit:cover;border-radius:4px;"
    "border:1px solid $rule}"
    # Skim.
    # Explain it simply: one concept as a row of emoji steps (stacked on phones).
    ".explain{padding:0 0 44px}.explain .h{margin:0 0 16px}"
    ".steps{list-style:none;margin:0;padding:0;display:grid;"
    "grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:12px}"
    ".steps li{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;"
    "align-items:center;border:2px solid $black;border-radius:4px;padding:14px 16px;"
    "font:600 15px/1.35 'IBM Plex Sans',sans-serif}"
    ".steps .ic{font-size:28px;line-height:1}"
    ".steps .sn{display:block;font:500 11px 'IBM Plex Mono',monospace;color:$orange;letter-spacing:.06em}"
    ".explain .why-line{margin:14px 0 0;font-size:15px;line-height:1.5;color:$ink}"
    ".explain .why-line b{color:$cobalt;font-weight:600}"
    ".explain .jump{padding:4px 0 0}"
    ".skim{padding:0 0 48px}.skim .h{margin:0 0 6px}"
    ".skim-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));"
    "gap:8px 36px;align-items:start}"
    ".skim-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;"
    "padding:16px 0 8px;border-bottom:2px solid $black}"
    ".skim-head h3{flex:1 0 auto;font:800 19px/1.2 Archivo,Arial,sans-serif;margin:0}"
    ".skim-head span{flex:none;font:12px 'IBM Plex Mono',monospace;color:$muted;white-space:nowrap}"
    ".srow{border-bottom:1px solid $rule}"
    ".stog{appearance:none;width:100%;text-align:left;background:none;border:0;cursor:pointer;"
    "padding:10px 0;display:grid;grid-template-columns:minmax(0,1fr) 16px;gap:10px;align-items:start;"
    "color:$ink;font:inherit}"
    ".stog:hover{color:$cobalt}"
    ".stog b{display:block;font:600 14.5px/1.3 Archivo,Arial,sans-serif}"
    ".stog .src{font:11px 'IBM Plex Mono',monospace;color:$muted}"
    ".stog .sign{font:500 14px/1.3 'IBM Plex Mono',monospace;color:$muted}"
    ".sgist{padding:0 26px 12px 0;font-size:13.5px;line-height:1.5;color:#333333;display:grid;gap:6px}"
    ".sgist a{color:$cobalt;font-weight:500;justify-self:start}"
    # Archive call-to-action after Skim.
    ".acta{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px 24px;align-items:center;"
    "margin:0 0 48px;padding:22px 24px;border:2px solid $black;border-radius:4px;"
    "text-decoration:none;color:$ink}"
    ".acta:hover{background:$orange_tint}"
    ".acta .k{display:block;font:800 12.5px Archivo,Arial,sans-serif;font-stretch:112%;"
    "letter-spacing:.16em;text-transform:uppercase;margin-bottom:6px}"
    ".acta .l{font:500 20px/1.3 Archivo,Arial,sans-serif}"
    ".acta .b{background:$orange;color:$black;font:700 15px 'IBM Plex Sans',sans-serif;"
    "padding:12px 18px;border-radius:4px;white-space:nowrap}"
    "@media (max-width:900px){.item{grid-template-columns:64px minmax(0,1fr)}"
    ".item-pic{grid-column:2;width:100%}.item-pic img{width:100%}}"
    "@media (max-width:760px){.sum-main{grid-column:auto}}"
    "@media (max-width:640px){.h{flex-wrap:wrap;row-gap:4px}.tbar-in{padding:0 16px}.tjump{margin-left:-11px}"
    ".item{grid-template-columns:44px minmax(0,1fr);gap:4px 12px}.num{font-size:30px}"
    ".item h3{font-size:21px}.takeaways p{font-size:19px}.acta{grid-template-columns:minmax(0,1fr)}"
    ".acta .b{justify-self:start}.takeaways li{grid-template-columns:28px minmax(0,1fr)}}"
)

# Progressive enhancement only: without it every section is open and every
# jump link is a plain anchor. Read state lives in this browser (localStorage).
_EDITION_JS = r"""
(function(){
  var order=document.getElementById('order'), key=order&&order.getAttribute('data-key');
  var read={};
  try{read=JSON.parse(localStorage.getItem(key)||'{}')||{};}catch(e){}
  function save(){try{localStorage.setItem(key,JSON.stringify(read));}catch(e){}}
  var items=[].slice.call(document.querySelectorAll('.item'));
  var done=document.getElementById('done'), fill=document.getElementById('fill');
  function paint(){
    var n=0;
    items.forEach(function(el){
      var r=!!read[el.getAttribute('data-n')]; if(r) n++;
      el.classList.toggle('read',r);
      var num=el.querySelector('.num'); num.textContent=r?'\u2713':num.getAttribute('data-num');
      var b=el.querySelector('.mark'); b.setAttribute('aria-pressed',String(r));
      b.textContent=r?'Read \u2713':'Mark as read';
    });
    if(done) done.textContent=n;
    if(fill) fill.style.width=(items.length?n/items.length*100:0)+'%';
  }
  items.forEach(function(el){
    var b=el.querySelector('.mark'); b.hidden=false;
    b.addEventListener('click',function(){
      var i=el.getAttribute('data-n'); if(read[i]) delete read[i]; else read[i]=true;
      save(); paint();
    });
  });
  var prog=document.querySelector('.prog'); if(prog) prog.hidden=false;
  paint();
  var skim=document.getElementById('skim'), openAll=skim&&skim.getAttribute('data-expanded')==='true';
  [].slice.call(document.querySelectorAll('.stog')).forEach(function(b){
    var g=document.getElementById(b.getAttribute('aria-controls'));
    function set(open){b.setAttribute('aria-expanded',String(open)); if(g) g.hidden=!open;
      b.querySelector('.sign').textContent=open?'\u2212':'+';}
    set(openAll);
    b.addEventListener('click',function(){set(b.getAttribute('aria-expanded')!=='true');});
  });
  var still=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
  [].slice.call(document.querySelectorAll('a.go')).forEach(function(a){
    a.addEventListener('click',function(e){
      var id=a.getAttribute('href').slice(1), el=document.getElementById(id); if(!el) return;
      e.preventDefault();
      window.scrollTo({top:el.getBoundingClientRect().top+window.scrollY-64,behavior:still?'auto':'smooth'});
      try{history.replaceState(null,'','#'+id);}catch(x){}
    });
  });
})();
"""

_NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                 "nine", "ten")
READING_IMAGES = ("first", "all", "none")


def _safe_url(url) -> str:
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def _image(item) -> str:
    return _safe_url(item.extra.get("image") or item.extra.get("thumbnail", ""))


def tab_label(name, limit=TAB_MAX) -> str:
    """A short label for a section when Claude didn't supply one: whole
    words up to `limit` characters, then an ellipsis."""
    name = " ".join((name or "").split())
    if len(name) <= limit:
        return name
    cut = name[:limit].rsplit(" ", 1)[0].rstrip(",;:&-") or name[:limit]
    return cut + "…"


def _json_for_html(data) -> str:
    """JSON safe to embed in a <script> block."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # `<` as \u003c keeps "</script" and "<!--" out of the script block.
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _badge(item) -> str:
    if item.extra.get("weekly_pick"):
        return ""
    tier = item.extra.get("priority")
    return (f'<span class="badge badge-{tier}">{escape(LABELS[tier])}</span>'
            if tier in LABELS else "")


def _words(n) -> str:
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else str(n)


def _plural(n, one, many) -> str:
    return f"{n} {one if n == 1 else many}"


def _story_range(first, last) -> str:
    """"story 1", "stories 1 and 2", "stories 1–3"."""
    if first == last:
        return f"story {first}"
    if last == first + 1:
        return f"stories {first} and {last}"
    return f"stories {first}–{last}"


def _section_of(themes) -> dict:
    return {id(i): (t.get("tab") or tab_label(t["name"])) for t in themes for i in t["items"]}


def _triage_bar(summary, order, n_skim, weekly=False, explainer=None) -> str:
    firsts = [n for n, i in enumerate(order) if i.extra.get("priority") == "first"]
    todays = [n for n, i in enumerate(order) if i.extra.get("priority") == "today"]
    links = []
    if summary:
        links.append(("Summary", "", "summary"))
    if weekly and order:
        links.append(("Week in 5" if len(order) == 5 else "The week", str(len(order)), "order"))
    elif firsts:
        links.append(("Read first", str(len(firsts)), f"order-{firsts[0]}"))
    if todays:
        links.append(("Read today", str(len(todays)), f"order-{todays[0]}"))
    if order and not firsts and not todays and not weekly:
        links.append(("Reading order", str(len(order)), "order"))
    if explainer:
        links.append(("Explain", "", "explain"))
    if n_skim:
        links.append(("Skim", str(n_skim), "skim"))
    tabs = "".join(
        f'<a class="tj go" href="#{target}"><span class="ix">{n:02d}</span>{label}'
        + (f'<span class="n">{count}</span>' if count else "") + "</a>"
        for n, (label, count, target) in enumerate(links, 1))
    prog = (f'<div class="prog" hidden><span><b id="done">0</b> of {len(order)} read</span>'
            f'<span class="track"><span class="fill" id="fill"></span></span></div>' if order else "")
    return (f'<nav class="tbar" aria-label="Sections"><div class="tbar-in">'
            f'<div class="tjump">{tabs}</div><div class="tright">'
            f'<a class="abtn" href="archive.html">Search the archive →</a>{prog}</div></div></nav>')


def _budget(order, n_skim, org) -> str:
    rows = []
    firsts = [i for i in order if i.extra.get("priority") == "first"]
    if firsts:
        who = f"what {escape(org)} does" if org else "what you do"
        n_first = len(firsts)
        rows.append((f"{sum(read_minutes(i) for i in firsts)} min",
                     f"Read {_story_range(1, n_first)}",
                     f"The one that changes {who} this quarter" if n_first == 1 else
                     f"The {_words(n_first)} that change {who} this quarter", "order-0"))
    if len(order) > len(firsts):
        n_today = len(order) - len(firsts)
        rows.append((f"{sum(read_minutes(i) for i in order)} min",
                     f"All {_words(len(order))} in the reading order" if len(order) > 1
                     else "The story in the reading order",
                     f"Adds the {_words(n_today) if n_today > 1 else 'one'} to read today"
                     if firsts else "The day's lead stories", "order-0"))
    if n_skim:
        rows.append((f"+{max(1, round(n_skim * 0.5))} min",
                     f"Skim the other {n_skim}" if order else f"Skim all {n_skim}",
                     "Headlines only; tap for a one-line gist", "skim"))
    if not rows:
        return ""
    body = "".join(
        f'<a class="brow go" href="#{target}"><span class="time">{time}</span>'
        f'<span class="what">{what}<span>{detail}</span></span></a>'
        for time, what, detail, target in rows)
    return f'<aside class="budget"><div class="bt">How much time do you have?</div>{body}</aside>'


def _summary_section(summary, order, skim, org, weekly=False) -> str:
    if not summary:
        return ""
    names = [t.get("tab") or tab_label(t["name"]) for t, _ in skim]
    lis = ""
    for n, s in enumerate(summary, 1):
        label, target = ref_target(s.get("ref"), names)
        jump = (f'<a class="jump go" href="#{target}">→ {escape(label)}</a>' if target else "")
        lis += (f'<li><span class="ix">{n:02d}</span><div><p><b>{escape(s["lead"])}</b> '
                f'{escape(s["text"])}</p>{jump}</div></li>')
    n_skim = sum(len(its) for _, its in skim)
    return (f'<section class="sum" id="summary"><div class="sum-main">'
            f'<h2 class="h">The {"week" if weekly else "day"} in 30 seconds</h2>'
            f'<ol class="takeaways">{lis}</ol></div>'
            f'{_budget(order, n_skim, org)}</section>')


def _order_item(n, item, section, org, reading_images) -> str:
    tier = item.extra.get("priority") or ""
    href = escape(_safe_url(item.url), quote=True)
    ext = 'target="_blank" rel="noopener"'
    also = item.extra.get("also") or []
    meta = (f'<div class="meta">{_badge(item)}<span>{escape(item.source)}</span>'
            f'<span class="quiet">{escape(item.extra.get("day_label") or section)} · '
            f'{read_minutes(item)} min</span>'
            + (f'<span class="quiet">· {len(also) + 1} sources, 1 story</span>' if also else "")
            + "</div>")
    why = item.extra.get("why")
    why_html = (f'<div class="whybox"><b>Why it matters{escape(f" for {org}") if org else ""}</b>'
                f'{escape(why)}</div>' if why else "")
    gist = f'<p class="gist">{escape(item.summary)}</p>' if item.summary else ""
    also_html = ('<div class="also"><span>Also covered by</span>' + "".join(
        f'<a href="{escape(_safe_url(a.url), quote=True)}" {ext} '
        f'title="{escape(a.title, quote=True)}">{escape(a.source)}</a>' for a in also)
        + "</div>" if also else "")
    img = _image(item)
    show = reading_images == "all" or (reading_images == "first" and tier == "first")
    pic = (f'<a class="item-pic" href="{href}" {ext} tabindex="-1">'
           f'<img src="{escape(img, quote=True)}" alt="" loading="lazy" referrerpolicy="no-referrer" '
           f'onerror="this.parentNode.remove()"></a>' if img and show else "")
    return (f'<article class="item{" " + tier if tier else ""}" id="order-{n}" data-n="{n}">'
            f'<div class="num" data-num="{n + 1}">{n + 1}</div><div class="item-body">{meta}'
            f'<h3><a class="t" href="{href}" {ext}>{escape(display_title(item))}</a></h3>'
            f'{why_html}{gist}{also_html}<div class="acts">'
            f'<button class="mark" type="button" aria-pressed="false" hidden>Mark as read</button>'
            f'<a class="open-link" href="{href}" {ext}>Open article ↗</a></div></div>{pic}</article>')


def _order_section(order, themes, org, reading_images, read_key, weekly=False) -> str:
    if not order:
        return ""
    section = _section_of(themes)
    minutes = sum(read_minutes(i) for i in order)
    rows = "".join(_order_item(n, i, section.get(id(i), ""), org, reading_images)
                   for n, i in enumerate(order))
    return (f'<section class="order" id="order" data-key="{escape(read_key, quote=True)}">'
            f'<h2 class="h">{"The week in " + str(len(order)) if weekly else "Read in this order"}<span>{_plural(len(order), "story", "stories")} · '
            f'~{minutes} min</span></h2>{rows}</section>')


def _explain_section(explainer) -> str:
    if not explainer or not explainer.get("steps"):
        return ""
    steps = "".join(
        f'<li><span class="ic" aria-hidden="true">{escape(st["icon"])}</span>'
        f'<span><span class="sn">Step {n}</span>{escape(st["text"])}</span></li>'
        for n, st in enumerate(explainer["steps"], 1))
    why = explainer.get("why")
    why_html = f'<p class="why-line"><b>Why today:</b> {escape(why)}</p>' if why else ""
    label, target = ref_target(explainer.get("ref"), [])
    jump = f'<a class="jump go" href="#{target}">→ {escape(label)}</a>' if target else ""
    return (f'<section class="explain" id="explain"><h2 class="h">Explain it simply'
            f'<span>{escape(explainer["concept"])}</span></h2>'
            f'<ol class="steps">{steps}</ol>{why_html}{jump}</section>')


def _skim_section(skim, expanded) -> str:
    if not skim:
        return ""
    n_skim = sum(len(its) for _, its in skim)
    cols = ""
    for s, (theme, items) in enumerate(skim):
        rows = ""
        for r, i in enumerate(items):
            gid = f"gist-{s}-{r}"
            summary = escape(i.summary) if i.summary else \
                "No summary in the feed; open the article for the full story."
            rows += (f'<div class="srow"><button class="stog" type="button" aria-expanded="true" '
                     f'aria-controls="{gid}"><span><b>{escape(i.title)}</b>'
                     f'<span class="src">{"Follow-up · " if i.extra.get("followup") else ""}'
                     f'{escape(i.source)}</span></span>'
                     f'<span class="sign" aria-hidden="true">−</span></button>'
                     f'<div class="sgist" id="{gid}"><span>{summary}</span>'
                     f'<a href="{escape(_safe_url(i.url), quote=True)}" target="_blank" rel="noopener">'
                     f'Open article ↗</a></div></div>')
        cols += (f'<div class="skim-col" id="skim-{s}"><div class="skim-head">'
                 f'<h3 title="{escape(theme["name"], quote=True)}">'
                 f'{escape(theme.get("tab") or tab_label(theme["name"]))}</h3>'
                 f'<span>{_plural(len(items), "story", "stories")}</span></div>{rows}</div>')
    return (f'<section class="skim" id="skim" data-expanded="{"true" if expanded else "false"}">'
            f'<h2 class="h">Skim if you have time<span>{_plural(n_skim, "headline", "headlines")}'
            f' · tap one for the gist</span></h2><div class="skim-grid">{cols}</div></section>')


def _edition_data(themes, edition_date, slot_key) -> list:
    """What the Archive needs from this edition, one row per story (a cluster's
    other sources ride along in its lead's `also`)."""
    order, _ = triage(themes)
    in_order = {id(i): n for n, i in enumerate(order, 1)}
    rows = []
    for theme in themes:
        for i in theme["items"]:
            minutes = i.extra.get("minutes")
            rows.append({
                "title": i.title, "url": _safe_url(i.url), "source": i.source,
                "summary": (i.summary or "")[:280], "image": _image(i),
                "date": edition_date, "slot": slot_key,
                "p": i.extra.get("priority") or "", "why": i.extra.get("why") or "",
                "section": theme["name"], "tab": theme.get("tab") or tab_label(theme["name"]),
                "minutes": read_minutes(i) if id(i) in in_order else (
                    minutes if isinstance(minutes, int) else None),
                "n": in_order.get(id(i)),  # place in the day's reading order
                "topic": i.extra.get("topic") or "",
                "cluster": i.extra.get("cluster_title") or "",
                "also": [{"title": a.title, "url": _safe_url(a.url), "source": a.source}
                         for a in i.extra.get("also") or []],
            })
    return rows


def _shell(title, page_title, body, extra_css, script, nav_on, top="") -> str:
    """The page frame. `top` sits between the masthead and <main> (the
    edition's sticky triage bar)."""
    nav = (f'<a class="{"on" if nav_on == "today" else ""}" href="index.html">Today</a>'
           f'<a class="{"on" if nav_on == "archive" else ""}" href="archive.html">Archive</a>')
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(page_title)}</title>{FONTS}<style>{_BASE_CSS}{extra_css}</style></head>'
        f'<body><header class="mast"><a class="word" href="index.html">{escape(title)}</a>'
        f'<nav class="nav">{nav}</nav></header>{top}<main>{body}</main>'
        f'<footer><span>{escape(title)} · curated by Claude</span>'
        f'<a href="{"archive.html" if nav_on == "today" else "index.html"}">'
        f'{"Browse the archive →" if nav_on == "today" else "← Today’s edition"}</a></footer>'
        f'{script}</body></html>'
    )


def build_web_edition(title, themes, *, greeting="", edition_label="", date_str=None,
                      edition_date=None, slot_key="edition", archive_link="archive.html",
                      summary=None, org="", reading_images="first", skim_expanded=False,
                      weekly=False, explainer=None) -> str:
    """Render the full browsable edition as a self-contained HTML string.
    `summary` comes from summary.py; `explainer` from explain.py (None = no
    "Explain it simply" section); `org` names the reader in the why lines;
    `reading_images` is first|all|none (which reading-order stories get a
    picture); `skim_expanded` opens every skim gist by default; `weekly`
    titles it as the Friday Week in 5 (weekly.py)."""
    now = datetime.now(timezone.utc)
    date_str = date_str or now.strftime("%A %d %B %Y")
    edition_date = edition_date or now.strftime("%Y-%m-%d")
    if reading_images not in READING_IMAGES:
        reading_images = "first"
    summary = summary or []
    order, skim = triage(themes)
    n_skim = sum(len(its) for _, its in skim)
    everything = all_items(themes)
    sources = len({i.source for i in everything})
    labelled = any(i.extra.get("priority") in ("first", "today") for i in order)
    dateline = (f'<div class="dateline"><span><b>{escape(date_str)}</b>'
                + (f' · {escape(edition_label)}' if edition_label else "")
                + f'</span><span>{_plural(len(everything), "story", "stories")} from '
                f'{_plural(sources, "source", "sources")}'
                + (f' · {len(order)} worth reading' if labelled else "") + '</span></div>')
    greet_html = f'<div class="greeting">{escape(greeting)}</div>' if greeting else ""
    read_key = f"edge-read-{edition_date}-{slot_key}"
    body = (f'<div class="wrap">{dateline}{greet_html}'
            f'{_summary_section(summary, order, skim, org, weekly)}'
            f'{_order_section(order, themes, org, reading_images, read_key, weekly)}'
            f'{_explain_section(explainer)}'
            f'{_skim_section(skim, skim_expanded)}'
            f'<a class="acta" href="archive.html"><span><span class="k">Looking for something older?</span>'
            f'<span class="l">Search every story {escape(title)} has sent, by topic, priority or source.'
            f'</span></span><span class="b">Open the archive →</span></a></div>')
    data = (f'<script id="edition-data" type="application/json">'
            f'{_json_for_html(_edition_data(themes, edition_date, slot_key))}</script>'
            f'<script id="edition-summary" type="application/json">'
            f'{_json_for_html([{"lead": x["lead"], "text": x["text"]} for x in summary])}</script>'
            + (f'<script id="edition-explainer" type="application/json">'
               f'{_json_for_html(explainer)}</script>' if explainer else ""))
    script = data + f"<script>{_EDITION_JS}</script>"
    page_title = f"{title} — {edition_label}" if edition_label else title
    return _shell(title, page_title, body, _EDITION_CSS, script, "today",
                  top=_triage_bar(summary, order, n_skim, weekly, explainer))


def save_edition(out_dir, html, date_str, slot_key) -> dict:
    """Write `html` to <out_dir>/index.html and a permanent dated copy under
    <out_dir>/editions/. Returns the two paths written."""
    editions_dir = os.path.join(out_dir, "editions")
    os.makedirs(editions_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "index.html")
    edition_path = os.path.join(editions_dir, f"{date_str}-{slot_key}.html")
    for path in (index_path, edition_path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    return {"index": index_path, "edition": edition_path}


def _list_editions(out_dir) -> list:
    """[(date, slot, filename)] for every editions/*.html, newest first."""
    found = []
    for path in glob.glob(os.path.join(out_dir, "editions", "*.html")):
        m = _EDITION_RE.match(os.path.basename(path))
        if m:
            found.append((m.group(1), m.group(2), os.path.basename(path)))
    found.sort(reverse=True)  # ISO dates sort lexically; newest first
    return found


def _read_script(path, pattern, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            m = pattern.search(fh.read())
        return json.loads(m.group(1)) if m else default
    except (OSError, ValueError):
        return default


def _read_edition_data(path) -> list:
    """Stories embedded in a saved edition, or [] for pages without data."""
    rows = _read_script(path, _DATA_RE, [])
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("url") and r.get("title")]


def collect_archive(out_dir) -> list:
    """Every story from every saved edition, oldest edition first, one row per
    URL (a story that ran twice keeps its first appearance, as in the Grove)."""
    seen, rows = set(), []
    for date_str, slot, fname in reversed(_list_editions(out_dir)):
        for r in _read_edition_data(os.path.join(out_dir, "editions", fname)):
            key = r["url"].split("#")[0].rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            r["date"], r["slot"], r["file"] = date_str, slot, fname
            rows.append(r)
    return rows


def collect_takes(out_dir) -> dict:
    """{date: "Lead. Text"}: each day's first summary takeaway (the Archive's
    "That day" line), from the latest edition of that day that has one.
    Editions saved before summaries existed simply have none."""
    takes = {}
    for date_str, _slot, fname in _list_editions(out_dir):  # newest first
        if date_str in takes:
            continue
        summary = _read_script(os.path.join(out_dir, "editions", fname), _SUMMARY_RE, [])
        first = summary[0] if isinstance(summary, list) and summary else None
        if isinstance(first, dict) and first.get("text"):
            takes[date_str] = " ".join(x for x in (str(first.get("lead") or "").strip(),
                                                   str(first["text"]).strip()) if x)
    return takes


_ARCHIVE_CSS = css(
    "mark{background:#FFD9C4;color:inherit;padding:0}"
    ".a-head{padding:26px 0 6px;display:flex;flex-wrap:wrap;align-items:flex-end;"
    "justify-content:space-between;gap:8px 20px}"
    ".a-head h1{font:900 40px/1 Archivo,Arial,sans-serif;font-stretch:125%;margin:0;letter-spacing:.01em}"
    ".stats{font:12px 'IBM Plex Mono',monospace;color:$muted;letter-spacing:.04em}"
    # Sticky tools: search, priority control, match count.
    ".tools{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.96);"
    "-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);padding:14px 0 12px;"
    "border-bottom:1px solid $rule;display:grid;gap:10px}"
    ".search{position:relative;display:block}"
    ".search span{position:absolute;left:14px;top:50%;transform:translateY(-50%);"
    "font:500 12px 'IBM Plex Mono',monospace;color:$muted;letter-spacing:.06em;pointer-events:none}"
    ".search input{width:100%;font:16px 'IBM Plex Sans',sans-serif;padding:12px 14px 12px 84px;"
    "border:2px solid $black;border-radius:4px;background:$white;color:$ink;outline-color:$orange}"
    ".search input::placeholder{color:#8A8A8A}"
    ".trow{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;justify-content:space-between}"
    ".seg{display:flex;flex-wrap:wrap;border:1px solid $rule;border-radius:999px;padding:2px}"
    ".seg button{appearance:none;cursor:pointer;white-space:nowrap;font:500 12.5px 'IBM Plex Sans',sans-serif;"
    "padding:5px 12px;border:0;border-radius:999px;background:transparent;color:$ink}"
    ".seg button[aria-pressed=true]{background:$black;color:$white}"
    ".seg i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px}"
    ".seg em{font:400 11px 'IBM Plex Mono',monospace;font-style:normal;margin-left:5px;opacity:.7}"
    ".dot-first{background:$orange}.dot-today{background:$cobalt}.dot-later{background:#BDBDBD}"
    ".count{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;"
    "font:12px 'IBM Plex Mono',monospace;color:$muted}"
    ".linkbtn{appearance:none;background:none;border:0;cursor:pointer;color:$cobalt;"
    "font:500 13px 'IBM Plex Sans',sans-serif;text-decoration:underline;padding:4px}"
    # Topics + source beside the results.
    ".abody{display:grid;grid-template-columns:minmax(180px,240px) minmax(0,1fr);gap:28px 40px;"
    "padding:22px 0 48px;align-items:start}"
    ".aside{display:grid;gap:26px;position:sticky;top:130px}"
    ".ah{font:800 12.5px Archivo,Arial,sans-serif;font-stretch:112%;letter-spacing:.16em;"
    "text-transform:uppercase;padding-bottom:8px;border-bottom:2px solid $black;margin:0}"
    ".topic{appearance:none;width:100%;text-align:left;cursor:pointer;background:transparent;border:0;"
    "border-bottom:1px solid $rule;padding:9px 8px;display:flex;justify-content:space-between;gap:10px;"
    "align-items:baseline;color:$ink;font:400 14px 'IBM Plex Sans',sans-serif}"
    ".topic:hover{color:$cobalt}"
    ".topic em{font:11px 'IBM Plex Mono',monospace;font-style:normal;color:$muted}"
    ".topic.zero{color:#8A8A8A}"
    ".topic[aria-pressed=true]{background:$orange_tint;font-weight:700;color:$black}"
    ".topic[aria-pressed=true] em{color:#8A3207}"
    ".aside select{width:100%;margin-top:10px;font:14px 'IBM Plex Sans',sans-serif;padding:7px 10px;"
    "border:1px solid $rule;border-radius:4px;background:$white;color:$ink}"
    # Results, grouped by day.
    ".day{padding-bottom:18px}"
    ".dh{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 16px;"
    "padding:10px 0 8px;border-bottom:2px solid $black}"
    ".dh h2{flex:1 0 auto;font:800 21px/1.2 Archivo,Arial,sans-serif;margin:0}"
    ".dh span{flex:none;font:12px 'IBM Plex Mono',monospace;color:$muted;white-space:nowrap}"
    ".take{margin:12px 0 4px;font:500 16px/1.4 Archivo,Arial,sans-serif;text-wrap:pretty}"
    ".take b{font:500 11px 'IBM Plex Mono',monospace;letter-spacing:.08em;text-transform:uppercase;"
    "color:$orange;margin-right:8px}"
    ".arow{display:grid;grid-template-columns:28px minmax(0,1fr) auto;gap:4px 14px;padding:14px 0;"
    "border-bottom:1px solid $rule}"
    ".anum{font:900 20px/1.2 Archivo,Arial,sans-serif;color:#BDBDBD}"
    ".anum.first{color:$orange}.anum.today{color:$cobalt}"
    ".abody-in{display:grid;gap:5px;align-content:start}"
    ".meta span{white-space:nowrap}.meta .quiet{color:$muted}"
    ".arow h3{font:700 17px/1.25 Archivo,Arial,sans-serif;margin:0;text-wrap:balance}"
    ".awhy{font-size:13.5px;line-height:1.45;color:#333333}"
    ".awhy b{font:500 10.5px 'IBM Plex Mono',monospace;letter-spacing:.08em;text-transform:uppercase;"
    "color:#8A3207;margin-right:6px}"
    ".aalso{font-size:12.5px;color:$muted}"
    ".ath{display:block;width:96px;height:64px;object-fit:cover;border-radius:3px;border:1px solid $rule;"
    "background:$paper}"
    ".more{appearance:none;background:none;border:0;cursor:pointer;padding:12px 0 4px;"
    "font:500 13px 'IBM Plex Sans',sans-serif;color:$cobalt;display:flex;gap:8px;align-items:center}"
    ".more span{font:500 14px 'IBM Plex Mono',monospace}"
    ".mlist{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:0 28px}"
    ".mrow{display:block;padding:9px 0;border-top:1px solid $rule;text-decoration:none;color:$ink}"
    ".mrow:hover{color:$cobalt}"
    ".mrow b{display:block;font:600 14px/1.3 Archivo,Arial,sans-serif}"
    ".mrow span{font:11px 'IBM Plex Mono',monospace;color:$muted}"
    ".empty{padding:40px 0;text-align:center;color:$muted;margin:0}"
    ".editions{margin-top:36px;padding-top:18px;border-top:2px solid $black}"
    ".editions ul{list-style:none;margin:8px 0 0;padding:0;display:grid;"
    "grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr));gap:4px 20px}"
    ".editions li{padding:6px 0;border-bottom:1px solid $rule;font-size:14px}"
    ".editions a{color:$cobalt;text-decoration:none}.editions a:hover{text-decoration:underline}"
    "@media (max-width:700px){.abody{grid-template-columns:minmax(0,1fr)}.aside{position:static}}"
    "@media (max-width:640px){.a-head h1{font-size:32px}.arow{grid-template-columns:24px minmax(0,1fr)}"
    ".ath{grid-column:2}}"
)

_ARCHIVE_JS = r"""
(function(){
  function json(id,d){try{return JSON.parse(document.getElementById(id).textContent)||d;}catch(e){return d;}}
  var all=json('archive-data',[]), takes=json('archive-takes',{});
  var OTHER=document.getElementById('topics').getAttribute('data-other');
  var LABEL={first:'Read first',today:'Read today',later:'Later'}, RANK={first:0,today:1,later:2};
  var MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var DOW=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function safe(u){return /^https?:\/\//.test(u||'')?u:'#';}
  function hl(t,q){
    t=String(t||''); if(!q) return esc(t);
    var lo=t.toLowerCase(), out='', k=0, j;
    if(lo.length!==t.length) return esc(t);
    while((j=lo.indexOf(q,k))>=0){out+=esc(t.slice(k,j))+'<mark>'+esc(t.slice(j,j+q.length))+'</mark>';k=j+q.length;}
    return out+esc(t.slice(k));
  }
  function day(d){var x=new Date(d+'T12:00:00Z');return DOW[x.getUTCDay()]+' '+x.getUTCDate()+' '+MON[x.getUTCMonth()];}
  all.forEach(function(i,n){
    i.p=LABEL[i.p]?i.p:'later'; i.tp=i.topic||OTHER; i.t=i.cluster||i.title; i._n=n;
    i.alsoNames=(i.also||[]).map(function(a){return typeof a==='string'?a:(a&&a.source)||'';}).filter(Boolean);
  });
  // Reading-order numbers for editions saved before rows carried them.
  var byDate={}; all.forEach(function(i){(byDate[i.date]=byDate[i.date]||[]).push(i);});
  Object.keys(byDate).forEach(function(d){
    var top=byDate[d].filter(function(i){return i.p!=='later';}), c=0;
    if(top.some(function(i){return typeof i.n!=='number';}))
      top.sort(function(a,b){return RANK[a.p]-RANK[b.p]||a._n-b._n;}).forEach(function(i){i.n=++c;});
  });
  var latest=all.length?all.map(function(i){return i.date;}).sort().slice(-1)[0]:null;
  var q=document.getElementById('q'), src=document.getElementById('src'), box=document.getElementById('groups');
  var count=document.getElementById('count'), clear=document.getElementById('clear');
  var tiers=[].slice.call(document.querySelectorAll('#tiers button'));
  var topics=[].slice.call(document.querySelectorAll('#topics .topic'));
  var st={q:'',tier:'all',topic:'',src:'all'}, open={};
  var sources=[]; all.forEach(function(i){if(sources.indexOf(i.source)<0)sources.push(i.source);}); sources.sort();
  src.innerHTML='<option value="all">All '+sources.length+' sources</option>'+sources.map(function(s){return '<option value="'+esc(s)+'">'+esc(s)+'</option>';}).join('');
  try{var h=new URLSearchParams(location.hash.slice(1));
    st.q=h.get('q')||''; st.tier=LABEL[h.get('tier')]?h.get('tier'):'all'; st.topic=h.get('topic')||'';
    st.src=sources.indexOf(h.get('source'))>=0?h.get('source'):'all';}catch(e){}
  q.value=st.q; src.value=st.src;
  function sync(){
    var h=[]; if(st.q) h.push('q='+encodeURIComponent(st.q)); if(st.tier!=='all') h.push('tier='+st.tier);
    if(st.topic) h.push('topic='+encodeURIComponent(st.topic)); if(st.src!=='all') h.push('source='+encodeURIComponent(st.src));
    try{history.replaceState(null,'',h.length?'#'+h.join('&'):location.pathname+location.search);}catch(e){}
  }
  function badge(p){return '<span class="badge badge-'+p+'">'+LABEL[p]+'</span>';}
  function row(i,ql){
    var num=i.p==='later'?'·':String(i.n||'');
    var img=i.image&&i.p!=='later'?'<img class="ath" src="'+esc(i.image)+'" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">':'';
    return '<article class="arow"><span class="anum '+i.p+'">'+num+'</span><div class="abody-in">'
      +'<div class="meta">'+badge(i.p)+'<span>'+esc(i.source)+'</span><span class="quiet">'+esc(i.tp)+'</span></div>'
      +'<h3><a class="t" href="'+esc(safe(i.url))+'" target="_blank" rel="noopener">'+hl(i.t,ql)+'</a></h3>'
      +(i.why?'<div class="awhy"><b>Why</b>'+esc(i.why)+'</div>':'')
      +(i.alsoNames.length?'<div class="aalso">Also covered by '+esc(i.alsoNames.join(' · '))+'</div>':'')
      +'</div>'+img+'</article>';
  }
  function render(){
    var ql=st.q.trim().toLowerCase();
    function match(i){return !ql||(i.t+' '+i.title+' '+i.source+' '+(i.why||'')+' '+(i.summary||'')+' '+i.tp).toLowerCase().indexOf(ql)>=0;}
    var base=all.filter(function(i){return match(i)&&(st.src==='all'||i.source===st.src);});
    function inTier(i,t){return t==='all'||i.p===t;}
    var hits=base.filter(function(i){return inTier(i,st.tier)&&(!st.topic||i.tp===st.topic);});
    var filtered=!!(ql||st.tier!=='all'||st.topic||st.src!=='all');
    tiers.forEach(function(b){var k=b.getAttribute('data-v');
      b.setAttribute('aria-pressed',String(k===st.tier));
      b.querySelector('em').textContent=base.filter(function(i){return inTier(i,k)&&(!st.topic||i.tp===st.topic);}).length;});
    topics.forEach(function(b){var k=b.getAttribute('data-k');
      var n=base.filter(function(i){return inTier(i,st.tier)&&(!k||i.tp===k);}).length;
      b.setAttribute('aria-pressed',String(k===st.topic)); b.classList.toggle('zero',!n);
      b.querySelector('em').textContent=n;});
    count.textContent=filtered?hits.length+' of '+all.length+' stories match':all.length+' stories';
    clear.hidden=!filtered;
    var groups={}, order=[];
    hits.forEach(function(i){if(!groups[i.date]){groups[i.date]=[];order.push(i.date);} groups[i.date].push(i);});
    order.sort().reverse();
    box.innerHTML=order.length?order.map(function(d){
      var list=groups[d].slice().sort(function(a,b){return RANK[a.p]-RANK[b.p]||(a.n||99)-(b.n||99)||a._n-b._n;});
      var top=filtered?list:list.filter(function(i){return i.p!=='later';});
      var rest=filtered?[]:list.filter(function(i){return i.p==='later';});
      var f=list.filter(function(i){return i.p==='first';}).length;
      var take=!filtered&&takes[d]?'<p class="take"><b>That day</b>'+esc(takes[d])+'</p>':'';
      var more=rest.length?'<button class="more" type="button" data-d="'+d+'" aria-expanded="'+(open[d]?'true':'false')+'"><span>'+(open[d]?'−':'+')+'</span>'+(open[d]?'Hide ':'Show ')+rest.length+' more from that day</button>'
        +(open[d]?'<div class="mlist">'+rest.map(function(i){return '<a class="mrow" href="'+esc(safe(i.url))+'" target="_blank" rel="noopener"><b>'+esc(i.t)+'</b><span>'+esc(i.source)+' · '+esc(i.tp)+'</span></a>';}).join('')+'</div>':''):'';
      return '<section class="day"><div class="dh"><h2>'+day(d)+(d===latest?' · latest':'')+'</h2><span>'
        +list.length+(filtered?' matching':' stories')+(f?' · '+f+' read first':'')+'</span></div>'
        +take+top.map(function(i){return row(i,ql);}).join('')+more+'</section>';
    }).join(''):'<p class="empty">'+(all.length?'No stories match. Try a shorter search or clear the filters.':'No stories yet. The first edition fills this in.')+'</p>';
    sync();
  }
  q.addEventListener('input',function(){st.q=q.value;render();});
  tiers.forEach(function(b){b.addEventListener('click',function(){st.tier=b.getAttribute('data-v');render();});});
  topics.forEach(function(b){b.addEventListener('click',function(){var k=b.getAttribute('data-k');st.topic=(k&&st.topic===k)?'':k;render();});});
  src.addEventListener('change',function(){st.src=src.value;render();});
  clear.addEventListener('click',function(){st={q:'',tier:'all',topic:'',src:'all'};q.value='';src.value='all';render();});
  box.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.more'); if(!b) return;
    var d=b.getAttribute('data-d'); open[d]=!open[d]; render();});
  render();
})();
"""


def archive_topics(rows, topics=None) -> list:
    """The archive's topic list: the configured `topics`, then any other topic
    found in saved rows, then "Other" when a story has none."""
    out = [t for t in (topics or []) if t]
    known = {t.lower() for t in out}
    for r in rows:
        t = str(r.get("topic") or "").strip()
        if t and t.lower() not in known:
            known.add(t.lower())
            out.append(t)
    if any(not str(r.get("topic") or "").strip() for r in rows) or not out:
        out.append(OTHER_TOPIC)
    return out


def build_archive_index(out_dir, site_title="The Archive", topics=None) -> str:
    """(Re)build <out_dir>/archive.html from the saved editions and return it:
    every story ever sent, grouped by day, searchable and filterable by
    priority, topic and source, plus a list of editions. `topics` is the
    fixed category list (config `archive.topics`); stories without one show
    under "Other"."""
    rows = collect_archive(out_dir)
    editions = _list_editions(out_dir)
    dates = sorted({r["date"] for r in rows})
    stats = (f'{len(rows)} stories · {len(editions)} editions · '
             f'{escape(datetime.strptime(dates[0], "%Y-%m-%d").strftime("%d %b").lstrip("0"))} – '
             f'{escape(datetime.strptime(dates[-1], "%Y-%m-%d").strftime("%d %b %Y").lstrip("0"))}'
             if dates else f'{len(editions)} editions')
    tiers = "".join(
        f'<button type="button" data-v="{k}" aria-pressed="{"true" if k == "all" else "false"}">'
        + ("" if k == "all" else f'<i class="dot-{k}"></i>')
        + f'{"All" if k == "all" else escape(LABELS[k])}<em></em></button>' for k in ("all",) + TIERS)
    topic_list = archive_topics(rows, topics)
    topic_btns = "".join(
        f'<button class="topic" type="button" data-k="{escape(k, quote=True)}" '
        f'aria-pressed="{"true" if not k else "false"}"><span>{escape(k or "All topics")}</span>'
        f'<em></em></button>' for k in [""] + topic_list)
    ed_rows = "".join(
        f'<li><a href="editions/{escape(fname, quote=True)}">'
        f'{escape(date_str)} · {escape(slot.replace("-", " ").title())}</a></li>'
        for date_str, slot, fname in editions) or "<li>No past editions yet.</li>"
    body = (
        f'<div class="wrap"><div class="a-head"><h1>Archive</h1><div class="stats">{stats}</div></div>'
        '<div class="tools"><label class="search"><span>SEARCH</span>'
        '<input id="q" type="search" placeholder="Headlines, companies, why-it-matters lines" '
        'aria-label="Search the archive"></label>'
        f'<div class="trow"><div class="seg" id="tiers" role="group" aria-label="Priority">{tiers}</div>'
        '<div class="count"><span id="count"></span>'
        '<button class="linkbtn" id="clear" type="button" hidden>Clear filters</button></div></div></div>'
        '<div class="abody"><aside class="aside"><div id="topics" '
        f'data-other="{escape(OTHER_TOPIC, quote=True)}"><h2 class="ah">Topics</h2>{topic_btns}</div>'
        '<div><h2 class="ah">Source</h2><select id="src" aria-label="Filter by source"></select></div>'
        '</aside><div><div id="groups"><noscript><p class="empty">The archive needs JavaScript to '
        'search; every edition is linked below.</p></noscript></div>'
        f'<section class="editions"><h2 class="h">Editions <span>{len(editions)}</span></h2>'
        f'<ul>{ed_rows}</ul></section></div></div></div>')
    script = (f'<script id="archive-data" type="application/json">{_json_for_html(rows)}</script>'
              f'<script id="archive-takes" type="application/json">'
              f'{_json_for_html(collect_takes(out_dir))}</script>'
              f'<script>{_ARCHIVE_JS}</script>')
    html = _shell(site_title, f"{site_title} — Archive", body, _ARCHIVE_CSS, script, "archive")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "archive.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    return html
