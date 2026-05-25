import json
import re
import time
import shutil
import os
from pathlib import Path
import requests
import api

BASE_DIR = Path(__file__).resolve().parent
BASE_URL = "https://studio-api.prod.suno.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SLEEP = 0.4

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "json"))).resolve()
PROFILES_DIR = DATA_DIR / "profiles"
PROFILES_TXT = DATA_DIR / "profiles.txt"
FAVORITES_FILE = DATA_DIR / "favorites.json"

def sanitize(name: str) -> str:
    if not name:
        return "unnamed"
    s = re.sub(r'[\\/:*?"<>|]', "_", str(name).strip())
    s = s.strip(" .")
    return s or "unnamed"


def load_favorites() -> set:
    p = FAVORITES_FILE
    if not p.exists():
        return set()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {str(h).lower().strip().lstrip("@").split()[0] for h in data if h}
            return set()
    except Exception:
        return set()


def save_favorites(favs: set):
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(favs)), f, indent=2)


def is_favorite(handle: str) -> bool:
    h = str(handle or "").lower().strip().lstrip("@").split()[0]
    return bool(h) and h in load_favorites()


def add_favorite(handle: str) -> bool:
    h = str(handle or "").lower().strip().lstrip("@").split()[0]
    if not h:
        return False
    favs = load_favorites()
    if h in favs:
        return False
    favs.add(h)
    save_favorites(favs)
    print(f"[FAV] Added @{h}")
    return True


def remove_favorite(handle: str) -> bool:
    h = str(handle or "").lower().strip().lstrip("@").split()[0]
    if not h:
        return False
    favs = load_favorites()
    if h not in favs:
        return False
    favs.remove(h)
    save_favorites(favs)
    print(f"[FAV] Removed @{h}")
    return True


def fetch_profile(handle: str) -> dict:
    url = f"{BASE_URL}/profiles/{handle}"
    params = {"playlists_sort_by": "upvote_count", "clips_sort_by": "created_at"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_playlist_page(pid: str, cursor: str = "") -> dict:
    url = f"{BASE_URL}/playlist/{pid}"
    params = {"next_cursor": cursor} if cursor else {}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def sync_profile(handle: str):
    try:
        safe = api.process_profile(handle)
    except Exception as e:
        raise
    return {"handle": handle, "safe": safe}

def _find_profile_dir(handle: str) -> Path | None:
    h = handle.lower().strip()
    if not PROFILES_DIR.exists():
        return None
    for d in PROFILES_DIR.iterdir():
        if not d.is_dir():
            continue
        if d.name.lower() == h:
            return d
        pj = d / "profile.json"
        if pj.exists():
            try:
                p = json.loads(pj.read_text(encoding="utf-8"))
                if str(p.get("handle", "")).lower() == h or str(p.get("display_name", "")).lower() == h:
                    return d
            except Exception:
                pass
    return None

def list_profiles() -> list:
    if not PROFILES_DIR.exists():
        return []
    fav_set = load_favorites()
    res = []
    for d in sorted(PROFILES_DIR.iterdir()):
        if not d.is_dir():
            continue
        handle = d.name
        display = handle
        pj = d / "profile.json"
        if pj.exists():
            try:
                p = json.loads(pj.read_text(encoding="utf-8"))
                handle = p.get("handle") or handle
                display = p.get("display_name") or handle
            except Exception:
                pass
        plroot = d / "playlists"
        pcount = 0
        if plroot.exists():
            pcount = sum(
                1 for item in plroot.iterdir()
                if item.is_dir() and (item / "clips").exists()
            )

        avatar_url = None
        upvote_count = 0
        if pj.exists():
            try:
                p = json.loads(pj.read_text(encoding="utf-8"))
                # Prefer Suno's real field; fall back to old saved key for backward compat
                avatar_image_url = (
                    p.get("avatar_image_url")
                    or p.get("avatar_url")
                    or p.get("user_avatar_image_url")
                    or p.get("image_url")
                )
                upvote_count = p.get("upvote_count", 0)
            except Exception:
                pass

        hkey = str(handle or d.name).lower().strip().lstrip("@")
        is_fav = hkey in fav_set

        res.append({
            "id": handle,
            "handle": handle,
            "display_name": display,
            "playlist_count": pcount,
            "avatar_image_url": avatar_image_url,
            "upvote_count": upvote_count,
            "is_favorite": is_fav,
        })

    # Favorites first, then alpha by display_name
    res.sort(key=lambda x: (0 if x.get("is_favorite") else 1, (x.get("display_name") or x.get("handle") or "").lower()))
    return res

def get_profile(handle: str) -> dict | None:
    d = _find_profile_dir(handle)
    if not d:
        return None
    pj = d / "profile.json"
    if pj.exists():
        try:
            prof = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            prof = {"handle": handle, "display_name": d.name}
    else:
        prof = {"handle": handle, "display_name": d.name}
    prof["playlists"] = list_playlists(handle)
    return prof

def list_playlists(handle: str) -> list:
    d = _find_profile_dir(handle)
    if not d:
        return []
    plroot = d / "playlists"
    if not plroot.exists():
        return []
    seen = {}
    sanitized_from_meta = set()

    # Pass 1: meta JSON files (preferred source)
    for jf in plroot.glob("*.json"):
        if jf.name == "playlists.json":
            continue
        try:
            m = json.loads(jf.read_text(encoding="utf-8"))
            pid = m.get("id") or jf.stem
            name = m.get("name") or pid
            sname = sanitize(name)
            # Try both sanitized name folder and ID folder for clips
            cdir = plroot / sname / "clips"
            if not cdir.exists():
                cdir = plroot / pid / "clips"
            cnt = len(list(cdir.glob("*.json"))) if cdir.exists() else 0
            seen[pid] = {
                "id": pid, 
                "suno_id": pid, 
                "name": name, 
                "image_url": m.get("image_url"),
                "clip_count": cnt
            }
            sanitized_from_meta.add(sname)
        except Exception:
            pass

    # Pass 2: folders that have no matching meta JSON (legacy data)
    for item in plroot.iterdir():
        if item.is_dir() and (item / "clips").exists():
            folder_name = item.name
            if folder_name in sanitized_from_meta or folder_name in seen:
                continue  # already counted via meta JSON

            cnt = len(list((item / "clips").glob("*.json")))
            seen[folder_name] = {
                "id": folder_name, 
                "suno_id": folder_name, 
                "name": folder_name, 
                "image_url": None,
                "clip_count": cnt
            }

    # Enrich "Main Clips" (the top-level clips) with the profile avatar as icon
    main_pl = seen.get("main")
    if not main_pl:
        main_pl = next((p for p in seen.values() if str(p.get("name", "")).lower() == "main clips"), None)
    if main_pl and not main_pl.get("image_url"):
        pj = d / "profile.json"
        if pj.exists():
            try:
                prof = json.loads(pj.read_text(encoding="utf-8"))
                avatar = prof.get("avatar_image_url") or prof.get("avatar_url") or prof.get("user_avatar_image_url")
                if avatar:
                    main_pl["image_url"] = avatar
            except Exception:
                pass

    return sorted(seen.values(), key=lambda x: x.get("name", "").lower())

def list_clips(handle: str, playlist_id: str) -> list:
    d = _find_profile_dir(handle)
    if not d:
        return []
    plroot = d / "playlists"
    cdir = plroot / playlist_id / "clips"
    if not cdir.exists():
        meta = plroot / f"{playlist_id}.json"
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                sname = sanitize(m.get("name") or playlist_id)
                cdir = plroot / sname / "clips"
            except Exception:
                pass
    if not cdir or not cdir.exists():
        return []
    clips = []
    for jf in sorted(cdir.glob("*.json")):
        try:
            c = json.loads(jf.read_text(encoding="utf-8"))
            cid = c.get("id") or jf.stem
            clips.append({
                "id": cid,
                "suno_id": cid,
                "title": c.get("title") or "",
                "image_large_url": c.get("image_large_url") or c.get("image_url") or "",
                "audio_url": c.get("audio_url") or "",
            })
        except Exception:
            pass
    return clips

def get_clip(handle: str, playlist_id: str, clip_id: str) -> dict | None:
    for c in list_clips(handle, playlist_id):
        if c["id"] == clip_id or c["suno_id"] == clip_id:
            return c
    return None

def get_playlist(handle: str, playlist_id: str) -> dict | None:
    for p in list_playlists(handle):
        if p["id"] == playlist_id:
            return p
    return None


def load_handles_from_txt(path: str | Path | None = None) -> list:
    """Parse handles from profiles.txt. Supports both @handle and handle formats."""
    if path is None:
        path = PROFILES_TXT

    handles = []
    p = Path(path).resolve()
    print(f"[PARSER] Reading profiles.txt from: {p}")

    if not p.exists():
        print(f"[PARSER] File does NOT exist: {p}")
        return []

    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            handle = line.replace("@", "").strip().split()[0]
            if handle and handle not in handles:
                handles.append(handle)

    print(f"[PARSER] Extracted {len(handles)} unique handles")
    return handles


def _get_profiles_txt_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).resolve()
    return PROFILES_TXT.resolve()


def remove_handle_from_txt(handle: str, path: str | Path | None = None) -> bool:
    """Remove handle (case-insensitive, without @) from profiles.txt if present."""
    p = _get_profiles_txt_path(path)
    if not p.exists():
        return False

    h = handle.lower().strip().lstrip("@").split()[0]
    if not h:
        return False

    lines = []
    changed = False
    with open(p, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue
            existing = stripped.replace("@", "").strip().split()
            if existing and existing[0].lower() == h:
                changed = True
                continue
            lines.append(line)

    if changed:
        with open(p, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[PROFILES.TXT] Removed @{h} from {p}")
    return changed


def add_handle_to_txt(handle: str, path: str | Path | None = None) -> bool:
    """Append clean handle to profiles.txt if not already present."""
    p = _get_profiles_txt_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    h = handle.strip().lstrip("@").split()[0]
    if not h:
        return False

    existing = set()
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip().replace("@", "").strip().split()
                if s:
                    existing.add(s[0].lower())

    if h.lower() in existing:
        return False

    with open(p, "a", encoding="utf-8") as f:
        f.write(h + "\n")
    print(f"[PROFILES.TXT] Added @{h} to {p}")
    return True


def delete_profile(handle: str, resync: bool = True) -> dict:
    """Delete entire local profile folder and optionally re-fetch from Suno.
    Also removes the handle from profiles.txt so it won't be auto-initialized again.
    """
    print(f"[DELETE] profile {handle} (resync={resync})")
    remove_handle_from_txt(handle)
    remove_favorite(handle)

    d = _find_profile_dir(handle)
    deleted = False
    if d and d.exists():
        try:
            shutil.rmtree(d, ignore_errors=True)
            deleted = True
            print(f"[DELETE] removed folder {d}")
        except Exception as e:
            print(f"[DELETE] error removing folder: {e}")

    result = {"handle": handle, "deleted": deleted}

    if resync:
        try:
            safe = api.process_profile(handle)
            result["resynced"] = True
            result["safe_folder"] = safe
            print(f"[DELETE] resynced profile {handle}")
        except Exception as e:
            result["resynced"] = False
            result["error"] = str(e)
            print(f"[DELETE] resync failed: {e}")
    else:
        result["resynced"] = False

    return result


def delete_playlist(handle: str, playlist_id: str, resync: bool = True) -> dict:
    """Delete local playlist data (meta + clips dir) and optionally resync profile."""
    print(f"[DELETE] playlist {playlist_id} for {handle} (resync={resync})")
    d = _find_profile_dir(handle)
    if not d:
        print("[DELETE] profile dir not found")
        return {"error": "profile not found", "handle": handle}

    plroot = d / "playlists"
    removed = []

    # Remove meta file
    meta = plroot / f"{playlist_id}.json"
    if meta.exists():
        try:
            meta.unlink()
            removed.append(str(meta.name))
        except Exception:
            pass

    if playlist_id == "main":
        main_meta = plroot / "main_playlist.json"
        if main_meta.exists():
            try:
                main_meta.unlink()
                removed.append("main_playlist.json")
            except Exception:
                pass
        main_dir = plroot / "main"
        if main_dir.exists():
            try:
                shutil.rmtree(main_dir, ignore_errors=True)
                removed.append("main/")
            except Exception:
                pass
    else:
        sname = None
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                sname = sanitize(m.get("name") or playlist_id)
            except Exception:
                pass

        if not sname:
            for item in plroot.iterdir():
                if item.is_dir() and (item / "clips").exists():
                    if playlist_id in item.name or item.name in playlist_id:
                        sname = item.name
                        break

        if sname:
            target = plroot / sname
            if target.exists():
                try:
                    shutil.rmtree(target, ignore_errors=True)
                    removed.append(sname + "/")
                except Exception:
                    pass

        # New convention: clips stored under the playlist ID folder itself
        id_folder = plroot / playlist_id
        if id_folder.exists():
            try:
                shutil.rmtree(id_folder, ignore_errors=True)
                removed.append(playlist_id + "/")
            except Exception:
                pass

    result = {"handle": handle, "playlist_id": playlist_id, "removed": removed}

    if resync:
        try:
            api.process_profile(handle)
            result["resynced"] = True
            print(f"[DELETE] resynced after playlist delete {playlist_id}")
        except Exception as e:
            result["resynced"] = False
            result["error"] = str(e)
            print(f"[DELETE] resync after playlist delete failed: {e}")
    else:
        result["resynced"] = False

    return result


def delete_clip(handle: str, playlist_id: str, clip_id: str, resync: bool = False) -> dict:
    """Delete single clip JSON. Resync defaults to False."""
    print(f"[DELETE] clip {clip_id} from playlist {playlist_id} (resync={resync})")
    d = _find_profile_dir(handle)
    if not d:
        print("[DELETE] profile dir not found for clip delete")
        return {"error": "profile not found"}

    plroot = d / "playlists"
    cdir = plroot / playlist_id / "clips"

    if not cdir.exists():
        meta = plroot / f"{playlist_id}.json"
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                sname = sanitize(m.get("name") or playlist_id)
                cdir = plroot / sname / "clips"
            except Exception:
                pass

    deleted = False
    if cdir and cdir.exists():
        clip_file = cdir / f"{clip_id}.json"
        if clip_file.exists():
            try:
                clip_file.unlink()
                deleted = True
            except Exception:
                pass

    result = {
        "handle": handle,
        "playlist_id": playlist_id,
        "clip_id": clip_id,
        "deleted": deleted
    }

    if resync:
        try:
            api.process_profile(handle)
            result["resynced"] = True
            print(f"[DELETE] resynced after clip delete")
        except Exception as e:
            result["resynced"] = False
            result["error"] = str(e)
            print(f"[DELETE] resync after clip delete failed: {e}")
    else:
        result["resynced"] = False

    return result
