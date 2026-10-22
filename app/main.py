from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import downloader, fsbrowser, library
from app.models import (
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
    DownloadRequest,
    DownloadStartResponse,
    FsListResponse,
    JobResponse,
    PlaylistRequest,
    PlaylistResponse,
    SearchRequest,
    SearchResponse,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
DOWNLOADS_DIR = ROOT_DIR / "downloads"

app = FastAPI(title="My Playlist", docs_url=None, redoc_url=None)


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
    if job is None:
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
