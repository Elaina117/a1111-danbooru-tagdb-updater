from __future__ import annotations

import json
import sys
from pathlib import Path

import gradio as gr

EXT_DIR = Path(__file__).resolve().parents[1]
if str(EXT_DIR) not in sys.path:
    sys.path.insert(0, str(EXT_DIR))

from updater_core import (  # noqa: E402
    DEFAULT_INTERVAL_DAYS,
    find_tagcomplete_dir,
    status_snapshot,
    update_tagdb,
)

try:
    from modules import script_callbacks
except Exception:
    script_callbacks = None

CONFIG_PATH = EXT_DIR / "config.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "auto_update": True,
            "interval_days": DEFAULT_INTERVAL_DAYS,
            "tagcomplete_dir": "",
            "auto_configure_tagcomplete": True,
        }


def save_config(auto_update: bool, interval_days: int, tagcomplete_dir: str, auto_configure: bool) -> None:
    data = {
        "auto_update": bool(auto_update),
        "interval_days": max(0, int(interval_days)),
        "tagcomplete_dir": tagcomplete_dir.strip(),
        "auto_configure_tagcomplete": bool(auto_configure),
    }
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def current_info() -> str:
    cfg = load_config()
    snap = status_snapshot(cfg.get("tagcomplete_dir") or None)
    state = snap["state"]
    lines = [
        f"Tag Autocomplete: {snap['target'] or '未検出'}",
        f"自動更新: {'ON' if cfg.get('auto_update', True) else 'OFF'} / 間隔 {cfg.get('interval_days', DEFAULT_INTERVAL_DAYS)} 日",
        f"日本語検索の自動設定: {'ON' if cfg.get('auto_configure_tagcomplete', True) else 'OFF'}",
        f"最終チェック: {state.get('last_check_iso', '未実行')}",
        f"DBスナップショット: {state.get('source_fingerprint', '未取得')}",
        f"最終成功: {state.get('last_success_iso', '未実行')}",
    ]
    if state.get("last_error"):
        lines.append(f"直近のエラー: {state['last_error']}")
    return "\n".join(lines)


def run_update(path_text: str, force: bool, interval_days: int, auto_configure: bool) -> tuple[str, str]:
    result = update_tagdb(
        configured_dir=path_text.strip() or None,
        force=force,
        interval_days=max(0, int(interval_days)),
        auto_configure=bool(auto_configure),
    )
    return result.message, current_info()


def build_ui():
    cfg = load_config()
    detected = find_tagcomplete_dir(cfg.get("tagcomplete_dir") or None)

    with gr.Blocks() as block:
        gr.Markdown(
            "## Danbooru Tag DB Updater\n"
            "`PYU224/tagdb-updater` の最新版を Tag Autocomplete の `tags` フォルダへ反映します。\n\n"
            "**v1.1:** Tag Autocomplete向けにタグ名を自動でアンダースコア形式へ正規化し、"
            "日本語訳による検索設定も自動化します。"
        )
        with gr.Row():
            auto = gr.Checkbox(label="起動時に自動更新チェック", value=cfg.get("auto_update", True))
            days = gr.Number(label="更新チェック間隔（日）", value=cfg.get("interval_days", DEFAULT_INTERVAL_DAYS), precision=0)
        auto_configure = gr.Checkbox(
            label="Tag Autocomplete の日本語検索を自動設定",
            value=cfg.get("auto_configure_tagcomplete", True),
        )
        path = gr.Textbox(
            label="Tag Autocomplete フォルダ（空欄なら自動検出）",
            value=cfg.get("tagcomplete_dir", ""),
            placeholder="例: C:\\ForgeNeo\\extensions\\a1111-sd-webui-tagcomplete",
        )
        detected_box = gr.Markdown(f"検出結果: `{detected or '未検出'}`")
        with gr.Row():
            save = gr.Button("設定を保存")
            update = gr.Button("今すぐ更新", variant="primary")
            force = gr.Checkbox(label="同じスナップショットでも再取得", value=False)
        result = gr.Textbox(label="結果", lines=5, interactive=False)
        info = gr.Textbox(label="状態", value=current_info(), lines=8, interactive=False)

        def save_fn(a, d, p, ac):
            save_config(a, int(d), p, ac)
            return "設定を保存しました。", current_info()

        save.click(save_fn, inputs=[auto, days, path, auto_configure], outputs=[result, info])
        update.click(run_update, inputs=[path, force, days, auto_configure], outputs=[result, info])

    return [(block, "Danbooru Tag DB Updater", "danbooru_tagdb_updater")]


if script_callbacks is not None:
    try:
        @script_callbacks.on_ui_tabs
        def _on_ui_tabs():
            return build_ui()
    except Exception as exc:
        print(f"[Danbooru Tag DB Updater] UI registration failed: {exc}")
