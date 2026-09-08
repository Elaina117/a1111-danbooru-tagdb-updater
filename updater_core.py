from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_BASE = "https://raw.githubusercontent.com/PYU224/tagdb-updater/main/dist"
FILES = (
    "danbooru.csv",
    "danbooru-jp.csv",
    "danbooru-ja.csv",
)
DEFAULT_INTERVAL_DAYS = 7
MIN_CSV_BYTES = 1024


def _default_ext_dir() -> Path:
    return Path(__file__).resolve().parent


def _state_path() -> Path:
    override = os.environ.get("DANBOORU_TAGDB_UPDATER_STATE")
    return Path(override) if override else _default_ext_dir() / "state.json"


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _webui_root() -> Path:
    try:
        from modules.paths_internal import script_path
        return Path(script_path)
    except Exception:
        return Path.cwd()


def find_tagcomplete_dir(configured: str | None = None) -> Path | None:
    """Find a1111-sd-webui-tagcomplete directory without importing it."""
    if configured:
        p = Path(configured).expanduser()
        if (p / "tags").is_dir():
            return p.resolve()

    candidates: list[Path] = []
    try:
        from modules.paths_internal import extensions_dir
        roots = [Path(extensions_dir)]
    except Exception:
        roots = [_webui_root() / "extensions"]

    for root in roots:
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if not p.is_dir() or "tagcomplete" not in p.name.lower():
                continue
            if (p / "tags").is_dir():
                candidates.append(p)

    if not candidates:
        return None

    candidates.sort(key=lambda p: (p.name.lower() != "a1111-sd-webui-tagcomplete", p.name.lower()))
    return candidates[0].resolve()


def _get_url(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "a1111-danbooru-tagdb-updater/1.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _looks_like_csv(name: str, content: bytes) -> bool:
    if len(content) < MIN_CSV_BYTES:
        return False
    text = content[:2000].decode("utf-8", errors="ignore")
    if "<html" in text.lower() or "<!doctype" in text.lower():
        return False
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return False
    rows = [row for row in rows if row]
    return len(rows) >= 5 and any(len(row) >= 2 for row in rows[:5])


def _normalize_tag_name(value: str) -> str:
    """Convert the tagdb-updater display form back to Danbooru/tagcomplete form.

    PYU224/tagdb-updater intentionally writes tags as spaces in its CSV output.
    a1111-sd-webui-tagcomplete expects the canonical underscore form in the CSV,
    so `bandage on hair` must become `bandage_on_hair` here.
    """
    return "_".join(value.strip().split())


def _normalize_aliases(value: str) -> str:
    if not value.strip():
        return ""
    aliases = []
    for alias in value.split(","):
        alias = _normalize_tag_name(alias)
        if alias:
            aliases.append(alias)
    return ",".join(aliases)


def normalize_csv_for_tagcomplete(name: str, content: bytes) -> bytes:
    """Normalize English tag keys while preserving CSV semantics and UTF-8."""
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")

    for row in reader:
        if not row:
            continue
        if name == "danbooru-jp.csv":
            if len(row) >= 2:
                row[0] = _normalize_tag_name(row[0])
                writer.writerow(row[:2])
            continue

        # danbooru.csv = tag,type,count,aliases
        # danbooru-ja.csv = tag,type,count,aliases,japanese
        if len(row) >= 1:
            row[0] = _normalize_tag_name(row[0])
        if len(row) >= 4:
            row[3] = _normalize_aliases(row[3])
        writer.writerow(row)

    normalized = output.getvalue().encode("utf-8")
    if len(normalized) < MIN_CSV_BYTES:
        raise ValueError(f"{name} の正規化結果が不自然に小さくなりました。")
    return normalized


def _meta_fingerprint(meta: dict[str, Any]) -> str:
    for key in ("generated_at", "updated_at", "generatedAt", "version"):
        value = meta.get(key)
        if value:
            return str(value)
    return str(meta)


@dataclass
class UpdateResult:
    status: str
    message: str
    changed: bool = False
    checked_at: float | None = None
    source_fingerprint: str | None = None
    tagcomplete_dir: str | None = None


def should_check(state: dict[str, Any], interval_days: int) -> bool:
    last_check = float(state.get("last_check_epoch", 0) or 0)
    interval = max(0, int(interval_days)) * 86400
    return (time.time() - last_check) >= interval


def _configure_tagcomplete_settings() -> str | None:
    """Enable Japanese translation search without overwriting an existing choice."""
    try:
        from modules import shared
    except Exception:
        return None

    try:
        opts = shared.opts
        changed = False

        # Main tag file: only set it when currently unset/None.
        current_tag_file = opts.data.get("tac_tagFile")
        if not current_tag_file or current_tag_file == "None":
            opts.data["tac_tagFile"] = "danbooru.csv"
            changed = True

        current_translation = opts.data.get("tac_translation.translationFile")
        selected_our_translation = not current_translation or current_translation == "None"
        if selected_our_translation:
            opts.data["tac_translation.translationFile"] = "danbooru-jp.csv"
            changed = True

            # Only enable translation search automatically when this extension is the
            # one selecting the Japanese translation file. A user's custom translation
            # file and explicit search setting are otherwise left untouched.
            if opts.data.get("tac_translation.searchByTranslation") is not True:
                opts.data["tac_translation.searchByTranslation"] = True
                changed = True
        elif current_translation == "danbooru-jp.csv" and opts.data.get("tac_translation.searchByTranslation") is not True:
            # The user already selected our file, so enabling its search is a safe repair.
            opts.data["tac_translation.searchByTranslation"] = True
            changed = True

        if changed:
            opts.save(shared.config_filename)
            return "Tag Autocomplete の日本語検索設定も自動設定しました。"
        return None
    except Exception as exc:
        # Do not make DB update fail just because a Forge/WebUI fork changed option internals.
        return f"日本語検索の自動設定はスキップしました（{exc}）。"


def update_tagdb(
    configured_dir: str | None = None,
    force: bool = False,
    interval_days: int = DEFAULT_INTERVAL_DAYS,
    auto_configure: bool = True,
) -> UpdateResult:
    state = _load_state()
    target = find_tagcomplete_dir(configured_dir)
    now = time.time()

    if target is None:
        return UpdateResult(
            status="not_found",
            message="Tag Autocomplete の tags フォルダを検出できませんでした。",
            checked_at=now,
        )

    if not force and not should_check(state, interval_days):
        return UpdateResult(
            status="skipped",
            message="更新チェック間隔内のため、今回は確認しませんでした。",
            checked_at=now,
            source_fingerprint=str(state.get("source_fingerprint") or "") or None,
            tagcomplete_dir=str(target),
        )

    try:
        meta = fetch_meta()
        fingerprint = _meta_fingerprint(meta)
        previous = str(state.get("source_fingerprint") or "")
        state.update({
            "last_check_epoch": now,
            "last_check_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "source_fingerprint": fingerprint,
        })

        tag_dir = target / "tags"
        missing = [name for name in FILES if not (tag_dir / name).is_file()]
        if not force and previous == fingerprint and not missing:
            setting_note = _configure_tagcomplete_settings() if auto_configure else None
            _save_state(state)
            return UpdateResult(
                status="up_to_date",
                message="最新DBです（" + fingerprint + "）。" + ("\n" + setting_note if setting_note else ""),
                checked_at=now,
                source_fingerprint=fingerprint,
                tagcomplete_dir=str(target),
            )

        tag_dir.mkdir(parents=True, exist_ok=True)
        downloaded: dict[str, bytes] = {}
        for name in FILES:
            raw = _get_url(f"{SOURCE_BASE}/{name}")
            if not _looks_like_csv(name, raw):
                raise ValueError(f"{name} の内容をCSVとして検証できませんでした。")
            downloaded[name] = normalize_csv_for_tagcomplete(name, raw)

        temp_files: dict[str, Path] = {}
        for name, content in downloaded.items():
            destination = tag_dir / name
            temp = tag_dir / f".{name}.download"
            temp.write_bytes(content)
            temp_files[name] = temp

        backups: dict[str, Path] = {}
        replaced: list[str] = []
        try:
            for name in FILES:
                destination = tag_dir / name
                backup = tag_dir / f".{name}.backup"
                if destination.exists():
                    os.replace(destination, backup)
                    backups[name] = backup
                os.replace(temp_files[name], destination)
                replaced.append(name)
        except Exception:
            for name in reversed(replaced):
                destination = tag_dir / name
                try:
                    destination.unlink(missing_ok=True)
                except Exception:
                    pass
            for name, backup in backups.items():
                try:
                    os.replace(backup, tag_dir / name)
                except Exception:
                    pass
            for temp in temp_files.values():
                try:
                    temp.unlink(missing_ok=True)
                except Exception:
                    pass
            raise
        finally:
            for backup in backups.values():
                try:
                    backup.unlink(missing_ok=True)
                except Exception:
                    pass
            for temp in temp_files.values():
                try:
                    temp.unlink(missing_ok=True)
                except Exception:
                    pass

        state.update({
            "last_success_epoch": now,
            "last_success_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "source_fingerprint": fingerprint,
        })
        _save_state(state)

        setting_note = _configure_tagcomplete_settings() if auto_configure else None
        suffix = "\n" + setting_note if setting_note else ""
        return UpdateResult(
            status="updated",
            message=(
                f"DanbooruタグDBを更新しました（{fingerprint}）。\n"
                "Tag Autocompleteが新しいDBを確実に読み込むため、Forge Neoの再起動を推奨します。"
                f"{suffix}"
            ),
            changed=True,
            checked_at=now,
            source_fingerprint=fingerprint,
            tagcomplete_dir=str(target),
        )

    except Exception as exc:
        state["last_check_epoch"] = now
        state["last_error"] = str(exc)
        state["last_error_iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        try:
            _save_state(state)
        except Exception:
            pass
        return UpdateResult(
            status="error",
            message=f"更新に失敗しました。既存のタグDBは変更していません。\n{exc}",
            checked_at=now,
            source_fingerprint=str(state.get("source_fingerprint") or "") or None,
            tagcomplete_dir=str(target),
        )


def fetch_meta() -> dict[str, Any]:
    raw = _get_url(f"{SOURCE_BASE}/meta.json")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("meta.json is not an object")
    return data


def status_snapshot(configured_dir: str | None = None) -> dict[str, Any]:
    state = _load_state()
    target = find_tagcomplete_dir(configured_dir)
    return {
        "target": str(target) if target else "",
        "state": state,
    }
