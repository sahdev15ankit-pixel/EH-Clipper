"""
clipping.polish.web_broll — opt-in B-roll from a trusted-source list via yt-dlp.

Enable with ``--broll-source web`` (web only) or ``--broll-source both`` (web
first, Pexels as fallback). The default stays ``pexels``.

Only channels you list in the trusted-sources JSON are searched. Nothing is
searched site-wide. Every clip used is logged to ``outputs/broll_credits.json``.

LICENSING: clips pulled from third-party channels are not licensed for you by
default. Only list channels you own, have written permission from, or that
publish under a licence allowing reuse. Pexels (the default) is licensed for
commercial use.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import urllib.parse

DEFAULT_SOURCES_FILE = "trusted_sources.json"
MAX_SOURCE_HEIGHT = 1080


def load_trusted_sources(path: str | None) -> list[dict]:
    """Each entry: {"name": str, "channel": "https://www.youtube.com/@handle", "topics": [str, ...]}"""
    path = path or DEFAULT_SOURCES_FILE
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [s for s in data if isinstance(s, dict) and s.get("channel")]


def pick_sources(sources: list[dict], query: str) -> list[dict]:
    """Prefer channels whose topics overlap the query; keep the rest as fallback."""
    q = query.lower()
    matched = [s for s in sources if any(t.lower() in q or q in t.lower() for t in s.get("topics", []))]
    rest = [s for s in sources if s not in matched]
    random.shuffle(rest)
    return matched + rest


def channel_search_url(channel: str, query: str) -> str:
    return channel.rstrip("/") + "/search?query=" + urllib.parse.quote_plus(query)


def search_channel(channel: str, query: str, limit: int = 3) -> list[dict]:
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": limit, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_search_url(channel, query), download=False)
    out = []
    for e in (info or {}).get("entries", []) or []:
        if e and e.get("id"):
            out.append({
                "id": e["id"],
                "title": e.get("title", ""),
                "url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
                "duration": e.get("duration") or 0,
            })
    return out


def fetch_section(url: str, start: float, seconds: float, out_path: str) -> bool:
    """Download only ``seconds`` of video (no audio) beginning at ``start``."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import download_range_func

    opts = {
        "quiet": True, "no_warnings": True,
        "format": f"bv*[height<={MAX_SOURCE_HEIGHT}]/b[height<={MAX_SOURCE_HEIGHT}]",
        "download_ranges": download_range_func(None, [(start, start + seconds)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": out_path,
        "overwrites": True,
    }
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
    return os.path.exists(out_path)


def conform(src: str, dst: str, rasio: str, seconds: float) -> bool:
    """Centre-crop to the target ratio, cap at ``seconds``, strip audio."""
    try:
        rw, rh = (float(x) for x in rasio.split(":"))
    except ValueError:
        rw, rh = 16.0, 9.0
    w, h = (1080, 1920) if rh > rw else (1920, 1080)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-t", f"{seconds:.2f}",
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", dst],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and os.path.exists(dst)


def _log_credit(cfg, entry: dict) -> None:
    path = os.path.join(getattr(cfg, "outputs_dir", "."), "broll_credits.json")
    rows = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        except Exception:
            rows = []
    rows.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def download_web_broll(query: str, rasio: str, output_filename: str, cfg, seconds: float = 5.0) -> bool:
    """Same contract as ``download_pexels_broll``: True when ``output_filename`` was written."""
    sources = load_trusted_sources(getattr(cfg, "trusted_sources", None))
    if not sources:
        print(f"      ℹ️ Web B-roll: no trusted sources in "
              f"'{getattr(cfg, 'trusted_sources', None) or DEFAULT_SOURCES_FILE}' — skipping.")
        return False

    seconds = max(2.0, min(float(seconds), 8.0))
    tmp = output_filename + ".raw.mp4"
    for src in pick_sources(sources, query):
        try:
            results = [r for r in search_channel(src["channel"], query) if (r["duration"] or 0) >= seconds + 2]
            if not results:
                continue
            pick = results[0]
            # Skip the intro/outro: start somewhere in the middle third.
            dur = pick["duration"] or (seconds * 6)
            start = random.uniform(dur * 0.15, max(dur * 0.15, dur * 0.7 - seconds))
            if fetch_section(pick["url"], start, seconds, tmp) and conform(tmp, output_filename, rasio, seconds):
                _log_credit(cfg, {
                    "query": query, "source": src.get("name", src["channel"]), "channel": src["channel"],
                    "title": pick["title"], "url": pick["url"], "start": round(start, 1), "seconds": seconds,
                })
                print(f"      ✅ Web B-roll '{query}' <- {src.get('name', src['channel'])}")
                return True
        except Exception as e:  # one bad channel must not stop the render
            print(f"      ⚠️ Web B-roll from {src.get('name', src['channel'])} failed: {e}")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return False
