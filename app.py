from flask import Flask, jsonify, request, send_file
from pathlib import Path
import services
import api
import traceback
import threading
import json
import os

app = Flask(__name__)

@app.route('/')
def serve_ui():
    return send_file('player.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/profiles/', methods=['GET'])
def profile_list():
    return jsonify(services.list_profiles())

@app.route('/profiles/sync/', methods=['POST'])
def profile_sync():
    data = request.get_json() or {}
    handle = (data.get('handle') or '').strip()
    if not handle:
        return jsonify({'error': 'handle required'}), 400
    try:
        result = services.sync_profile(handle)
        services.add_handle_to_txt(handle)
        prof = services.get_profile(handle) or result
        return jsonify(prof), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/profiles/load-from-txt', methods=['POST'])
def load_from_txt():
    """Load and sync all handles from profiles.txt"""
    handles = services.load_handles_from_txt()
    if not handles:
        return jsonify({"error": "profiles.txt not found or empty", "handles": []}), 404

    synced = []
    errors = []
    for h in handles:
        try:
            services.sync_profile(h)
            synced.append(h)
        except Exception as e:
            errors.append({"handle": h, "error": str(e)})

    return jsonify({
        "total_found": len(handles),
        "synced": len(synced),
        "errors": len(errors),
        "synced_handles": synced,
        "error_details": errors
    })


@app.route('/profiles/<handle>/', methods=['GET'])
def profile_detail(handle):
    p = services.get_profile(handle)
    if not p:
        return jsonify({'error': 'not found'}), 404
    return jsonify(p)

@app.route('/profiles/<handle>/playlists/', methods=['GET'])
def playlist_list(handle):
    return jsonify(services.list_playlists(handle))

@app.route('/profiles/<handle>/playlists/<playlist_id>/', methods=['GET'])
def playlist_detail(handle, playlist_id):
    pl = services.get_playlist(handle, playlist_id)
    if not pl:
        return jsonify({'error': 'not found'}), 404
    return jsonify(pl)

@app.route('/profiles/<handle>/playlists/<playlist_id>/clips/', methods=['GET'])
def clip_list(handle, playlist_id):
    return jsonify(services.list_clips(handle, playlist_id))

@app.route('/profiles/<handle>/playlists/<playlist_id>/clips/<clip_id>/', methods=['GET'])
def clip_detail(handle, playlist_id, clip_id):
    c = services.get_clip(handle, playlist_id, clip_id)
    if not c:
        return jsonify({'error': 'not found'}), 404
    return jsonify(c)


# === Delete + Resync endpoints ===

@app.route('/profiles/<handle>/', methods=['DELETE'])
def delete_profile(handle):
    resync = request.args.get('resync', '1') not in ('0', 'false', 'no')
    result = services.delete_profile(handle, resync=resync)
    return jsonify(result), 200


@app.route('/profiles/<handle>/playlists/<playlist_id>/', methods=['DELETE'])
def delete_playlist(handle, playlist_id):
    resync = request.args.get('resync', '1') not in ('0', 'false', 'no')
    result = services.delete_playlist(handle, playlist_id, resync=resync)
    return jsonify(result), 200


@app.route('/profiles/<handle>/playlists/<playlist_id>/clips/<clip_id>/', methods=['DELETE'])
def delete_clip(handle, playlist_id, clip_id):
    resync = request.args.get('resync', '0') not in ('0', 'false', 'no')   # default false for clips (expensive)
    result = services.delete_clip(handle, playlist_id, clip_id, resync=resync)
    return jsonify(result), 200


# === Favorites endpoints for profiles ===
@app.route('/profiles/favorites/', methods=['GET'])
def favorites_list():
    all_profiles = services.list_profiles()
    favs = [p for p in all_profiles if p.get("is_favorite")]
    return jsonify(favs)


@app.route('/profiles/favorites/', methods=['POST'])
def add_favorite_route():
    data = request.get_json() or {}
    handle = (data.get('handle') or '').strip()
    if not handle:
        return jsonify({'error': 'handle required'}), 400
    ok = services.add_favorite(handle)
    return jsonify({"handle": handle, "added": ok}), 200


@app.route('/profiles/favorites/<handle>/', methods=['DELETE'])
def remove_favorite_route(handle):
    ok = services.remove_favorite(handle)
    return jsonify({"handle": handle, "removed": ok}), 200


def _safe_log(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("utf-8", errors="replace").decode("ascii", errors="replace"))
        except Exception:
            print("[log] (encoding error suppressed)")

def _auto_init_from_profiles_txt():
    profiles_txt_path = services.PROFILES_TXT

    handles = services.load_handles_from_txt(profiles_txt_path)

    if not handles:
        _safe_log("[INIT] No handles found.")
        _safe_log(f"[INIT] Expected file at: {profiles_txt_path}")
        return

    # Build robust "already done" set: both by handle and by any existing display_name folder
    existing_profiles = services.list_profiles()
    existing = {p.get("handle") for p in existing_profiles if p.get("handle")}
    for p in existing_profiles:
        dn = p.get("display_name")
        if dn:
            existing.add(api.sanitize(dn))  # treat sanitized display_name as "done" marker too

    to_sync = [h for h in handles if h not in existing]

    _safe_log(f"[INIT] {len(to_sync)} new profiles to sync")
    _safe_log(f"[INIT] {len(existing)} profiles already exist (skipped)")

    if not to_sync:
        _safe_log("[INIT] Nothing new to sync.")
        _safe_log("[INIT] ============================================\n")
        return

    for i, h in enumerate(to_sync, 1):
        _safe_log(f"\n[SYNC] ({i}/{len(to_sync)}) Checking @{h} via profile API...")

        try:
            # Light fetch to get the real display_name
            profile_data = api.fetch_profile(h)
            raw_display = profile_data.get("name") or h
            safe_name = api.sanitize(raw_display)
            target_folder = services.PROFILES_DIR / safe_name

            if target_folder.exists():
                _safe_log(f"[SYNC] ({i}/{len(to_sync)}) ⏭️  SKIP - Folder for display_name '{safe_name}' already exists")
                continue

            _safe_log(f"[SYNC] ({i}/{len(to_sync)}) Folder '{safe_name}' does not exist → full fetch...")
            services.sync_profile(h)
            _safe_log(f"[SYNC] ({i}/{len(to_sync)}) ✓ SUCCESS - @{h} (saved under '{safe_name}')")

        except Exception as e:
            _safe_log(f"[SYNC] ({i}/{len(to_sync)}) ✗ FAILED - @{h}")
            _safe_log(f"[SYNC] Error: {str(e)}")
            traceback.print_exc()

    _safe_log("\n[INIT] ============================================")
    _safe_log("[INIT] Auto-init from profiles.txt finished.")
    _safe_log("[INIT] ============================================\n")


if __name__ == '__main__':
    threading.Thread(target=_auto_init_from_profiles_txt, daemon=True).start()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
