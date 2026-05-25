# Suno Music Archiver — Flask + Local JSON

Flask REST API + single-file UI that archives Suno profiles, playlists, and clips to local JSON files.

Supports **both**:
- Local JSON storage (`./json/profiles/...`)
- Live fetch from the public Suno API on demand

https://studio-api.prod.suno.com/api/playlist/574c5144-2eb5-44e1-9333-3add06c84006
https://studio-api.prod.suno.com/api/profiles/fghjkl11?playlists_sort_by=upvote_count&clips_sort_by=created_at

## Stack

- Python 3.10+
- Flask 3+
- `requests`

## Quick Start

```powershell
cd c:\dev\projects\AI\pets\music

# Install dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the app
.\.venv\Scripts\python.exe app.py
```

Open:
- **UI Player**: http://127.0.0.1:8000/
- **API**: http://127.0.0.1:8000/profiles/

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/profiles/` | List all archived profiles |
| `POST` | `/profiles/sync/` | Fetch from Suno + save to local JSON |
| `GET` | `/profiles/{handle}/` | Profile with embedded playlists |
| `GET` | `/profiles/{handle}/playlists/` | Playlists for a profile |
| `GET` | `/profiles/{handle}/playlists/{playlist_id}/` | Playlist detail |
| `GET` | `/profiles/{handle}/playlists/{playlist_id}/clips/` | Clips in a playlist |
| `GET` | `/profiles/{handle}/playlists/{playlist_id}/clips/{clip_id}/` | Single clip |

## Usage

### Sync a profile via UI
Enter a handle (e.g. `fotballpiraten`) in the top bar and click **sync**.

### Sync via curl
```sh
curl -X POST http://127.0.0.1:8000/profiles/sync/ \
  -H "Content-Type: application/json" \
  -d '{"handle": "fotballpiraten"}'
```

### Read data
```sh
curl http://127.0.0.1:8000/profiles/
curl http://127.0.0.1:8000/profiles/fotballpiraten/playlists/
curl http://127.0.0.1:8000/profiles/fotballpiraten/playlists/<playlist_id>/clips/
```

## Local Storage

All data lives in:

```
json/
  profiles/
    <DisplayName>/
      profile.json
      playlists/
        <playlist_id>.json
        <playlist_id>/
          clips/
            <clip_id>.json
```

- Idempotent: re-syncing updates existing files
- No database — pure file-based archive

## Suno Sources

```
GET https://studio-api.prod.suno.com/api/profiles/{handle}
    ?playlists_sort_by=upvote_count&clips_sort_by=created_at

GET https://studio-api.prod.suno.com/api/playlist/{suno_id}
    [?next_cursor=...]
```

## Conventions

- No comments in implementation code
- SOLID / YAGNI / DRY
- `services.py` owns all data access and sync logic
- `api.py` owns all outbound Suno HTTP calls
- 0.4s sleep between Suno requests

## Run

```powershell
.\.venv\Scripts\python.exe app.py
```

The same command serves both the beautiful player UI and the REST API.

## Deploy to Render

This app is ready for Render.com (Flask + Gunicorn + optional persistent disk for JSON data).

### One-click / Blueprint deploy (recommended)

1. Push this folder (or the whole repo) to GitHub.
2. In Render Dashboard → "New Blueprint Instance" → connect repo and select `pets/music/render.yaml`.
3. Or use the Render CLI:
   ```bash
   render blueprint launch
   ```

### Manual Web Service setup

- **Environment**: Python 3.11
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
- **Root Directory**: `pets/music` (if monorepo)
- Recommended: attach a **Persistent Disk** (1GB) mounted at `/data`
- Set Environment Variable:
  - `DATA_DIR` = `/data`
- Health check path: `/health`

### Environment Variables (Render)

| Key         | Value          | Notes |
|-------------|----------------|-------|
| DATA_DIR    | /data          | Required when using disk for persistence |
| PYTHON_VERSION | 3.11.0      | Match your runtime |

### Data Persistence

- Without a disk, all synced profiles/playlists are **ephemeral** (lost on every deploy/restart).
- With disk + `DATA_DIR=/data` the JSON archive survives restarts.
- After first deploy (empty disk): use the UI "sync" or call:
  ```bash
  curl -X POST https://your-app.onrender.com/profiles/load-from-txt
  ```
  or individual `/profiles/sync/` for specific handles.

### Notes

- Auto-sync from `profiles.txt` only runs for local `python app.py` (not under gunicorn).
- Use the explicit sync endpoints in production.
- The frontend (`player.html`) uses relative API calls and works out of the box.

## Production Notes

- Uses Gunicorn (see `Procfile` and `render.yaml`).
- `debug=True` only when running directly (`python app.py`).
- Respect `$PORT` automatically.