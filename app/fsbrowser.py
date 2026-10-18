from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Optional

from app.models import FsEntry, FsListResponse


def list_roots() -> FsListResponse:
    roots: list[FsEntry] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(FsEntry(name=f"{letter}:\\", path=str(drive), is_dir=True))
    else:
        home = Path.home()
        roots.append(FsEntry(name=home.name or str(home), path=str(home), is_dir=True))
        roots.append(FsEntry(name="/", path="/", is_dir=True))
    return FsListResponse(path="", parent=None, entries=roots)


def list_dir(
    path: str,
    *,
    include_files: bool = False,
    file_ext: Optional[str] = None,
) -> FsListResponse:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    if not target.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    resolved = target.resolve()
    parent = str(resolved.parent) if resolved.parent != resolved else None
    if os.name == "nt" and len(str(resolved)) <= 3:
        parent = None

    entries: list[FsEntry] = []
    try:
        children = sorted(
            resolved.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.casefold()),
        )
    except PermissionError as exc:
        raise PermissionError(f"Permission denied: {path}") from exc

    ext = file_ext.lower().lstrip(".") if file_ext else None

    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if is_dir:
            entries.append(FsEntry(name=child.name, path=str(child), is_dir=True))
            continue
        if not include_files:
            continue
        if ext and child.suffix.lower().lstrip(".") != ext:
            continue
        entries.append(FsEntry(name=child.name, path=str(child), is_dir=False))

    return FsListResponse(path=str(resolved), parent=parent, entries=entries)
