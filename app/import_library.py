"""Import downloads/ into music library: MusicBrainz clean, skip/delete dupes, move to artist folders."""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from mutagen import File as MutagenFile
from mutagen.mp3 import HeaderNotFoundError

from app.library import (
    _index_directory,
    normalize_track_key,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOWNLOADS = REPO_ROOT / "downloads"
DEFAULT_MUSIC = Path(r"D:\music")
REPORT_PATH = REPO_ROOT / "scripts" / "move_to_library_report.txt"

AUDIO_EXT = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wma"}
ILLEGAL = re.compile(r'[\\/:*?"<>|]')
TRACK_PREFIX = re.compile(
    r"^(?:"
    r"\d{1,3}-\d{1,3}\s+"
    r"|\d{1,4}\s*[-_.]\s*"
    r"|\(\d{1,4}\)\s*"
    r"|\[\d{1,4}\]\s*"
    r")"
)
YEAR_PREFIX = re.compile(r"^(?:19|20)\d{2}\s*[-_.]\s+")

# YouTube / download noise
YT_PARENS = re.compile(
    r"[\(\[\{]\s*(?:"
    r"official(?:\s+(?:music|hd|4k|lyric))?\s*video|"
    r"official\s+(?:audio|lyric(?:s)?|video)|"
    r"lyric(?:s)?\s*video|"
    r"music\s*video|"
    r"hd\s*video|"
    r"4k|"
    r"visualizer|"
    r"audio|"
    r"remaster(?:ed)?(?:\s*\d{4})?|"
    r"single\s+version(?:\s*/\s*remastered)?|"
    r"radio\s+edit|"
    r"extended\s+12[\"″]?\s*remix(?:\s*\([^)]*\))?|"
    r"from\s+(?:the\s+)?(?:film|movie)\s+[\"'].*?[\"']|"
    r"as\s+featured\s+in\s+.*?|"
    r"ft\.?\s+.*?|"
    r"feat\.?\s+.*?"
    r")\s*[\)\]\}]",
    re.IGNORECASE,
)
YT_TRAILING = re.compile(
    r"\s*[-–|]\s*(?:official(?:\s+(?:music|hd|lyric))?\s*video|official\s+audio|"
    r"lyric(?:s)?\s*video|music\s*video)\s*$",
    re.IGNORECASE,
)
WWW_TAG = re.compile(r"[\[\(]www\.[^\]\)]+[\]\)]", re.IGNORECASE)
VEVO_SUFFIX = re.compile(r"VEVO$", re.IGNORECASE)
RECORD_LABEL_ARTISTS = re.compile(
    r"^(?:Atlantic Records|RHINO|ChessVEVO|UnidiscMusic|Old But Gold|"
    r"LatinHype|The Real Eve|Délicieuse Musique|"
    r"KatrinaTheWavesVEVO|ponycanyon|fadaachinin|iamkelis|"
    r"BlondieMusicOfficial|ParraforCuva|Rammstein Official|"
    r"Gazebo Official|TheSoundYouNeed|Ultra Records|Club Music 80|"
    r"Hellrazer12|UPROXX|fabmusicify)\s*[-–]\s*",
    re.IGNORECASE,
)
CHANNEL_OFFICIAL = re.compile(r"^(.+?)\s+Official\s*[-–]\s*", re.IGNORECASE)

USER_AGENT = "MyPlaylistMoveToLibrary/1.0 (local import; contact: local)"
MB_BASE = "https://musicbrainz.org/ws/2/"

FOLDER_ARTIST = {
    "AC DC": "AC/DC",
    "Guns n' Roses": "Guns N' Roses",
    "System Of a Down": "System of a Down",
    "Dj Tiesto": "Tiësto",
    "R.E.M": "R.E.M.",
    "P. Diddy": "Diddy",
    "T.I": "T.I.",
    "POD": "P.O.D.",
    "Beyonce": "Beyoncé",
    "Empire of the sun": "Empire of the Sun",
}

# Playlist / dump folders under downloads — never treat as artist
PLAYLIST_FOLDERS = {
    "'70",
    "'80",
    "2000",
    "hard",
    "summer",
    "perform",
    "run",
    "SPACE TRIP",
    "Paolo Cangialosi 80’s Vibes",
    "Parra for Cuva",
}

REPORT: dict[str, int] = {
    "scanned": 0,
    "mb_hit": 0,
    "heuristic": 0,
    "moved": 0,
    "deleted_dupe": 0,
    "failed": 0,
    "skipped_unreadable": 0,
}
REPORT_LINES: list[str] = []
_last_mb_call = 0.0
_quiet = False


def _reset_report() -> None:
    global REPORT, REPORT_LINES, _last_mb_call
    REPORT = {
        "scanned": 0,
        "mb_hit": 0,
        "heuristic": 0,
        "moved": 0,
        "deleted_dupe": 0,
        "failed": 0,
        "skipped_unreadable": 0,
    }
    REPORT_LINES = []
    _last_mb_call = 0.0


def log(msg: str) -> None:
    REPORT_LINES.append(msg)
    if _quiet:
        return
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)


# ---------------------------------------------------------------------------
# MusicBrainz helpers (ported from D:\music\.beets\cleanup_library.py)
# ---------------------------------------------------------------------------


def mb_get(path: str, params: dict) -> dict:
    global _last_mb_call
    qs = urllib.parse.urlencode(params)
    url = f"{MB_BASE}{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err: Exception | None = None
    for attempt in range(5):
        wait = 1.15 - (time.time() - _last_mb_call)
        if wait > 0:
            time.sleep(wait)
        _last_mb_call = time.time()
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (503, 429, 502):
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    raise last_err or RuntimeError("MusicBrainz request failed")


def sanitize_filename(name: str) -> str:
    name = name.replace("/", "-").replace("\\", "-")
    name = ILLEGAL.sub("-", name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    name = re.sub(r"\s*-\s*-\s*", " - ", name)
    return name


def sanitize_folder_name(name: str) -> str:
    # Keep AC/DC as AC DC for Windows paths
    name = name.replace("/", " ").replace("\\", " ")
    name = ILLEGAL.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "Unknown Artist"


def strip_junk(stem: str) -> str:
    s = unicodedata.normalize("NFKC", stem)
    s = s.replace("_", " ").replace("／", "/").replace("⧸", "/")
    s = TRACK_PREFIX.sub("", s)
    s = YEAR_PREFIX.sub("", s)
    s = WWW_TAG.sub("", s)
    s = YT_PARENS.sub(" ", s)
    s = YT_TRAILING.sub("", s)
    s = RECORD_LABEL_ARTISTS.sub("", s)
    s = CHANNEL_OFFICIAL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" -._")
    return s


def parse_artist_title(stem: str) -> tuple[str, str]:
    s = strip_junk(stem)
    # Fix "Artist - Artist - Title"
    if " - " in s:
        parts = [p.strip() for p in s.split(" - ") if p.strip()]
        if len(parts) >= 3:
            # Channel - Artist - Title  OR  Artist - Artist - Title
            if parts[0].casefold() == parts[1].casefold():
                return parts[0], " - ".join(parts[2:])
            # Label/channel then real artist
            if (
                VEVO_SUFFIX.search(parts[0])
                or "Records" in parts[0]
                or parts[0].endswith("Music")
                or parts[0].endswith("Official")
            ):
                return parts[1], " - ".join(parts[2:]) if len(parts) > 2 else parts[1]
            # Artist - Title with extra suffix segments
            return parts[0], " - ".join(parts[1:])
        if len(parts) == 2:
            artist, title = parts
            # Title already contains "Artist - Title" duplicated in tag-ish stems
            if title.casefold().startswith(artist.casefold() + " - "):
                title = title[len(artist) + 3 :].strip()
            # "Rammstein Official" leftover as artist with "Rammstein - Song" title
            if " - " in title and (
                artist.casefold().endswith("official")
                or artist.casefold() in {"thesoundyouneed", "uproxx", "hellrazer12"}
            ):
                return parse_artist_title(title)
            return artist.strip(), title.strip()
    if " – " in s:
        artist, title = s.split(" – ", 1)
        return artist.strip(), title.strip()
    m = re.match(r"^(.+?)\s*-\s*(.+)$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", s


def title_case_light(s: str) -> str:
    if not s:
        return s
    small = {
        "a", "an", "the", "and", "or", "but", "for", "nor", "on", "at",
        "to", "from", "by", "of", "in", "vs", "vs.", "feat", "feat.", "ft", "ft.",
    }
    parts = re.split(r"(\s+|-)", s)
    out: list[str] = []
    word_i = 0
    for p in parts:
        if not p or p.isspace() or p == "-":
            out.append(p)
            continue
        lower = p.lower()
        if word_i > 0 and lower in small:
            out.append(lower)
        elif p.isupper() and len(p) <= 4:
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper())
        word_i += 1
    return "".join(out)


def artist_credit_name(credit: list) -> str:
    parts: list[str] = []
    for c in credit:
        if isinstance(c, dict):
            parts.append(c.get("name") or c.get("artist", {}).get("name", ""))
            join = c.get("joinphrase")
            if join:
                parts.append(join)
        elif isinstance(c, str):
            parts.append(c)
    return "".join(parts).strip()


def _norm(s: str) -> str:
    s = s.lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _token_set(s: str) -> set[str]:
    stop = {"the", "a", "an", "and", "feat", "ft", "featuring", "with", "vs", "cu"}
    return {t for t in _norm(s).split() if t and t not in stop}


def _similarity(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


def _is_junk_recording(rec: dict, query_artist: str, query_title: str) -> bool:
    title = rec.get("title") or ""
    t = title.lower()
    if re.search(r"\b(tribute|cover|karaoke|ringtone|made famous)\b", t):
        return True
    credit = artist_credit_name(rec.get("artist-credit") or [])
    if re.search(r"\b(tribute|karaoke)\b", credit.lower()):
        return True
    if _similarity(query_title, title) < 0.45 and _norm(query_title) not in _norm(title):
        return True
    if query_artist and _similarity(query_artist, credit) < 0.34:
        qa = _token_set(query_artist)
        qc = _token_set(credit)
        if not qa & qc:
            return True
    return False


def search_recording(artist: str, title: str) -> dict | None:
    if not title:
        return None
    clauses = [f'recording:"{title}"']
    if artist:
        clauses.append(f'artist:"{artist}"')
    query = " AND ".join(clauses)
    try:
        data = mb_get("recording", {"query": query, "fmt": "json", "limit": "12"})
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        log(f"  MB error: {e}")
        return None

    recordings = data.get("recordings") or []
    if not recordings and artist:
        try:
            data = mb_get(
                "recording",
                {"query": f'artist:"{artist}" AND recording:"{title}"', "fmt": "json", "limit": "12"},
            )
            recordings = data.get("recordings") or []
        except Exception as e:  # noqa: BLE001
            log(f"  MB error: {e}")
            return None
    if not recordings:
        return None

    best = None
    best_score = -1
    for rec in recordings:
        if _is_junk_recording(rec, artist, title):
            continue
        score = int(rec.get("score") or 0)
        credit = artist_credit_name(rec.get("artist-credit") or [])
        rec_title = rec.get("title") or ""
        artist_sim = _similarity(artist, credit) if artist else 0.5
        title_sim = _similarity(title, rec_title)
        releases = rec.get("releases") or []
        bonus = int(30 * artist_sim + 25 * title_sim)
        for rel in releases[:3]:
            status = (rel.get("status") or "").lower()
            if status == "official":
                bonus += 5
            if rel.get("date"):
                bonus += 2
        total = score + bonus
        if total > best_score:
            best_score = total
            best = rec
    if not best or int(best.get("score") or 0) < 85:
        return None
    if _is_junk_recording(best, artist, title):
        return None
    return best


def _looks_live_bootleg(rel: dict) -> bool:
    title = (rel.get("title") or "").lower()
    if re.search(r"\b(live|bootleg|demo)\b", title):
        return True
    if re.match(r"^\d{4}-\d{2}-\d{2}:", title):
        return True
    return False


def pick_release(rec: dict) -> tuple[str, str]:
    releases = rec.get("releases") or []
    if not releases:
        return "", ""

    def score_rel(r: dict) -> tuple:
        title = (r.get("title") or "").lower()
        rg = r.get("release-group") or {}
        primary = (rg.get("primary-type") or "").lower()
        secondary = [s.lower() for s in (rg.get("secondary-types") or [])]
        status = (r.get("status") or "").lower()
        date = r.get("date") or ""

        bad = 0
        if status and status != "official":
            bad += 50
        if _looks_live_bootleg(r):
            bad += 80
        if any(x in secondary for x in ("compilation", "live", "remix", "dj-mix", "mixtape/street")):
            bad += 40
        if re.search(
            r"greatest hits|best of|the singles|hits\b|anthology|playlist|"
            r"throwback|now that.?s what|top\s*\d|millennium|compilation|"
            r"music from and inspired|soundtrack|tribute",
            title,
        ):
            bad += 45
        if primary == "album":
            type_rank = 0
        elif primary == "single":
            type_rank = 1
        elif primary == "ep":
            type_rank = 2
        else:
            type_rank = 3
        has_date = 0 if date else 1
        return (bad, type_rank, has_date, date or "9999")

    best = min(releases, key=score_rel)
    if score_rel(best)[0] >= 80:
        return "", ""
    album = best.get("title") or ""
    date = (best.get("date") or "")[:4]
    return album, date


def _album_worse_than_existing(new_album: str, existing: str) -> bool:
    if not existing:
        return False
    if not new_album:
        return True
    ex = existing.lower().strip()
    nw = new_album.lower().strip()
    if ex == nw:
        return False
    junk = re.compile(
        r"live|greatest hits|best of|the singles|anthology|bootleg|deluxe edition bonus"
    )
    if junk.search(nw) and not junk.search(ex):
        return True
    return False


def read_tags(path: Path) -> dict:
    try:
        audio = MutagenFile(str(path), easy=True)
    except (HeaderNotFoundError, Exception):  # noqa: BLE001
        return {}
    if audio is None:
        return {}

    def g(key: str) -> str:
        v = audio.get(key)
        return v[0] if v else ""

    return {
        "artist": g("artist"),
        "title": g("title"),
        "album": g("album"),
        "date": g("date") or g("year"),
    }


def write_tags(path: Path, artist: str, title: str, album: str, date: str) -> None:
    audio = MutagenFile(str(path), easy=True)
    if audio is None:
        raise RuntimeError("cannot open for tagging")
    if audio.tags is None:
        audio.add_tags()
    audio["artist"] = artist
    audio["title"] = title
    if album:
        audio["album"] = album
    if date:
        audio["date"] = date
    audio.save()


def clean_title_string(title: str) -> str:
    title = WWW_TAG.sub("", title)
    title = YT_PARENS.sub(" ", title)
    title = YT_TRAILING.sub("", title)
    title = re.sub(r"\s+", " ", title).strip(" -")
    # Drop leading duplicated artist in title: "Akon - I Wanna Love You"
    return title


def prefer_filename(parsed: str, tagged: str, threshold: float) -> str:
    if not parsed:
        return tagged
    if not tagged:
        return parsed
    if _similarity(parsed, tagged) < threshold:
        return parsed
    pt, tt = _token_set(parsed), _token_set(tagged)
    if pt != tt and tt and tt.issubset(pt) and len(pt) > len(tt):
        return parsed
    return tagged


def resolve_metadata(path: Path) -> tuple[str, str, str, str, str]:
    """Return (artist, title, album, date, source)."""
    parsed_artist, parsed_title = parse_artist_title(path.stem)
    tags = read_tags(path)
    tag_artist = (tags.get("artist") or "").strip()
    tag_title = clean_title_string((tags.get("title") or "").strip())
    # If tag title is "Artist - Title", split it
    if tag_title and " - " in tag_title and tag_artist:
        if tag_title.casefold().startswith(tag_artist.casefold() + " - "):
            tag_title = tag_title[len(tag_artist) + 3 :].strip()

    artist = prefer_filename(parsed_artist, tag_artist, 0.34)
    title = prefer_filename(parsed_title, tag_title, 0.45)
    artist = artist.strip()
    title = clean_title_string(title.strip())

    if not title:
        raise ValueError("no title")

    rec = search_recording(artist, title)
    if not rec and parsed_artist and parsed_title:
        swapped = search_recording(parsed_title, parsed_artist)
        if swapped:
            artist, title = parsed_title, parsed_artist
            rec = swapped

    album = (tags.get("album") or "").strip()
    date = (tags.get("date") or "").strip()[:4]

    if rec:
        new_title = rec.get("title") or title
        credit = rec.get("artist-credit") or []
        new_artist = artist_credit_name(credit) or artist
        mb_album, mb_date = pick_release(rec)
        if mb_album and not _album_worse_than_existing(mb_album, album):
            album = mb_album
        if mb_date and (not date or len(date) < 4):
            date = mb_date
        elif mb_date and not album:
            date = mb_date
        source = "musicbrainz"
    else:
        new_artist = artist or "Unknown Artist"
        new_title = parsed_title or title
        new_title = re.sub(r"\s+", " ", new_title).strip()
        if new_title.islower() or new_title.isupper() or "_" in path.stem:
            new_title = title_case_light(new_title)
        if new_artist.islower() or (new_artist.isupper() and len(new_artist) > 4):
            new_artist = title_case_light(new_artist)
        source = "heuristic"

    new_artist = re.sub(r"\s+", " ", new_artist).strip()
    new_title = re.sub(r"\s+", " ", new_title).strip()
    # Drop duplicated artist prefix in title: "Metallica： Moth Into Flame"
    if new_artist and new_title:
        for sep in (": ", "：", " - "):
            prefix = new_artist + sep
            if new_title.casefold().startswith(prefix.casefold()):
                new_title = new_title[len(prefix) :].strip()
                break
    # Fix common UTF-8 mojibake in artist names
    if "Ă¶" in new_artist or "Ã¶" in new_artist:
        new_artist = new_artist.replace("Ă¶", "ö").replace("Ã¶", "ö")
    return new_artist, new_title, album, date, source


def primary_artist(artist: str) -> str:
    """First billed artist for folder placement.

    Splits collab markers (feat/ft/vs) but keeps comma bands like
    \"Earth, Wind & Fire\" / \"Lipps, Inc.\". For \"A, B\" duets, prefer the
    left name only when it already has an artist folder in the library map.
    """
    s = artist.strip()
    for sep in (" feat. ", " feat ", " ft. ", " ft ", " featuring ", " with ", " vs. ", " vs "):
        idx = s.casefold().find(sep)
        if idx > 0:
            s = s[:idx]
            break
    # Do not split on bare \" & \" — many real band names use it.
    return s.strip()


def build_artist_folder_map(music_dir: Path) -> dict[str, str]:
    """normalized folder key -> actual folder name."""
    mapping: dict[str, str] = {}
    if not music_dir.is_dir():
        return mapping
    for d in music_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name in PLAYLIST_FOLDERS:
            continue
        key = normalize_track_key(d.name.replace("/", " "))
        mapping.setdefault(key, d.name)
        # Also map without spaces for AC/DC <-> AC DC
        mapping.setdefault(normalize_track_key(d.name.replace(" ", "")), d.name)
    for folder, preferred in FOLDER_ARTIST.items():
        key = normalize_track_key(folder)
        if key not in mapping and (music_dir / folder).is_dir():
            mapping[key] = folder
        # preferred spelling -> existing folder if present
        folder_path = music_dir / sanitize_folder_name(preferred)
        if folder_path.is_dir():
            mapping.setdefault(normalize_track_key(preferred), folder_path.name)
            mapping.setdefault(normalize_track_key(sanitize_folder_name(preferred)), folder_path.name)
    return mapping


def resolve_artist_folder(music_dir: Path, artist: str, folder_map: dict[str, str]) -> Path:
    primary = primary_artist(artist)
    # For "Elton John, Kiki Dee"-style credits: use left side if that folder exists
    if ", " in primary:
        left = primary.split(", ", 1)[0].strip()
        left_key = normalize_track_key(left)
        if left_key in folder_map:
            primary = left
        elif left_key not in folder_map and normalize_track_key(primary) not in folder_map:
            # New duet folder vs new solo: if left looks like a person name (2+ words), use it
            if len(left.split()) >= 2 and not re.search(
                r"\b(inc|ltd|llc|wind|earth|fire)\b", primary, re.I
            ):
                primary = left

    # Prefer existing folder spelling
    for candidate in (primary, artist, sanitize_folder_name(primary), primary.replace("/", " ")):
        key = normalize_track_key(candidate)
        if key in folder_map:
            return music_dir / folder_map[key]
        key2 = normalize_track_key(candidate.replace(" ", ""))
        if key2 in folder_map:
            return music_dir / folder_map[key2]
    folder_name = sanitize_folder_name(primary)
    return music_dir / folder_name


def unique_target(folder: Path, filename: str) -> Path:
    target = folder / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    ext = Path(filename).suffix
    n = 2
    while True:
        cand = folder / f"{stem} ({n}){ext}"
        if not cand.exists():
            return cand
        n += 1


def _nk(text: str) -> str:
    """Normalize with NFKC so fullwidth Latin (e.g. Asthenic mix titles) match ASCII."""
    return normalize_track_key(unicodedata.normalize("NFKC", text))


def candidate_keys(artist: str, title: str, filename_stem: str) -> set[str]:
    """Strong keys only — avoid bare short title keys that collide across mixes."""
    keys: set[str] = set()
    artist_n = unicodedata.normalize("NFKC", artist or "").strip()
    title_n = unicodedata.normalize("NFKC", title or "").strip()
    if artist_n and title_n:
        keys.add(_nk(f"{artist_n} - {title_n}"))
        keys.add(_nk(f"{artist_n} {title_n}"))
    # Title-only only when distinctive enough (after NFKC + paren strip)
    if title_n:
        tk = _nk(title_n)
        if len(tk) >= 10:
            keys.add(tk)
    if filename_stem:
        stem_n = unicodedata.normalize("NFKC", filename_stem)
        sk = _nk(stem_n)
        if len(sk) >= 12:
            keys.add(sk)
        if " - " in stem_n:
            left, right = stem_n.split(" - ", 1)
            keys.add(_nk(f"{left} {right}"))
            rk = _nk(right)
            if len(rk) >= 10:
                keys.add(rk)
    return {k for k in keys if k}


def find_duplicate(index: dict[str, str], artist: str, title: str, stem: str) -> str | None:
    for key in candidate_keys(artist, title, stem):
        if key in index:
            return index[key]
    return None


def move_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except OSError:
        shutil.copy2(src, dest)
        if dest.stat().st_size != src.stat().st_size:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"copy size mismatch for {src} -> {dest}")
        src.unlink()


def iter_downloads(downloads: Path):
    for path in sorted(downloads.rglob("*")):
        if path.is_file() and path.suffix.lower() in AUDIO_EXT:
            yield path


def process_file(
    path: Path,
    downloads: Path,
    music_dir: Path,
    index: dict[str, str],
    folder_map: dict[str, str],
    apply: bool,
) -> None:
    REPORT["scanned"] += 1
    rel = path.relative_to(downloads)

    try:
        # Verify readable
        tags_probe = read_tags(path)
        if not tags_probe and path.suffix.lower() == ".mp3":
            # Still try — some files have no tags but are valid
            MutagenFile(str(path))
    except Exception as e:  # noqa: BLE001
        REPORT["skipped_unreadable"] += 1
        log(f"SKIP unreadable: {rel} ({e})")
        return

    try:
        artist, title, album, date, source = resolve_metadata(path)
    except Exception as e:  # noqa: BLE001
        REPORT["failed"] += 1
        log(f"FAIL metadata: {rel}: {e}")
        return

    if source == "musicbrainz":
        REPORT["mb_hit"] += 1
    else:
        REPORT["heuristic"] += 1

    ext = path.suffix.lower() or ".mp3"
    new_name = sanitize_filename(f"{artist} - {title}") + ext
    folder = resolve_artist_folder(music_dir, artist, folder_map)
    dest = unique_target(folder, new_name)

    # Duplicate against library (before we would add this file)
    hit = find_duplicate(index, artist, title, path.stem)
    # Also check cleaned name against index
    if not hit:
        hit = find_duplicate(index, artist, title, f"{artist} - {title}")

    prefix = "" if apply else "[DRY] "
    log(f"{prefix}{rel}")
    log(f"  [{source}] {artist!r} - {title!r} | album={album!r} date={date!r}")

    if hit:
        REPORT["deleted_dupe"] += 1
        log(f"  DUPE of {hit} -> delete download")
        if apply:
            try:
                path.unlink()
            except OSError as e:
                REPORT["failed"] += 1
                log(f"  ERROR deleting dupe: {e}")
        return

    log(f"  move -> {dest.relative_to(music_dir)}")

    if not apply:
        REPORT["moved"] += 1
        # Register planned destination keys so later dry-run items in same batch see it
        for key in candidate_keys(artist, title, f"{artist} - {title}"):
            index.setdefault(key, str(dest))
        return

    try:
        write_tags(path, artist, title, album, date)
        move_file(path, dest)
        REPORT["moved"] += 1
        # Update index so later files in this run see the new track
        for key in candidate_keys(artist, title, dest.stem):
            index.setdefault(key, str(dest))
        # Update folder map if we created a new folder
        folder_key = normalize_track_key(folder.name)
        folder_map.setdefault(folder_key, folder.name)
    except Exception as e:  # noqa: BLE001
        REPORT["failed"] += 1
        log(f"  ERROR: {e}")


def run_import(
    downloads: Path | str,
    music_dir: Path | str,
    *,
    apply: bool = False,
    limit: int = 0,
    quiet: bool = False,
    write_report: bool = True,
) -> dict[str, Any]:
    """Import audio from downloads into music_dir artist folders.

    Returns counts + log lines. Default is dry-run (apply=False).
    """
    global _quiet
    _quiet = quiet
    _reset_report()

    downloads_path = Path(downloads).resolve()
    music_path = Path(music_dir).resolve()

    if not downloads_path.is_dir():
        raise FileNotFoundError(f"Downloads dir missing: {downloads_path}")
    if not music_path.is_dir():
        raise FileNotFoundError(f"Music dir missing: {music_path}")

    log(f"Indexing library: {music_path}")
    index = _index_directory(music_path)
    folder_map = build_artist_folder_map(music_path)
    log(f"Library index keys: {len(index)}; artist folders: {len(folder_map)}")

    files = list(iter_downloads(downloads_path))
    if limit and limit > 0:
        files = files[:limit]

    mode = "APPLY" if apply else "DRY-RUN"
    log(f"Processing {len(files)} files ({mode})")
    log("")

    for i, path in enumerate(files, 1):
        if i % 25 == 0:
            log(f"... {i}/{len(files)}")
        try:
            process_file(path, downloads_path, music_path, index, folder_map, apply)
        except Exception as e:  # noqa: BLE001
            REPORT["failed"] += 1
            log(f"FAIL {path}: {e}")

    log("")
    log("=== SUMMARY ===")
    for k, v in REPORT.items():
        log(f"{k}: {v}")

    if write_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text("\n".join(REPORT_LINES), encoding="utf-8")
        log(f"Report written to {REPORT_PATH}")

    return {
        "dry_run": not apply,
        "counts": dict(REPORT),
        "lines": list(REPORT_LINES),
        "report_path": str(REPORT_PATH) if write_report else None,
    }
