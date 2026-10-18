# My Playlist

Local-only MP3 downloader with a classic **Winamp 2.x**-style UI. Download from song search, YouTube / YouTube Music links, or playlists. Runs entirely on your machine.

## Features

- **Search** — enter `Song - Artist` (one per line), pick a match, download
- **Link** — paste a single YouTube / YouTube Music video URL
- **Playlist** — load a playlist, check tracks, download selected (optional subfolder by playlist name)
- **MP3 only** — best available audio → MP3 (default 320 kbps) via `yt-dlp` + ffmpeg
- **Concurrent downloads** with a live job list and progress
- **Duplicate warnings** — compare against your music library folder and `downloads/`
- **Retry tools** — RETRY same URL, or RE-SEARCH for another upload when a video is gone
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

From the repo root:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

Downloaded files go under `downloads/` (gitignored). Playlist downloads can use `downloads/<playlist-name>/` when **Playlist subfolder** is enabled in EQ.

## Modes (player tabs)

| Tab | Purpose |
|-----|---------|
| **SRCH** | Multi-line search; choose one candidate per song; download |
| **LINK** | One video URL → download |
| **PL** | Playlist URL → checkboxes → download selected |
| **EQ** | Settings (stored in browser `localStorage`) |

### EQ settings

| Setting | Default | Notes |
|---------|---------|--------|
| Concurrent downloads | 3 | Parallel workers |
| Search results per song | 5 | Candidates shown after SEARCH |
| Filename template | Artist - Title | Or title only |
| Audio bitrate (kbps) | 320 | MP3 encode quality |
| Music library folder | _(empty)_ | Used for duplicate checks; **BROWSE** available |
| YouTube cookies.txt | _(empty)_ | Netscape cookie file; helps with 403s; **BROWSE** available |
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

| Problem | What to do |
|---------|------------|
| Temporary / **403 Forbidden** | Set **YouTube cookies.txt** in EQ, then **RETRY**. Also try lower concurrency or `pip install -U yt-dlp`. |
| **Video unavailable** | Use **RE-SEARCH** on that failed item (searches by title, downloads the top match). |
| Same URL might work later | **RETRY** re-queues the original link. |

Failed items in the job list show **RETRY** and **RE-SEARCH** buttons, plus short tips.

### Exporting cookies (for 403s)

1. Log into YouTube in your browser.
2. Export cookies in **Netscape `cookies.txt`** format (browser extension such as “Get cookies.txt LOCALLY” or similar).
3. In EQ, set **YouTube cookies.txt** (or **BROWSE** to the file) and **SAVE**.
4. **RETRY** the failed tracks.

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
- Some videos are region-locked, private, or removed; RE-SEARCH or another link may be required.
- Cookie files stay on your machine; the path is stored in `localStorage` and sent to the local API when downloading.
