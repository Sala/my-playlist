from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app import downloader, library, spotify, state
from app.models import DownloadItem


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def playlist_is_due(playlist: dict[str, Any], interval_days: int, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    last = _parse_iso(playlist.get("lastSyncedAt"))
    if last is None:
        return True
    days = max(1, int(interval_days or 7))
    return (now - last).total_seconds() >= days * 86400


def detect_source(url: str) -> str:
    cleaned = (url or "").strip()
    if spotify.is_spotify_playlist_url(cleaned) or spotify.looks_like_spotify_host(cleaned):
        return "spotify"
    return "youtube"


def sync_status() -> dict[str, Any]:
    settings = state.get_settings()
    interval = int(settings.get("syncIntervalDays") or 7)
    playlists = state.list_playlists()
    due = [p for p in playlists if playlist_is_due(p, interval)]
    queue = state.get_sync_queue()
    return {
        "syncIntervalDays": interval,
        "dueCount": len(due),
        "duePlaylistIds": [p["id"] for p in due],
        "queueCount": len(queue),
        "playlistCount": len(playlists),
        "lastGlobalSyncAt": state.load_state().get("lastGlobalSyncAt"),
    }


def _display_title(entry_title: str, channel: str) -> str:
    title = (entry_title or "").strip()
    artists = (channel or "").strip()
    if artists and title and not title.lower().startswith(artists.lower()):
        return f"{artists} - {title}"
    return title or artists or "Unknown"


def find_missing_entries(
    entries: list[Any],
    music_dir: Optional[str],
    downloads_dir: Path,
) -> list[Any]:
    items = [
        DownloadItem(
            url=e.url,
            title=_display_title(getattr(e, "title", "") or "", getattr(e, "channel", "") or ""),
        )
        for e in entries
    ]
    duplicates = library.find_duplicates(
        items=items,
        music_dir=music_dir,
        downloads_dir=downloads_dir,
    )
    dup_urls = {d.url for d in duplicates}
    return [e for e, item in zip(entries, items) if item.url not in dup_urls]


def sync_playlists(
    *,
    playlist_ids: Optional[list[str]],
    downloads_dir: Path,
    cookiefile: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    only_due: bool = False,
) -> dict[str, Any]:
    settings = state.get_settings()
    interval = int(settings.get("syncIntervalDays") or 7)
    music_dir = (settings.get("musicDir") or "").strip() or None

    playlists = state.list_playlists()
    if playlist_ids:
        id_set = set(playlist_ids)
        targets = [p for p in playlists if p.get("id") in id_set]
    elif only_due:
        targets = [p for p in playlists if playlist_is_due(p, interval)]
    else:
        targets = list(playlists)

    if not targets:
        return {
            "synced": [],
            "missingCount": 0,
            "queue": state.get_sync_queue(),
            "errors": [],
        }

    new_queue_items: list[dict[str, Any]] = []
    synced_ids: list[str] = []
    errors: list[dict[str, str]] = []
    missing_total = 0

    for pl in targets:
        url = (pl.get("url") or "").strip()
        if not url:
            errors.append({"playlistId": pl.get("id") or "", "error": "Missing URL"})
            continue
        try:
            response = downloader.fetch_playlist(
                url,
                cookiefile=cookiefile,
                cookies_from_browser=cookies_from_browser,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"playlistId": pl.get("id") or "", "error": str(exc)})
            continue

        # Refresh title if we got a better one
        if response.title and response.title != pl.get("title"):
            state.update_playlist(pl["id"], title=response.title)

        missing = find_missing_entries(response.entries, music_dir, downloads_dir)
        missing_total += len(missing)
        for entry in missing:
            artists = (entry.channel or "").strip()
            title = (entry.title or "").strip()
            new_queue_items.append(
                {
                    "playlistId": pl["id"],
                    "playlistTitle": response.title or pl.get("title") or "",
                    "title": title,
                    "artists": artists,
                    "url": entry.url,
                    "status": "pending",
                }
            )
        synced_ids.append(pl["id"])

    if synced_ids:
        state.mark_playlists_synced(synced_ids)
    queue = state.merge_sync_queue(new_queue_items) if new_queue_items else state.get_sync_queue()

    return {
        "synced": synced_ids,
        "missingCount": missing_total,
        "queue": queue,
        "errors": errors,
    }

