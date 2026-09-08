from __future__ import annotations

import json
import os
import re
import time
import urllib.error
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
    # When running under WebUI, this is normally the executable working tree.
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

    # Prefer the canonical upstream directory name.
    candidates.sort(key=lambda p: (p.name.lower() != "a1111-sd-webui-tagcomplete", p.name.lower()))
    return candidates[0].resolve()


def _get_url(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "a1111-danbooru-tagdb-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _looks_like_csv(name: str, content: bytes) -> bool:
    if len(content) < MIN_CSV_BYTES:
        return False
    # Avoid writing an HTML error page or GitHub error body as a CSV.
    text = content[:2000].decode("utf-8", errors="ignore")
    if "<html" in text.lower() or "<!doctype" in text.lower():
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        return False
    if name == "danbooru-jp.csv":
        return any("," in line for line in lines[:5])
    return any("," in line for line in lines[:5])


def fetch_meta() -> dict[str, Any]:
    raw = _get_url(f"{SOURCE_BASE}/meta.json")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("meta.json is not an object")
    return data


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


def update_tagdb(
    configured_dir: str | None = None,
    force: bool = False,
    interval_days: int = DEFAULT_INTERVAL_DAYS,
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

        # Same source snapshot: no need to re-download unless forced and files are missing.
        tag_dir = target / "tags"
        missing = [name for name in FILES if not (tag_dir / name).is_file()]
        if not force and previous == fingerprint and not missing:
            _save_state(state)
            return UpdateResult(
                status="up_to_date",
                message=f"最新DBです（{fingerprint}）。",
                checked_at=now,
                source_fingerprint=fingerprint,
                tagcomplete_dir=str(target),
            )

        tag_dir.mkdir(parents=True, exist_ok=True)
        downloaded: dict[str, bytes] = {}
        for name in FILES:
            content = _get_url(f"{SOURCE_BASE}/{name}")
            if not _looks_like_csv(name, content):
                raise ValueError(f"{name} の内容をCSVとして検証できませんでした。")
            downloaded[name] = content

        # Prepare every temporary file first. Then swap them in, keeping a backup
        # so a partial disk failure can be rolled back without losing the old DB.
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

        return UpdateResult(
            status="updated",
            message=f"DanbooruタグDBを更新しました（{fingerprint}）。WebUIの再起動を推奨します。",
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


def status_snapshot(configured_dir: str | None = None) -> dict[str, Any]:
    state = _load_state()
    target = find_tagcomplete_dir(configured_dir)
    return {
        "target": str(target) if target else "",
        "state": state,
    }
