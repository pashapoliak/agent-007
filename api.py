import requests
import json
import os
import re
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "json"))).resolve()
PROFILES_ROOT = DATA_DIR / "profiles"

def sanitize(name):
    if not name:
        return "unnamed"
    name = str(name).strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(" .")
    return name or "unnamed"

def ensure_dir(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)

def save_json(path, data):
    ensure_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch_profile(handle):
    url = "https://studio-api.prod.suno.com/api/profiles/" + handle
    params = {"playlists_sort_by": "upvote_count", "clips_sort_by": "created_at"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_playlist_page(playlist_id, cursor=None):
    url = "https://studio-api.prod.suno.com/api/playlist/" + playlist_id
    params = {"cursor": cursor} if cursor else {}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_all_clips(playlist_id):
    all_clips = []
    cursor = None
    while True:
        page = fetch_playlist_page(playlist_id, cursor)
        entries = page.get("playlist_clips", []) or page.get("clips", [])
        for entry in entries:
            clip = entry.get("clip") if isinstance(entry, dict) and "clip" in entry else entry
            if isinstance(clip, dict) and clip.get("id"):
                all_clips.append(clip)
        cursor = page.get("next_cursor")
        time.sleep(0.7)
        if not cursor:
            break
    return all_clips

def process_profile(handle):
    profile = fetch_profile(handle)
    raw_display = profile.get("display_name") or profile.get("handle") or handle
    safe_user = sanitize(raw_display)
    base_dir = PROFILES_ROOT / safe_user
    def _extract_avatar(p: dict) -> str | None:
        if not isinstance(p, dict):
            return None

        # Most common keys observed in Suno profile responses over time
        direct_keys = [
            "avatar_image_url",          # primary for many profiles
            "user_avatar_image_url",
            "avatar_url",
            "image_url",
            "avatar",
        ]

        for key in direct_keys:
            val = p.get(key)
            if isinstance(val, str) and val.startswith(("http://", "https://")):
                return val

        # Check nested user object (sometimes the avatar is here)
        user = p.get("user") if isinstance(p.get("user"), dict) else {}
        for key in ["avatar_url", "avatar_image_url", "image_url", "avatar"]:
            val = user.get(key)
            if isinstance(val, str) and val.startswith(("http://", "https://")):
                return val

        return None

    avatar_url = _extract_avatar(profile)
    upvote_count = profile.get("upvote_count", 0)

    save_json(base_dir / "profile.json", {
        "handle": handle,
        "display_name": raw_display,
        "avatar_image_url": avatar_url,
        "upvote_count": upvote_count,
    })

    # Top-level clips that come directly in the profile response
    # (user's own clips / uploads). Save them as main_playlist.json
    clips = profile.get("clips", []) or []
    if clips:
        main_playlist = {
            "id": "main",
            "name": "Main Clips",
            "clips": []
        }
        # Put main_playlist.json inside playlists/ for consistency
        main_clips_dir = base_dir / "playlists" / "main" / "clips"
        for clip in clips:
            cid = clip.get("id")
            if not cid:
                continue
            main_playlist["clips"].append({
                "id": cid,
                "title": clip.get("title"),
                "audio_url": clip.get("audio_url"),
                "image_large_url": clip.get("image_large_url") or clip.get("image_url"),
            })

            # Also save individual clip JSONs (consistent with regular playlists)
            clip_path = main_clips_dir / f"{cid}.json"
            if not clip_path.exists():
                minimal = {
                    "id": cid,
                    "title": clip.get("title"),
                    "audio_url": clip.get("audio_url"),
                    "image_large_url": clip.get("image_large_url") or clip.get("image_url"),
                }
                save_json(clip_path, minimal)
                time.sleep(0.05)

        save_json(base_dir / "playlists" / "main_playlist.json", main_playlist)

    playlists = profile.get("playlists", []) or []
    for pl in playlists:
        pl_id = pl.get("id")
        if not pl_id:
            continue
        raw_name = pl.get("name") or pl_id
        pl_meta_path = base_dir / "playlists" / f"{pl_id}.json"
        pl_meta = {
            "id": pl_id,
            "name": raw_name,
            "image_url": pl.get("image_url"),
            "num_total_results": pl.get("num_total_results") or pl.get("song_count", 0),
        }
        save_json(pl_meta_path, pl_meta)
        clips = fetch_all_clips(pl_id)
        clips_dir = base_dir / "playlists" / pl_id / "clips"
        for clip in clips:
            cid = clip.get("id")
            if not cid:
                continue
            clip_path = clips_dir / f"{cid}.json"
            if clip_path.exists():
                continue
            minimal = {
                "id": cid,
                "title": clip.get("title"),
                "audio_url": clip.get("audio_url"),
                "image_large_url": clip.get("image_large_url") or clip.get("image_url"),
            }
            save_json(clip_path, minimal)
            time.sleep(0.05)
    return safe_user

def validate_audio(base_dir):
    ok = 0
    fail = 0
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if not f.endswith(".json"):
                continue
            path = os.path.join(root, f)
            if os.path.basename(os.path.dirname(path)) != "clips":
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    clip = json.load(fh)
                url = clip.get("audio_url")
                if not url:
                    continue
                r = requests.head(url, timeout=8, allow_redirects=True)
                if r.status_code == 200:
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
    return {"ok": ok, "fail": fail}
