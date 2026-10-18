from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from app.models import DownloadItem, DuplicateHit, DuplicateMatch

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"}
_PARENS = re.compile(r"[\(\[\{].*?[\)\]\}]")
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTISPACE = re.compile(r"\s+")

# path -> (built_at, keys set of normalized strings, path_by_key)
_cache: dict[str, tuple[float, dict[str, str]]] = {}
_CACHE_TTL = 60.0


def normalize_track_key(text: str) -> str:
    value = text.casefold().strip()
    value = _PARENS.sub(" ", value)
    value = _FEAT.sub(" ", value)
    value = value.replace("&", " and ")
    value = _NON_ALNUM.sub(" ", value)
    value = _MULTISPACE.sub(" ", value).strip()
    return value


def _keys_from_filename(path: Path) -> set[str]:
    stem = path.stem
    keys = {normalize_track_key(stem)}
    if " - " in stem:
        left, right = stem.split(" - ", 1)
        keys.add(normalize_track_key(right))
        keys.add(normalize_track_key(f"{left} {right}"))
        keys.add(normalize_track_key(f"{right} {left}"))
    return {k for k in keys if k}


def _keys_from_tags(path: Path) -> set[str]:
    try:
        from mutagen import File as MutagenFile  # type: ignore
    except ImportError:
        return set()

    try:
        audio = MutagenFile(path, easy=True)
    except Exception:  # noqa: BLE001
        return set()
    if not audio or not getattr(audio, "tags", None):
        return set()

    title = " ".join(audio.tags.get("title") or []).strip()
    artist = " ".join(audio.tags.get("artist") or []).strip()
    keys: set[str] = set()
    if title:
        keys.add(normalize_track_key(title))
    if artist and title:
        keys.add(normalize_track_key(f"{artist} - {title}"))
        keys.add(normalize_track_key(f"{artist} {title}"))
    return {k for k in keys if k}


def _index_directory(root: Path) -> dict[str, str]:
    """Map normalized key -> first matching file path."""
    index: dict[str, str] = {}
    if not root.exists() or not root.is_dir():
        return index

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
            continue
        for key in _keys_from_filename(path) | _keys_from_tags(path):
            index.setdefault(key, str(path))
    return index


def get_library_index(music_dir: Optional[str], always_include: Path) -> dict[str, str]:
    roots: list[Path] = []
    if music_dir and music_dir.strip():
        roots.append(Path(music_dir.strip()))
    roots.append(always_include)

    merged: dict[str, str] = {}
    now = time.monotonic()
    for root in roots:
        try:
            resolved = str(root.resolve())
        except OSError:
            continue
        cached = _cache.get(resolved)
        if cached and now - cached[0] < _CACHE_TTL:
            index = cached[1]
        else:
            index = _index_directory(Path(resolved))
            _cache[resolved] = (now, index)
        for key, path in index.items():
            merged.setdefault(key, path)
    return merged


def _candidate_keys(item: DownloadItem) -> set[str]:
    keys: set[str] = set()
    title = (item.title or "").strip()
    if title:
        keys |= _keys_from_filename(Path(title + ".mp3"))
        keys.add(normalize_track_key(title))
    return {k for k in keys if k}


def _resolve_title(item: DownloadItem) -> DownloadItem:
    if item.title and item.title.strip():
        return item
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(item.url, download=False)
        title = (info or {}).get("title")
        artist = (info or {}).get("artist") or (info or {}).get("uploader")
        if title and artist:
            return DownloadItem(url=item.url, title=f"{artist} - {title}")
        if title:
            return DownloadItem(url=item.url, title=title)
    except Exception:  # noqa: BLE001
        pass
    return item


def find_duplicates(
    items: list[DownloadItem],
    music_dir: Optional[str],
    downloads_dir: Path,
) -> list[DuplicateMatch]:
    index = get_library_index(music_dir, downloads_dir)
    if not index:
        return []

    matches: list[DuplicateMatch] = []
    for raw in items:
        item = _resolve_title(raw)
        keys = _candidate_keys(item)
        if not keys:
            continue
        hit_path = None
        hit_key = None
        for key in keys:
            if key in index:
                hit_path = index[key]
                hit_key = key
                break
        if hit_path:
            matches.append(
                DuplicateMatch(
                    url=item.url,
                    title=item.title,
                    existing=DuplicateHit(path=hit_path, matched_key=hit_key or ""),
                )
            )
    return matches
