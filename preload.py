"""Early startup hook: update tag DB before normal extension scripts load."""

import json
from pathlib import Path
import sys

EXT_DIR = Path(__file__).resolve().parent
if str(EXT_DIR) not in sys.path:
    sys.path.insert(0, str(EXT_DIR))

try:
    from updater_core import update_tagdb

    config_path = EXT_DIR / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        config = {}

    if config.get("auto_update", True):
        result = update_tagdb(
            configured_dir=config.get("tagcomplete_dir") or None,
            force=False,
            interval_days=int(config.get("interval_days", 7)),
            auto_configure=bool(config.get("auto_configure_tagcomplete", True)),
        )
        print(f"[Danbooru Tag DB Updater] {result.message}")
    else:
        print("[Danbooru Tag DB Updater] 自動更新は設定でOFFになっています。")
except Exception as exc:
    print(f"[Danbooru Tag DB Updater] startup update failed: {exc}")
