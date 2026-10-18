from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    queries: list[str] = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    cookiefile: Optional[str] = None


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
