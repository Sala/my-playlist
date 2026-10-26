from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    queries: list[str] = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    cookiefile: Optional[str] = None
    cookies_from_browser: Optional[str] = None


class Candidate(BaseModel):
    id: str
    title: str
    channel: str = ""
    duration: Optional[int] = None
    url: str


class QueryResult(BaseModel):
    query: str
    candidates: list[Candidate]
    error: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[QueryResult]


class PlaylistRequest(BaseModel):
    url: str = Field(..., min_length=1)
    cookiefile: Optional[str] = None
    cookies_from_browser: Optional[str] = None


class PlaylistEntry(BaseModel):
    id: str
    title: str
    channel: str = ""
    duration: Optional[int] = None
    url: str
    index: int


class PlaylistResponse(BaseModel):
    title: str
    entries: list[PlaylistEntry]


class DownloadItem(BaseModel):
    url: str = Field(..., min_length=1)
    title: Optional[str] = None


class DownloadRequest(BaseModel):
    items: list[DownloadItem] = Field(..., min_length=1)
    output_subdir: Optional[str] = None
    concurrency: int = Field(default=3, ge=1, le=10)
    embed_metadata: bool = True
    audio_bitrate: int = Field(default=320, ge=64, le=320)
    filename_template: str = "Artist - Title"
    cookiefile: Optional[str] = None
    cookies_from_browser: Optional[str] = None


class ItemStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    done = "done"
    failed = "failed"


class JobItemStatus(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    status: ItemStatus = ItemStatus.queued
    progress: float = 0.0
    error: Optional[str] = None
    filename: Optional[str] = None


class JobStatus(str, Enum):
    running = "running"
    done = "done"
    failed = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    items: list[JobItemStatus]


class DownloadStartResponse(BaseModel):
    job_id: str


class CheckDuplicatesRequest(BaseModel):
    items: list[DownloadItem] = Field(..., min_length=1)
    music_dir: Optional[str] = None


class DuplicateHit(BaseModel):
    path: str
    matched_key: str = ""


class DuplicateMatch(BaseModel):
    url: str
    title: Optional[str] = None
    existing: DuplicateHit


class CheckDuplicatesResponse(BaseModel):
    duplicates: list[DuplicateMatch]
    checked: int


class FsEntry(BaseModel):
    name: str
    path: str
    is_dir: bool = True


class FsListResponse(BaseModel):
    path: str
    parent: Optional[str] = None
    entries: list[FsEntry]


class AppSettings(BaseModel):
    concurrency: int = Field(default=3, ge=1, le=10)
    searchResultCount: int = Field(default=5, ge=1, le=20)
    playlistSubfolder: bool = True
    filenameTemplate: str = "Artist - Title"
    embedMetadata: bool = True
    audioBitrate: int = Field(default=320, ge=64, le=320)
    musicDir: str = r"D:\music"
    cookieFile: str = ""
    cookiesFromBrowser: str = ""
    checkDuplicates: bool = True
    syncIntervalDays: int = Field(default=7, ge=1, le=365)


class SavedPlaylist(BaseModel):
    id: str
    url: str
    title: str
    source: str
    addedAt: str
    lastSyncedAt: Optional[str] = None


class AddPlaylistRequest(BaseModel):
    url: str = Field(..., min_length=1)
    cookiefile: Optional[str] = None
    cookies_from_browser: Optional[str] = None


class SyncQueueItem(BaseModel):
    id: str
    playlistId: Optional[str] = None
    playlistTitle: str = ""
    title: str = ""
    artists: str = ""
    url: str
    status: str = "pending"


class SyncPlaylistsRequest(BaseModel):
    playlistIds: Optional[list[str]] = None
    onlyDue: bool = False
    cookiefile: Optional[str] = None
    cookies_from_browser: Optional[str] = None


class SyncPlaylistsResponse(BaseModel):
    synced: list[str]
    missingCount: int
    queue: list[SyncQueueItem]
    errors: list[dict[str, str]] = Field(default_factory=list)


class SyncStatusResponse(BaseModel):
    syncIntervalDays: int
    dueCount: int
    duePlaylistIds: list[str]
    queueCount: int
    playlistCount: int
    lastGlobalSyncAt: Optional[str] = None


class SyncDownloadRequest(BaseModel):
    all: bool = False
    ids: Optional[list[str]] = None
    cookiefile: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    concurrency: int = Field(default=3, ge=1, le=10)
    embed_metadata: bool = True
    audio_bitrate: int = Field(default=320, ge=64, le=320)
    filename_template: str = "Artist - Title"
    output_subdir: Optional[str] = None


class SyncDismissRequest(BaseModel):
    ids: Optional[list[str]] = None
    all: bool = False


class LibraryImportRequest(BaseModel):
    dryRun: bool = True
    musicDir: Optional[str] = None
    limit: int = Field(default=0, ge=0)


class LibraryImportResponse(BaseModel):
    dry_run: bool
    counts: dict[str, int]
    lines: list[str]
    report_path: Optional[str] = None
