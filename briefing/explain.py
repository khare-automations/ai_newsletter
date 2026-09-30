"""Explainer: "Explain it simply", one concept from the day's reading order,
explained ELI5-style for someone who knows nothing about it: a few emoji steps
and very few words.

Optional and off by default. Enable in `config.yaml`:

    explain: { enabled: true }

One Claude call after theming. Returns
`{"concept": "MCP", "steps": [{"icon": "📦", "text": "Apps expose tools"}, ...],
"why": "...", "ref": {"stories": [2]} | None}` with 3 or 4 steps, where `ref`
names the reading-order stories (1-based) that use the concept. Returns None
when off, when nothing in the day needs explaining, or on any failure; the
renderers then leave the section out. `recent` (the last concepts explained,
from history.json) is an avoid-list so the same idea doesn't come back daily.
"""
from __future__ import annotations
from briefing.llm import claude_json, make_client
from briefing.priority import triage, display_title

MIN_STEPS, MAX_STEPS = 3, 4
RECENT_KEEP = 20


def _client():
    return make_client()


def is_enabled(cfg) -> bool:
    return bool(cfg) and bool(cfg.get("enabled"))


def _clean(text, limit) -> str:
    return " ".join(str(text or "").split())[:limit]


def _prompt(order, recent) -> str:
    stories = "\n".join(f"Story {n}: {i.source} | {display_title(i)} | {(i.summary or '')[:300]}"
                        for n, i in enumerate(order, 1))
    avoid = (f"Recently explained, pick something else: {', '.join(recent)}.\n" if recent else "")
    return (
        "You write the \"Explain it simply\" box of a daily AI briefing.\n"
        "From today's stories below, pick the ONE technical or financial concept that a smart "
        "reader with no background in it would most need explained to follow them "
        "(e.g. RAG, MCP, evals, fine-tuning, venture debt, a covenant). Pick a concept, not a "
        "company or a product launch.\n"
        "Explain it for someone who knows nothing about it: no jargon, no assumed background, "
        "plain words, but not baby talk and never wrong.\n"
        + avoid
        + "- \"concept\": its usual name, at most 4 words.\n"
        f"- \"steps\": {MIN_STEPS} or {MAX_STEPS} steps that show how it works, in order. Each "
        "has \"icon\": one emoji, and \"text\": at most 6 words.\n"
        "- \"why\": at most 20 words: why it matters in today's news.\n"
        '- "ref": {"stories": [<numbers of the stories that use it>]}.\n'
        'If no story involves a concept worth explaining, return {"explainer": null}.\n'
        "Return ONLY JSON:\n"
        '{"explainer": {"concept": "RAG", "steps": [{"icon": "📚", "text": "Gather the documents"}, '
        '{"icon": "✂️", "text": "Split them into chunks"}, {"icon": "🔍", "text": "Find chunks like the question"}, '
        '{"icon": "✍️", "text": "Answer from those chunks"}], "why": "...", "ref": {"stories": [1]}}}\n\n'
        f"Today's stories (the reading order):\n{stories}"
    )


def _ref(raw, n_order) -> dict | None:
    if not isinstance(raw, dict):
        return None
    stories = raw.get("stories", raw.get("story"))
    if isinstance(stories, int) and not isinstance(stories, bool):
        stories = [stories]
    if not isinstance(stories, list):
        return None
    nums = sorted({s for s in stories
                   if isinstance(s, int) and not isinstance(s, bool) and 1 <= s <= n_order})
    return {"stories": nums} if nums else None


def explain(themes, cfg, recent=()) -> dict | None:
    """The day's explainer (see module doc), or None when off, not needed or on failure."""
    if not is_enabled(cfg):
        return None
    order, _ = triage(themes)
    if not order:
        return None
    recent = [_clean(r, 40) for r in (recent or []) if _clean(r, 40)]
    data = claude_json(_prompt(order, recent), max_tokens=500, context="explain",
                       client_factory=lambda: _client())
    row = data.get("explainer") if isinstance(data, dict) else None
    if not isinstance(row, dict):
        print("[explain] no explainer today", flush=True)
        return None
    concept = _clean(row.get("concept"), 40)
    steps = []
    for s in row.get("steps") if isinstance(row.get("steps"), list) else []:
        if not isinstance(s, dict):
            continue
        text = _clean(s.get("text"), 60)
        if text:
            steps.append({"icon": _clean(s.get("icon"), 8) or "•", "text": text})
    steps = steps[:MAX_STEPS]
    if not concept or len(steps) < MIN_STEPS:
        print("[explain] explainer incomplete; left out", flush=True)
        return None
    print(f"[explain] {concept}", flush=True)
    return {"concept": concept, "steps": steps, "why": _clean(row.get("why"), 160),
            "ref": _ref(row.get("ref"), len(order))}
