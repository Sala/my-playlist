from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import downloader, fsbrowser, import_library, library, state, sync
from app.models import (
    AddPlaylistRequest,
    AppSettings,
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
    DownloadItem,
    DownloadRequest,
    DownloadStartResponse,
    FsListResponse,
    JobResponse,
    LibraryImportRequest,
    LibraryImportResponse,
    PlaylistRequest,
    PlaylistResponse,
    SavedPlaylist,
    SearchRequest,
    SearchResponse,
    SyncDismissRequest,
    SyncDownloadRequest,
    SyncPlaylistsRequest,
    SyncPlaylistsResponse,
    SyncQueueItem,
    SyncStatusResponse,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
DOWNLOADS_DIR = ROOT_DIR / "downloads"

app = FastAPI(title="My Playlist", docs_url=None, redoc_url=None)

# Ensure state file exists on startup
state.ensure_data_dir()
state.load_state()


def _validate_cookiefile(cookiefile: Optional[str]) -> Optional[str]:
    if not cookiefile:
        return None
    path = Path(cookiefile)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Cookie file not found: {cookiefile}")
    return str(path)


def _validate_browser(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    key = name.strip().lower()
    allowed = {"chrome", "edge", "firefox", "brave", "chromium", "opera"}
    if key not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported browser for cookies: {name}. Use one of: {', '.join(sorted(allowed))}",
        )
    return key


@app.get("/api/settings", response_model=AppSettings)
def api_get_settings() -> AppSettings:
    return AppSettings(**state.get_settings())


@app.put("/api/settings", response_model=AppSettings)
def api_put_settings(body: AppSettings) -> AppSettings:
    updated = state.update_settings(body.model_dump())
    return AppSettings(**updated)


@app.get("/api/playlists", response_model=list[SavedPlaylist])
def api_list_playlists() -> list[SavedPlaylist]:
    return [SavedPlaylist(**p) for p in state.list_playlists()]


@app.post("/api/playlists", response_model=SavedPlaylist)
def api_add_playlist(body: AddPlaylistRequest) -> SavedPlaylist:
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    cookiefile = _validate_cookiefile(body.cookiefile)
    browser = _validate_browser(body.cookies_from_browser)
    try:
        fetched = downloader.fetch_playlist(
            url,
            cookiefile=cookiefile,
            cookies_from_browser=browser,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    source = sync.detect_source(url)
    entry = state.add_playlist(url=url, title=fetched.title or "Playlist", source=source)
    return SavedPlaylist(**entry)


@app.delete("/api/playlists/{playlist_id}")
def api_delete_playlist(playlist_id: str) -> dict:
    if not state.delete_playlist(playlist_id):
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"ok": True}


@app.get("/api/sync/status", response_model=SyncStatusResponse)
def api_sync_status() -> SyncStatusResponse:
    return SyncStatusResponse(**sync.sync_status())


@app.get("/api/sync/queue", response_model=list[SyncQueueItem])
def api_sync_queue() -> list[SyncQueueItem]:
    return [SyncQueueItem(**q) for q in state.get_sync_queue()]


@app.post("/api/playlists/sync", response_model=SyncPlaylistsResponse)
def api_sync_playlists(body: SyncPlaylistsRequest) -> SyncPlaylistsResponse:
    cookiefile = _validate_cookiefile(body.cookiefile)
    browser = _validate_browser(body.cookies_from_browser)
    result = sync.sync_playlists(
        playlist_ids=body.playlistIds,
        downloads_dir=DOWNLOADS_DIR,
        cookiefile=cookiefile,
        cookies_from_browser=browser,
        only_due=body.onlyDue,
    )
    return SyncPlaylistsResponse(
        synced=result["synced"],
        missingCount=result["missingCount"],
        queue=[SyncQueueItem(**q) for q in result["queue"]],
        errors=result["errors"],
    )


@app.post("/api/sync/download", response_model=DownloadStartResponse)
def api_sync_download(body: SyncDownloadRequest) -> DownloadStartResponse:
    queue = state.get_sync_queue()
    if body.all:
        selected = [q for q in queue if q.get("status") == "pending"]
    elif body.ids:
        id_set = set(body.ids)
        selected = [q for q in queue if q.get("id") in id_set]
    else:
        raise HTTPException(status_code=400, detail="Provide all=true or ids")

    if not selected:
        raise HTTPException(status_code=400, detail="No queue items to download")

    cookiefile = _validate_cookiefile(body.cookiefile)
    browser = _validate_browser(body.cookies_from_browser)
    items = [
        DownloadItem(
            url=q["url"],
            title=_queue_item_title(q),
        )
        for q in selected
    ]
    settings = state.get_settings()
    subdir = body.output_subdir
    if subdir is None and settings.get("playlistSubfolder"):
        # Prefer first playlist title if all same
        titles = {q.get("playlistTitle") or "" for q in selected}
        titles.discard("")
        if len(titles) == 1:
            subdir = next(iter(titles))

    job_id = downloader.start_download_job(
        items=items,
        output_subdir=subdir,
        concurrency=body.concurrency,
        embed_metadata=body.embed_metadata,
        audio_bitrate=body.audio_bitrate,
        filename_template=body.filename_template,
        cookiefile=cookiefile,
        cookies_from_browser=browser,
    )
    state.remove_sync_queue_by_urls([q["url"] for q in selected])
    return DownloadStartResponse(job_id=job_id)


@app.post("/api/sync/dismiss")
def api_sync_dismiss(body: SyncDismissRequest) -> dict:
    if body.all:
        state.clear_sync_queue()
    elif body.ids:
        state.clear_sync_queue(body.ids)
    else:
        raise HTTPException(status_code=400, detail="Provide all=true or ids")
    return {"ok": True, "queue": state.get_sync_queue()}


def _queue_item_title(q: dict) -> str:
    artists = (q.get("artists") or "").strip()
    title = (q.get("title") or "").strip()
    if artists and title:
        return f"{artists} - {title}"
    return title or artists or q.get("url") or "track"


@app.post("/api/library/import", response_model=LibraryImportResponse)
def api_library_import(body: LibraryImportRequest) -> LibraryImportResponse:
    settings = state.get_settings()
    music_dir = (body.musicDir or settings.get("musicDir") or "").strip()
    if not music_dir:
        raise HTTPException(status_code=400, detail="Music library folder not set")
    music_path = Path(music_dir)
    if not music_path.exists() or not music_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Music library folder not found: {music_dir}")
    try:
        result = import_library.run_import(
            DOWNLOADS_DIR,
            music_path,
            apply=not body.dryRun,
            limit=body.limit or 0,
            quiet=True,
            write_report=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return LibraryImportResponse(**result)


@app.post("/api/search", response_model=SearchResponse)
def api_search(body: SearchRequest) -> SearchResponse:
    queries = [q.strip() for q in body.queries if q.strip()]
    if not queries:
        raise HTTPException(status_code=400, detail="No queries provided")
    cookiefile = _validate_cookiefile(body.cookiefile)
    browser = _validate_browser(body.cookies_from_browser)
    results = downloader.search_queries(
        queries,
        limit=body.limit,
        cookiefile=cookiefile,
        cookies_from_browser=browser,
    )
    return SearchResponse(results=results)


@app.post("/api/playlist", response_model=PlaylistResponse)
def api_playlist(body: PlaylistRequest) -> PlaylistResponse:
    cookiefile = _validate_cookiefile(body.cookiefile)
    browser = _validate_browser(body.cookies_from_browser)
    try:
        return downloader.fetch_playlist(
            body.url.strip(),
            cookiefile=cookiefile,
            cookies_from_browser=browser,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/check-duplicates", response_model=CheckDuplicatesResponse)
def api_check_duplicates(body: CheckDuplicatesRequest) -> CheckDuplicatesResponse:
    if body.music_dir:
        music_path = Path(body.music_dir)
        if not music_path.exists() or not music_path.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"Music library folder not found: {body.music_dir}",
            )
    duplicates = library.find_duplicates(
        items=body.items,
        music_dir=body.music_dir,
        downloads_dir=DOWNLOADS_DIR,
    )
    return CheckDuplicatesResponse(duplicates=duplicates, checked=len(body.items))


@app.post("/api/download", response_model=DownloadStartResponse)
def api_download(body: DownloadRequest) -> DownloadStartResponse:
    cookiefile = _validate_cookiefile(body.cookiefile)
    browser = _validate_browser(body.cookies_from_browser)
    job_id = downloader.start_download_job(
        items=body.items,
        output_subdir=body.output_subdir,
        concurrency=body.concurrency,
        embed_metadata=body.embed_metadata,
        audio_bitrate=body.audio_bitrate,
        filename_template=body.filename_template,
        cookiefile=cookiefile,
        cookies_from_browser=browser,
    )
    return DownloadStartResponse(job_id=job_id)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def api_job(job_id: str) -> JobResponse:
    job = downloader.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/fs/roots", response_model=FsListResponse)
def api_fs_roots() -> FsListResponse:
    return fsbrowser.list_roots()


@app.get("/api/fs/list", response_model=FsListResponse)
def api_fs_list(
    path: str = Query(..., min_length=1),
    include_files: bool = Query(False),
    file_ext: Optional[str] = Query(None),
) -> FsListResponse:
    try:
        return fsbrowser.list_dir(path, include_files=include_files, file_ext=file_ext)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
