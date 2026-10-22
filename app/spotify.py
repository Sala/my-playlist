from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.models import PlaylistEntry, PlaylistResponse

_PLAYLIST_ID = re.compile(
    r"(?:spotify:playlist:|open\.spotify\.com/(?:intl-[a-z]{2}/)?playlist/)([a-zA-Z0-9]+)"
)
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def is_spotify_playlist_url(url: str) -> bool:
    return bool(_PLAYLIST_ID.search(url or ""))


def extract_playlist_id(url: str) -> str:
    match = _PLAYLIST_ID.search(url or "")
    if not match:
        raise ValueError("Not a Spotify playlist URL")
    return match.group(1)


def _http_get(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise ValueError(f"Spotify embed HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach Spotify: {exc.reason}") from exc


def _dig_entity(data: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
        if isinstance(entity, dict):
            return entity
    except (KeyError, TypeError):
        pass
    raise ValueError(
        "Could not parse Spotify playlist (private, region-locked, or embed changed)"
    )


def _duration_ms_to_sec(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        ms = int(value)
        return max(0, ms // 1000)
    except (TypeError, ValueError):
        return None


def _track_id(uri_or_id: str, index: int) -> str:
    raw = (uri_or_id or "").strip()
    if raw.startswith("spotify:track:"):
        return raw.split(":")[-1]
    if raw:
        return raw
    return f"spotify-{index}"


def _search_url(artists: str, title: str) -> str:
    artists = (artists or "").strip()
    title = (title or "").strip() or "Unknown"
    if artists:
        query = f"{artists} - {title}"
    else:
        query = title
    return f"ytsearch1:{query}"


def fetch_public_playlist(url: str) -> PlaylistResponse:
    playlist_id = extract_playlist_id(url)
    embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    html = _http_get(embed_url)
    match = _NEXT_DATA.search(html)
    if not match:
        raise ValueError("Spotify embed page missing playlist data")

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid Spotify embed JSON") from exc

    entity = _dig_entity(payload)
    title = entity.get("name") or entity.get("title") or "Spotify playlist"
    track_list = entity.get("trackList") or entity.get("tracks") or []
    if not isinstance(track_list, list) or not track_list:
        raise ValueError("Spotify playlist has no visible tracks (may be private)")

    entries: list[PlaylistEntry] = []
    for index, track in enumerate(track_list):
        if not isinstance(track, dict):
            continue
        song = (track.get("title") or track.get("name") or "").strip()
        artists = (track.get("subtitle") or track.get("artists") or "").strip()
        if isinstance(artists, list):
            artists = ", ".join(str(a) for a in artists if a)
        # Normalize weird spaces from embed
        artists = re.sub(r"\s+", " ", artists.replace("\xa0", " ")).strip()
        if not song and not artists:
            continue
        uri = track.get("uri") or track.get("id") or ""
        display_title = f"{artists} - {song}" if artists else song
        entries.append(
            PlaylistEntry(
                id=_track_id(str(uri), index),
                title=display_title,
                channel=artists,
                duration=_duration_ms_to_sec(track.get("duration")),
                url=_search_url(artists, song),
                index=index,
            )
        )

    if not entries:
        raise ValueError("No usable tracks found in Spotify playlist")

    return PlaylistResponse(title=str(title), entries=entries)


def looks_like_spotify_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    return "spotify.com" in host or url.strip().lower().startswith("spotify:")
