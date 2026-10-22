from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import yt_dlp

from app import spotify
from app.models import (
    Candidate,
    DownloadItem,
    ItemStatus,
    JobItemStatus,
    JobResponse,
    JobStatus,
    PlaylistEntry,
    PlaylistResponse,
    QueryResult,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = ROOT_DIR / "downloads"


def _find_ffmpeg_location() -> Optional[str]:
    """Return a directory containing ffmpeg, if found."""
    which = shutil.which("ffmpeg")
    if which:
        return str(Path(which).resolve().parent)

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Packages",
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        if (path / "ffmpeg.exe").exists() or (path / "ffmpeg").exists():
            return str(path)
        for match in path.rglob("ffmpeg.exe"):
            return str(match.parent)
    return None


_FFMPEG_LOCATION = _find_ffmpeg_location()

_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_jobs: dict[str, JobResponse] = {}
_jobs_lock = threading.Lock()


def _sanitize_filename(name: str, fallback: str = "track") -> str:
    cleaned = _INVALID_FS.sub("", name).strip(" .")
    return cleaned[:180] if cleaned else fallback


def _format_duration(seconds: Optional[int]) -> Optional[int]:
    if seconds is None:
        return None
    try:
        return int(seconds)
    except (TypeError, ValueError):
        return None


def _candidate_from_info(info: dict[str, Any]) -> Candidate:
    video_id = info.get("id") or ""
    url = info.get("webpage_url") or info.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    return Candidate(
        id=video_id,
        title=info.get("title") or "Untitled",
        channel=info.get("channel") or info.get("uploader") or "",
        duration=_format_duration(info.get("duration")),
        url=url,
    )


def _apply_cookiefile(opts: dict[str, Any], cookiefile: Optional[str]) -> None:
    if not cookiefile:
        return
    path = Path(cookiefile)
    if path.is_file():
        opts["cookiefile"] = str(path)


def _ydl_base_opts(
    *,
    cookiefile: Optional[str] = None,
    skip_download: bool = False,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Helps with many 403 / SABR issues on YouTube
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "android_sdkless", "web"],
            }
        },
        "retries": 5,
        "fragment_retries": 5,
    }
    if skip_download:
        opts["skip_download"] = True
    _apply_cookiefile(opts, cookiefile)
    if _FFMPEG_LOCATION:
        opts["ffmpeg_location"] = _FFMPEG_LOCATION
    return opts


def search_queries(
    queries: list[str],
    limit: int = 5,
    cookiefile: Optional[str] = None,
) -> list[QueryResult]:
    results: list[QueryResult] = []
    ydl_opts = _ydl_base_opts(cookiefile=cookiefile, skip_download=True)
    ydl_opts["extract_flat"] = False

    for raw in queries:
        query = raw.strip()
        if not query:
            continue
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            entries = data.get("entries") or []
            candidates = [_candidate_from_info(e) for e in entries if e]
            results.append(QueryResult(query=query, candidates=candidates))
        except Exception as exc:  # noqa: BLE001
            results.append(QueryResult(query=query, candidates=[], error=str(exc)))
    return results


def fetch_playlist(url: str, cookiefile: Optional[str] = None) -> PlaylistResponse:
    cleaned = (url or "").strip()
    if spotify.is_spotify_playlist_url(cleaned) or spotify.looks_like_spotify_host(cleaned):
        return spotify.fetch_public_playlist(cleaned)

    ydl_opts = _ydl_base_opts(cookiefile=cookiefile, skip_download=True)
    ydl_opts["extract_flat"] = "in_playlist"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(cleaned, download=False)

    if not data:
        raise ValueError("Could not load playlist")

    title = data.get("title") or "playlist"
    raw_entries = data.get("entries") or []
    entries: list[PlaylistEntry] = []

    for index, entry in enumerate(raw_entries):
        if not entry:
            continue
        video_id = entry.get("id") or ""
        if not video_id:
            continue
        webpage = entry.get("url") or entry.get("webpage_url")
        if webpage and not str(webpage).startswith("http"):
            webpage = f"https://www.youtube.com/watch?v={video_id}"
        elif not webpage:
            webpage = f"https://www.youtube.com/watch?v={video_id}"
        entries.append(
            PlaylistEntry(
                id=video_id,
                title=entry.get("title") or f"Track {index + 1}",
                channel=entry.get("channel") or entry.get("uploader") or "",
                duration=_format_duration(entry.get("duration")),
                url=webpage,
                index=index,
            )
        )

    return PlaylistResponse(title=title, entries=entries)


def _search_query_for_item(item: JobItemStatus) -> Optional[str]:
    title = (item.title or "").strip()
    url = (item.url or "").strip()
    if url.lower().startswith("ytsearch1:"):
        q = url.split(":", 1)[1].strip()
        if q:
            return q
    if title:
        return title
    return None


def _fallback_search_url(item: JobItemStatus) -> Optional[str]:
    query = _search_query_for_item(item)
    if not query:
        return None
    primary = (item.url or "").strip()
    candidate = f"ytsearch1:{query}"
    if primary.lower() == candidate.lower():
        return None
    if primary.lower().startswith("ytsearch1:") and primary.split(":", 1)[1].strip().lower() == query.lower():
        return None
    return candidate


def _output_template(subdir: Optional[str], filename_template: str) -> str:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    base = DOWNLOADS_DIR
    if subdir:
        base = DOWNLOADS_DIR / _sanitize_filename(subdir, "playlist")
        base.mkdir(parents=True, exist_ok=True)

    if filename_template.strip().lower() in {"artist - title", "artist-title"}:
        pattern = "%(artist,uploader,channel)s - %(title)s.%(ext)s"
    elif filename_template.strip().lower() == "title":
        pattern = "%(title)s.%(ext)s"
    else:
        pattern = "%(artist,uploader,channel)s - %(title)s.%(ext)s"

    return str(base / pattern)


def _progress_hook(job_id: str, item_id: str):
    def hook(d: dict[str, Any]) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            item = next((i for i in job.items if i.id == item_id), None)
            if not item:
                return
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total:
                    item.progress = round(min(99.0, (downloaded / total) * 100), 1)
                item.status = ItemStatus.downloading
            elif d.get("status") == "finished":
                item.progress = 99.0
                item.status = ItemStatus.downloading

    return hook


def _download_one(
    job_id: str,
    item: JobItemStatus,
    outtmpl: str,
    embed_metadata: bool,
    audio_bitrate: int,
    cookiefile: Optional[str],
) -> None:
    with _jobs_lock:
        item.status = ItemStatus.downloading
        item.progress = 0.0
        item.error = None

    postprocessors = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(audio_bitrate),
        }
    ]
    if embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})

    ydl_opts = _ydl_base_opts(cookiefile=cookiefile)
    ydl_opts.update(
        {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "progress_hooks": [_progress_hook(job_id, item.id)],
            "postprocessors": postprocessors,
            "prefer_ffmpeg": True,
            "keepvideo": False,
        }
    )

    def _run_extract(source: str) -> tuple[Optional[str], Optional[str]]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source, download=True)
            filename = None
            title = None
            if info:
                # ytsearch results may nest the real entry
                if info.get("_type") == "playlist" and info.get("entries"):
                    info = next((e for e in info["entries"] if e), info)
                prepared = ydl.prepare_filename(info)
                path = Path(prepared)
                mp3_path = path.with_suffix(".mp3")
                if mp3_path.exists():
                    filename = str(mp3_path)
                elif path.exists():
                    filename = str(path)
                else:
                    filename = str(mp3_path)
                title = info.get("title")
            return filename, title

    primary_error: Optional[str] = None
    try:
        filename, title = _run_extract(item.url)
        with _jobs_lock:
            item.status = ItemStatus.done
            item.progress = 100.0
            item.filename = filename
            item.error = None
            if title and not item.title:
                item.title = title
        return
    except Exception as exc:  # noqa: BLE001
        primary_error = str(exc)

    fallback = _fallback_search_url(item)
    if not fallback:
        with _jobs_lock:
            item.status = ItemStatus.failed
            item.error = primary_error
            item.progress = 0.0
        return

    try:
        with _jobs_lock:
            item.status = ItemStatus.downloading
            item.progress = 0.0
            item.error = f"Primary failed; searching: {fallback.removeprefix('ytsearch1:')}"
        filename, title = _run_extract(fallback)
        with _jobs_lock:
            item.status = ItemStatus.done
            item.progress = 100.0
            item.filename = filename
            item.error = None
            if title:
                item.title = item.title or title
            item.url = fallback
    except Exception as exc:  # noqa: BLE001
        with _jobs_lock:
            item.status = ItemStatus.failed
            item.error = f"{primary_error} | search fallback: {exc}"
            item.progress = 0.0


def _run_job(
    job_id: str,
    output_subdir: Optional[str],
    concurrency: int,
    embed_metadata: bool,
    audio_bitrate: int,
    filename_template: str,
    cookiefile: Optional[str],
) -> None:
    outtmpl = _output_template(output_subdir, filename_template)

    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job_items = list(job.items)

    workers = max(1, min(concurrency, len(job_items)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _download_one,
                job_id,
                job_item,
                outtmpl,
                embed_metadata,
                audio_bitrate,
                cookiefile,
            )
            for job_item in job_items
        ]
        for future in futures:
            future.result()

    with _jobs_lock:
        job = _jobs[job_id]
        if all(i.status == ItemStatus.failed for i in job.items):
            job.status = JobStatus.failed
        else:
            job.status = JobStatus.done


def start_download_job(
    items: list[DownloadItem],
    output_subdir: Optional[str] = None,
    concurrency: int = 3,
    embed_metadata: bool = True,
    audio_bitrate: int = 320,
    filename_template: str = "Artist - Title",
    cookiefile: Optional[str] = None,
) -> str:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = JobResponse(
            job_id=job_id,
            status=JobStatus.running,
            items=[
                JobItemStatus(id=str(uuid.uuid4()), url=it.url, title=it.title)
                for it in items
            ],
        )
    thread = threading.Thread(
        target=_run_job,
        args=(
            job_id,
            output_subdir,
            concurrency,
            embed_metadata,
            audio_bitrate,
            filename_template,
            cookiefile,
        ),
        daemon=True,
    )
    thread.start()
    return job_id


def get_job(job_id: str) -> Optional[JobResponse]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return JobResponse.model_validate(job.model_dump())
