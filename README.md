# My Playlist

Local-only MP3 downloader. Search songs, download links or playlists, sync saved playlists against your library, and import downloads into artist folders. Runs entirely on your machine.

## Features

- **Search songs** — `Song - Artist` (one per line), pick a match, download
- **Download link** — paste a YouTube / YouTube Music video URL
- **Download playlist** — one-shot load of a YouTube Music or **public Spotify** playlist; pick tracks; download (not saved)
- **Sync playlists** — save playlists, check every N days for tracks missing from your library; download selected / all / dismiss
- **Import to library** — dry-run then apply: `downloads/` → music library artist folders
- **MP3 only** — best available audio → MP3 (default 320 kbps) via `yt-dlp` + ffmpeg
- **Jobs panel** — concurrent downloads with progress, Retry / Re-search on failures
- **Duplicate warnings** — before ad-hoc downloads, compare against your music library and `downloads/`
- **Persisted state** — settings, saved playlists, and sync queue in `data/state.json` (gitignored)

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/download.html)
- Internet access for YouTube / YouTube Music

## Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Install ffmpeg if needed, then verify with `ffmpeg -version`. Update yt-dlp periodically: `pip install -U yt-dlp`.

## Run

### Easy way (Windows)

Double-click `start.bat`, or in PowerShell:

```powershell
.\start.ps1
```

Opens [http://127.0.0.1:8765](http://127.0.0.1:8765).

### Manual way

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

Downloads go under `downloads/`. App state lives in `data/state.json`.

## How the app is organized

The home screen is a set of cards. Each opens a focused flow; use **Home** (or the brand) to return. **Jobs** in the top bar opens the download panel.

| Card | What it does |
|------|----------------|
| **Search songs** | Multi-line search → pick candidates → download |
| **Download link** | One video URL → download |
| **Download playlist** | Load playlist once → select tracks → download. **Not** saved for later sync |
| **Sync playlists** | Save playlists to monitor; sync due/all → missing queue → download or dismiss |
| **Import to library** | Dry-run / apply import of `downloads/` into your music folder |
| **Settings** | Paths, sync interval, cookies, quality |

### Download playlist vs Sync playlists

These are separate on purpose:

1. **Download playlist** — one-shot. Paste URL, load, download what you want. Nothing is persisted for monitoring.
2. **Sync playlists** — long-term. Add URLs to a saved list. Every **N days** (Settings → Sync interval, default **7**) they become *due*. Sync compares tracks to your library + `downloads/` and fills a **missing** queue. You choose what to download; nothing auto-downloads. Opening the app does **not** auto-sync; the Sync card shows due/queue badges instead.

### Spotify

- Public `open.spotify.com/playlist/...` only (embed scrape; typically up to ~100 tracks).
- Private playlists are not supported.

### Library import

Same pipeline as the CLI:

```bash
python scripts/move_to_library.py          # dry-run
python scripts/move_to_library.py --apply
```

Target layout: `musicDir\<Artist>\<Artist - Title>.mp3` (default music folder `D:\music`).

### Settings

| Setting | Default | Notes |
|---------|---------|--------|
| Concurrent downloads | 3 | Parallel workers |
| Search results per song | 5 | Candidates after Search |
| Filename template | Artist - Title | Or title only |
| Audio bitrate (kbps) | 320 | MP3 encode quality |
| Sync interval (days) | 7 | When saved playlists become due |
| Music library folder | `D:\music` | Dupes, sync checks, import target |
| YouTube cookies from browser | Off | Chrome / Edge / Firefox / Brave |
| Or cookies.txt file | _(empty)_ | Netscape cookie file |
| Playlist subfolder | on | Named folder under `downloads/` for playlist/sync batches |
| Embed ID3 metadata | on | When tags are available |
| Warn on duplicates | on | Confirm before re-downloading (search / link / one-shot playlist) |

## Project layout

```
my-playlist/
  app/
    main.py            # FastAPI routes + static hosting
    state.py           # data/state.json persistence
    sync.py            # Due-check + missing-track queue
    import_library.py  # downloads → music library
    downloader.py      # yt-dlp search, playlist, downloads, jobs
    spotify.py         # Public Spotify playlist via embed
    library.py         # Duplicate index / matching
    fsbrowser.py       # Local folder/file picker
    models.py
  static/              # Light wizard UI (home + focused screens)
  data/                # state.json (gitignored)
  downloads/           # Output (gitignored)
  scripts/move_to_library.py
```

## Stack

- **Backend:** Python, FastAPI, uvicorn  
- **Download / convert:** yt-dlp, ffmpeg  
- **Tags / dupes / import:** mutagen, MusicBrainz  
- **Frontend:** vanilla HTML / CSS / JS (no build step)

## Notes

- For personal / local use only. No database — one JSON state file.
- Cookie paths stay on your machine.
- Spotify embed scraping can break if Spotify changes their embed HTML.
