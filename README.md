# My Playlist

Local-only MP3 downloader with a classic **Winamp 2.x**-style UI. Download from song search, YouTube / YouTube Music links, or playlists. Runs entirely on your machine.

## Features

- **Search** — enter `Song - Artist` (one per line), pick a match, download
- **Link** — paste a single YouTube / YouTube Music video URL
- **Playlist** — YouTube Music **or public Spotify** playlists; check tracks; download selected (optional subfolder by playlist name)
- **MP3 only** — best available audio → MP3 (default 320 kbps) via `yt-dlp` + ffmpeg
- **Concurrent downloads** with a live job list and progress
- **Duplicate warnings** — compare against your music library folder and `downloads/`
- **Auto search-fallback** — if a download fails for any reason, the worker searches YouTube for `Artist - Title` and tries the top match
- **Retry tools** — manual RETRY (same URL) or RE-SEARCH on failed items
- **YouTube cookies** — optional `cookies.txt` to reduce HTTP 403 failures
- **Folder / file browser** — pick music library and cookie paths without typing
- **Winamp chrome** — transport and playlist footer buttons map to real app actions

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/download.html) (required for MP3 conversion)
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

Install ffmpeg if needed:

```bash
# Windows (winget)
winget install --id Gyan.FFmpeg -e

# macOS (Homebrew)
brew install ffmpeg

# Debian / Ubuntu
sudo apt install ffmpeg
```

Verify:

```bash
ffmpeg -version
```

The app also auto-detects common Windows ffmpeg install paths (including WinGet) if it is not yet on `PATH`.

Update yt-dlp periodically (YouTube changes often):

```bash
pip install -U yt-dlp
```

## Run

### Easy way (Windows)

Double-click `start.bat`, or in PowerShell from the repo root:

```powershell
.\start.ps1
```

The script checks Python, ffmpeg, and pip packages, prints install hints if something is missing, creates `.venv` if needed, then starts the server and opens [http://127.0.0.1:8765](http://127.0.0.1:8765).

### Manual way

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

(Use the venv: `.venv\Scripts\activate` on Windows, then the same command.)

Downloaded files go under `downloads/` (gitignored). Playlist downloads can use `downloads/<playlist-name>/` when **Playlist subfolder** is enabled in EQ.

## Modes (player tabs)

| Tab | Purpose |
|-----|---------|
| **SRCH** | Multi-line search; choose one candidate per song; download |
| **LINK** | One video URL → download |
| **PL** | YouTube Music or **public Spotify** playlist URL → checkboxes → download selected |
| **EQ** | Settings (stored in browser `localStorage`) |

### Spotify playlists

- Paste a **public** `open.spotify.com/playlist/...` link into **PL** (no Spotify API keys, no Premium required for this method).
- Tracks are read from Spotify’s public **embed** page, then each selected song is downloaded via YouTube search (`Artist - Title`).
- Embed pages typically expose up to ~**100** tracks; longer playlists are truncated to what Spotify embeds.
- **Private** Spotify playlists are not supported.

### EQ settings

| Setting | Default | Notes |
|---------|---------|--------|
| Concurrent downloads | 3 | Parallel workers |
| Search results per song | 5 | Candidates shown after SEARCH |
| Filename template | Artist - Title | Or title only |
| Audio bitrate (kbps) | 320 | MP3 encode quality |
| Music library folder | _(empty)_ | Used for duplicate checks; **BROWSE** available |
| YouTube cookies from browser | Off | Chrome / Edge / Firefox / Brave — needed for **age-restricted** videos (close browser if extraction fails) |
| Or cookies.txt file | _(empty)_ | Netscape cookie file alternative; **BROWSE** available |
| Playlist subfolder | on | Save playlist tracks under a named folder |
| Embed ID3 metadata | on | When tags are available |
| Warn on duplicates | on | Confirm before re-downloading |

## Duplicates

When **Warn on duplicates** is on, the app scans:

1. Your **music library folder** (recursive), and  
2. The app **`downloads/`** directory  

Matching is exact-ish normalized names (strips `(Official Video)`, `feat.`, punctuation, etc.) using filenames and ID3 tags via mutagen.

If matches are found you can **SKIP DUPES**, **DOWNLOAD ALL**, or **CANCEL**.

## Failed downloads

On any download error (403, unavailable, network, etc.), the backend **automatically** retries once with a YouTube search for the track title (`ytsearch1:Artist - Title`). Spotify playlist rows already start as search URLs.

If that still fails, the job item stays **FAILED**. You can then:

| Action | What it does |
|--------|----------------|
| **RETRY** | Same URL again (helps with temporary 403s; set cookies in EQ first) |
| **RE-SEARCH** | Manual search by title → top match |

Also keep yt-dlp updated: `pip install -U yt-dlp`.

### Cookies (age-restricted / 403s)

Easiest:

1. Log into YouTube in Chrome/Edge/Firefox/Brave.
2. In **EQ**, set **YouTube cookies from browser** to that browser → **SAVE**.
3. If yt-dlp can’t read the profile, **fully quit** the browser and retry.
4. **RETRY** the failed track.

Alternative: export Netscape `cookies.txt` and set **Or cookies.txt file** in EQ.

## Winamp controls

These keep the classic look but perform real actions:

| Control | Action |
|---------|--------|
| **ADD** | Switch to Search |
| **REM** | Clear finished/failed jobs from the UI list |
| **SEL** | Select all tracks in a loaded playlist |
| **MISC** / **LIST OPTS** | Open EQ (settings) |
| **▶** / **□** | Focus the job list |
| **⏮** / **⏭** | Cycle highlighted jobs |
| **⏸** | Pause / resume job status polling |
| **⏹** / **×** | Reset LCD to READY |
| **⏏** | Open Link mode |
| **_** | Hide / show the form panels |

## Project layout

```
my-playlist/
  app/
    main.py          # FastAPI routes + static hosting
    downloader.py    # yt-dlp search, playlist, downloads, jobs
    spotify.py       # Public Spotify playlist via embed page
    library.py       # Duplicate index / matching
    fsbrowser.py     # Local folder/file picker API
    models.py        # Request/response models
  static/
    index.html
    app.js
    styles.css
  downloads/         # Output (gitignored)
  requirements.txt
  README.md
```

## Stack

- **Backend:** Python, FastAPI, uvicorn  
- **Download / convert:** yt-dlp, ffmpeg  
- **Tags / dupes:** mutagen  
- **Frontend:** vanilla HTML / CSS / JS (no build step)

## Notes

- For personal / local use only.
- Some videos are region-locked, private, or removed; auto search-fallback and manual RE-SEARCH help in most cases.
- Cookie files stay on your machine; the path is stored in `localStorage` and sent to the local API when downloading.
- Spotify embed scraping can break if Spotify changes their embed HTML; no official API is used.
