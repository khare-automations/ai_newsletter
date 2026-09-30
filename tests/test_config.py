import pytest
from briefing.config import load_config, ConfigError

VALID = """
briefing: {title: "T"}
filter: {mode: interests, interests: ["ai"], max_items: 10, recency_hours: 24, per_source_cap: 5}
sources:
  - {type: rss, name: "BBC", url: "http://x/rss"}
"""

def test_load_valid(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(VALID, encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.title == "T"
    assert cfg.filter_mode == "interests"
    assert cfg.max_items == 10
    assert cfg.sources[0]["type"] == "rss"

def test_bad_filter_mode_raises(tmp_path):
    bad = VALID.replace("mode: interests", "mode: nonsense")
    p = tmp_path / "c.yaml"; p.write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(p))

def test_source_missing_type_raises(tmp_path):
    bad = VALID.replace('{type: rss, name: "BBC", url: "http://x/rss"}', '{name: "BBC"}')
    p = tmp_path / "c.yaml"; p.write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(p))

def test_optional_blocks_default_off(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(VALID, encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.voice == {} and cfg.web == {} and cfg.editions == []
    assert cfg.email_mode == "full"

def test_optional_blocks_parsed(tmp_path):
    extra = VALID + """
email: {mode: cover}
voice: {enabled: true, name: "Sage", tone: "warm"}
web: {enabled: true, output_dir: "docs", edition_url: "https://x/"}
editions:
  - {key: morning, label: "Morning", until_hour: 12}
  - {key: evening, label: "Evening"}
"""
    p = tmp_path / "c.yaml"; p.write_text(extra, encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.email_mode == "cover"
    assert cfg.voice["name"] == "Sage"
    assert cfg.web["enabled"] is True
    assert [e["key"] for e in cfg.editions] == ["morning", "evening"]

def test_bad_email_mode_raises(tmp_path):
    bad = VALID + "\nemail: {mode: bogus}\n"
    p = tmp_path / "c.yaml"; p.write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(p))

def test_email_subject_defaults_and_validates(tmp_path):
    import pytest
    from briefing.config import load_config, ConfigError
    base = 'filter: {mode: recent}\nsources: [{type: rss, name: X, url: "http://x"}]\n'
    p = tmp_path / "c.yaml"
    p.write_text(base)
    assert load_config(str(p)).email_subject == "date"
    p.write_text(base + "email: {subject: top_pick}\n")
    assert load_config(str(p)).email_subject == "top_pick"
    p.write_text(base + "email: {subject: shouty}\n")
    with pytest.raises(ConfigError):
        load_config(str(p))

def test_from_name_defaults_blank(tmp_path):
    from briefing.config import load_config
    base = 'filter: {mode: recent}\nsources: [{type: rss, name: X, url: "http://x"}]\n'
    p = tmp_path / "c.yaml"
    p.write_text(base)
    assert load_config(str(p)).email_from_name == ""
    p.write_text(base + 'email: {from_name: "The Edge"}\n')
    assert load_config(str(p)).email_from_name == "The Edge"

def test_repo_config_loads():
    # The live config.yaml must always parse and validate.
    from briefing.config import load_config
    cfg = load_config("config.yaml")
    assert cfg.title and cfg.sources

def test_summary_and_cover_footer_default_off(tmp_path):
    from briefing.config import load_config
    base = 'filter: {mode: recent}\nsources: [{type: rss, name: X, url: "http://x"}]\n'
    p = tmp_path / "c.yaml"
    p.write_text(base)
    cfg = load_config(str(p))
    assert cfg.summary == {} and cfg.email_unsubscribe == "" and cfg.email_address == ""
    assert cfg.explain == {}
    assert cfg.email_feedback == ""
    p.write_text(base + 'summary: {enabled: true}\nexplain: {enabled: true}\n'
                 'email: {unsubscribe: "mailto:u@x.com", address: "1 Road, Zurich"}\n')
    cfg = load_config(str(p))
    assert cfg.summary == {"enabled": True} and cfg.explain == {"enabled": True}
    assert cfg.email_unsubscribe == "mailto:u@x.com" and cfg.email_address == "1 Road, Zurich"

def test_archive_topics_from_config_or_interests(tmp_path):
    from briefing.config import load_config, topic_label
    assert topic_label("AI for private capital: deal screening, due diligence") == "AI for private capital"
    assert topic_label("frontier model releases, capabilities") == "Frontier model releases"
    assert topic_label("EU AI Act, AI regulation") == "EU AI Act"
    assert len(topic_label("a very long interest line without any punctuation at all")) <= 28
    base = ('filter: {mode: recent, interests: ["longevity research", "AI policy: Europe"]}\n'
            'sources: [{type: rss, name: X, url: "http://x"}]\n')
    p = tmp_path / "c.yaml"
    p.write_text(base)
    assert load_config(str(p)).topics() == ["Longevity research", "AI policy"]
    p.write_text(base + 'archive: {topics: ["Governed AI", " governed ai ", "", "Work & society"]}\n')
    assert load_config(str(p)).topics() == ["Governed AI", "Work & society"]
    assert len(load_config("config.yaml").topics()) == 8

def test_schedule_defaults_off_and_validates_the_day(tmp_path):
    import pytest
    from briefing.config import load_config, ConfigError
    base = 'filter: {mode: recent}\nsources: [{type: rss, name: X, url: "http://x"}]\n'
    p = tmp_path / "c.yaml"
    p.write_text(base)
    assert load_config(str(p)).schedule == {}
    p.write_text(base + "schedule: {weekly_day: Friday, skip_weekends: true}\n")
    assert load_config(str(p)).schedule["skip_weekends"] is True
    p.write_text(base + "schedule: {weekly_day: fri}\n")
    with pytest.raises(ConfigError):
        load_config(str(p))
