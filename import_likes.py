import json
import time
from pathlib import Path
import requests

import api


def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("utf-8", errors="replace").decode("ascii", errors="replace"))
        except Exception:
            print("[log] (encoding error suppressed)")

BASE = Path(__file__).resolve().parent
LIKES_JSON = BASE / "json" / "likes.json"
PROFILE_DIR = BASE / "json" / "profiles" / "Barmaglot"
LIKES_META = PROFILE_DIR / "playlists" / "likes.json"
LIKES_CLIPS_DIR = PROFILE_DIR / "playlists" / "likes" / "clips"

def fetch_clip(clip_id: str):
    url = f"https://studio-api.prod.suno.com/api/clip/{clip_id}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    with open(LIKES_JSON, encoding="utf-8") as f:
        data = json.load(f)

    clip_ids = data.get("filters", {}).get("ids", {}).get("clipIds", [])
    _safe_print(f"Found {len(clip_ids)} clip IDs in likes.json")

    # Ensure meta for the likes playlist
    if not LIKES_META.exists():
        api.save_json(LIKES_META, {
            "id": "likes",
            "name": "Likes",
            "image_url": None,
            "num_total_results": len(clip_ids),
        })
        _safe_print("Created likes.json meta")

    saved = 0
    skipped = 0
    for i, cid in enumerate(clip_ids, 1):
        clip_path = LIKES_CLIPS_DIR / f"{cid}.json"
        if clip_path.exists():
            skipped += 1
            _safe_print(f"[{i}/{len(clip_ids)}] SKIP existing {cid}")
            continue

        try:
            clip = fetch_clip(cid)
            minimal = {
                "id": cid,
                "title": clip.get("title"),
                "audio_url": clip.get("audio_url"),
                "image_large_url": clip.get("image_large_url") or clip.get("image_url"),
            }
            api.save_json(clip_path, minimal)
            saved += 1
            _safe_print(f"[{i}/{len(clip_ids)}] SAVED {cid} - {minimal['title']}")
        except Exception as e:
            _safe_print(f"[{i}/{len(clip_ids)}] ERROR {cid}: {e}")

        time.sleep(0.6)

    _safe_print(f"Done. Saved: {saved}, Skipped: {skipped}")

if __name__ == "__main__":
    main()
