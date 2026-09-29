import os
from briefing.config import load_config
from briefing.pipeline import run

if __name__ == "__main__":
    # Set by .github/workflows/daily.yml: a manual preview run, or a scheduled run
    # (which must not send twice in a day).
    cfg = load_config("config.yaml")
    run(cfg, history_path="history.json",
        edition=(os.environ.get("BRIEFING_EDITION") or "auto").strip().lower(),
        preview=bool(os.environ.get("BRIEFING_PREVIEW")),
        only_if_unsent=bool(os.environ.get("BRIEFING_ONLY_IF_UNSENT")))
