from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STATE_PATH = DATA_DIR / "state.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "concurrency": 3,
    "searchResultCount": 5,
    "playlistSubfolder": True,
    "filenameTemplate": "Artist - Title",
    "embedMetadata": True,
    "audioBitrate": 320,
    "musicDir": r"D:\music",
    "cookieFile": "",
    "cookiesFromBrowser": "",
    "checkDuplicates": True,
    "syncIntervalDays": 7,
}

_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "settings": deepcopy(DEFAULT_SETTINGS),
        "playlists": [],
        "syncQueue": [],
        "lastGlobalSyncAt": None,
    }


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_state(raw: dict[str, Any]) -> dict[str, Any]:
    base = _default_state()
    settings = {**DEFAULT_SETTINGS, **(raw.get("settings") or {})}
    base["settings"] = settings
    base["playlists"] = list(raw.get("playlists") or [])
    base["syncQueue"] = list(raw.get("syncQueue") or [])
    base["lastGlobalSyncAt"] = raw.get("lastGlobalSyncAt")
    return base


def load_state() -> dict[str, Any]:
    with _lock:
        ensure_data_dir()
        if not STATE_PATH.is_file():
            state = _default_state()
            _write_unlocked(state)
            return deepcopy(state)
        try:
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("state root must be object")
            return _normalize_state(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            state = _default_state()
            _write_unlocked(state)
            return deepcopy(state)


def _write_unlocked(state: dict[str, Any]) -> None:
    ensure_data_dir()
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(STATE_PATH)


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        normalized = _normalize_state(state)
        _write_unlocked(normalized)
        return deepcopy(normalized)


def get_settings() -> dict[str, Any]:
    return deepcopy(load_state()["settings"])


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        state = load_state()
        merged = {**DEFAULT_SETTINGS, **state["settings"], **patch}
        # Keep only known keys
        state["settings"] = {k: merged[k] for k in DEFAULT_SETTINGS}
        _write_unlocked(state)
        return deepcopy(state["settings"])


def list_playlists() -> list[dict[str, Any]]:
    return deepcopy(load_state()["playlists"])


def add_playlist(
    *,
    url: str,
    title: str,
    source: str,
) -> dict[str, Any]:
    with _lock:
        state = load_state()
        for existing in state["playlists"]:
            if (existing.get("url") or "").strip() == url.strip():
                return deepcopy(existing)
        entry = {
            "id": str(uuid.uuid4()),
            "url": url.strip(),
            "title": title or "Playlist",
            "source": source,
            "addedAt": _utc_now(),
            "lastSyncedAt": None,
        }
        state["playlists"].append(entry)
        _write_unlocked(state)
        return deepcopy(entry)


def delete_playlist(playlist_id: str) -> bool:
    with _lock:
        state = load_state()
        before = len(state["playlists"])
        state["playlists"] = [p for p in state["playlists"] if p.get("id") != playlist_id]
        if len(state["playlists"]) == before:
            return False
        state["syncQueue"] = [
            q for q in state["syncQueue"] if q.get("playlistId") != playlist_id
        ]
        _write_unlocked(state)
        return True


def get_playlist(playlist_id: str) -> Optional[dict[str, Any]]:
    for p in load_state()["playlists"]:
        if p.get("id") == playlist_id:
            return deepcopy(p)
    return None


def update_playlist(playlist_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    with _lock:
        data = load_state()
        for p in data["playlists"]:
            if p.get("id") != playlist_id:
                continue
            for key, value in fields.items():
                if key in {"title", "url", "source", "lastSyncedAt"}:
                    p[key] = value
            _write_unlocked(data)
            return deepcopy(p)
        return None


def mark_playlists_synced(playlist_ids: list[str], when: Optional[str] = None) -> None:
    stamp = when or _utc_now()
    id_set = set(playlist_ids)
    with _lock:
        state = load_state()
        for p in state["playlists"]:
            if p.get("id") in id_set:
                p["lastSyncedAt"] = stamp
        state["lastGlobalSyncAt"] = stamp
        _write_unlocked(state)


def get_sync_queue() -> list[dict[str, Any]]:
    return deepcopy(load_state()["syncQueue"])


def set_sync_queue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with _lock:
        state = load_state()
        state["syncQueue"] = items
        _write_unlocked(state)
        return deepcopy(items)


def merge_sync_queue(new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append missing tracks; skip duplicates by url already in queue."""
    with _lock:
        state = load_state()
        existing_urls = {(q.get("url") or "").strip() for q in state["syncQueue"]}
        for item in new_items:
            url = (item.get("url") or "").strip()
            if not url or url in existing_urls:
                continue
            entry = {
                "id": item.get("id") or str(uuid.uuid4()),
                "playlistId": item.get("playlistId"),
                "playlistTitle": item.get("playlistTitle") or "",
                "title": item.get("title") or "",
                "artists": item.get("artists") or "",
                "url": url,
                "status": item.get("status") or "pending",
            }
            state["syncQueue"].append(entry)
            existing_urls.add(url)
        _write_unlocked(state)
        return deepcopy(state["syncQueue"])


def clear_sync_queue(ids: Optional[list[str]] = None) -> list[dict[str, Any]]:
    with _lock:
        state = load_state()
        if ids is None:
            state["syncQueue"] = []
        else:
            id_set = set(ids)
            state["syncQueue"] = [q for q in state["syncQueue"] if q.get("id") not in id_set]
        _write_unlocked(state)
        return deepcopy(state["syncQueue"])


def remove_sync_queue_by_urls(urls: list[str]) -> list[dict[str, Any]]:
    url_set = {u.strip() for u in urls if u and u.strip()}
    with _lock:
        state = load_state()
        state["syncQueue"] = [
            q for q in state["syncQueue"] if (q.get("url") or "").strip() not in url_set
        ]
        _write_unlocked(state)
        return deepcopy(state["syncQueue"])
