import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from briefing.models import Item
from briefing.explain import explain, is_enabled

def _item(n, **extra):
    return Item.make(source="S", source_type="rss", title=f"T{n}", url=f"http://x/{n}",
                     summary="s", published=datetime.now(timezone.utc), extra=extra)

def _themes():
    return [{"name": "Model Wars", "tab": "Models", "items": [_item(0, priority="first", rank=0),
                                                             _item(1, priority="later")]},
            {"name": "Money", "items": [_item(2, priority="today", rank=1)]}]

def _client(payload):
    c = MagicMock(); block = MagicMock(); block.type = "text"
    block.text = payload if isinstance(payload, str) else json.dumps(payload)
    msg = MagicMock(); msg.content = [block]; c.messages.create.return_value = msg
    return c

def _run(payload, cfg={"enabled": True}, recent=()):
    client = _client(payload)
    with patch("briefing.explain._client", return_value=client):
        return explain(_themes(), cfg, recent=recent), client

_STEPS = [{"icon": "📦", "text": "Apps expose tools"}, {"icon": "🔌", "text": "One standard plug"},
          {"icon": "🤖", "text": "Agent calls any tool"}]

def test_off_by_default_makes_no_call():
    assert not is_enabled({}) and not is_enabled({"enabled": False})
    with patch("briefing.explain._client") as c:
        assert explain(_themes(), {}) is None
        assert explain([], {"enabled": True}) is None  # no reading order, no call
    c.assert_not_called()

def test_explainer_is_cleaned_and_ref_resolved():
    out, client = _run({"explainer": {
        "concept": "  MCP ", "why": " Story 1\n uses it. ",
        "steps": _STEPS + [{"icon": "", "text": "  Human   approves "}, "junk",
                           {"icon": "x", "text": "a fifth step"}],
        "ref": {"stories": [2, 9, 2, True]}}}, recent=["RAG", " ", "Evals"])
    assert out == {"concept": "MCP", "why": "Story 1 uses it.",
                   "steps": _STEPS + [{"icon": "•", "text": "Human approves"}],
                   "ref": {"stories": [2]}}
    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Story 1: S | T0" in prompt and "Story 2: S | T2" in prompt
    assert "Recently explained, pick something else: RAG, Evals." in prompt

def test_long_text_is_cut_and_bad_ref_dropped():
    out, _ = _run({"explainer": {"concept": "C" * 99, "steps": [
        {"icon": "🧠" * 9, "text": "w" * 99}] * 3, "why": "y" * 999, "ref": {"stories": [0]}}})
    assert len(out["concept"]) == 40 and len(out["why"]) == 160 and out["ref"] is None
    assert all(len(s["text"]) == 60 and len(s["icon"]) == 8 for s in out["steps"])

def test_nothing_to_explain_or_failure_gives_none():
    assert _run({"explainer": None})[0] is None
    assert _run({"explainer": {"concept": "X", "steps": _STEPS[:2]}})[0] is None
    assert _run({"explainer": {"concept": "", "steps": _STEPS}})[0] is None
    out, client = _run("not json")
    assert out is None and client.messages.create.call_count == 2
