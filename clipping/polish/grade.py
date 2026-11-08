"""
clipping.polish.grade — colour grade + loudness normalisation for finished clips.

Runs after rendering, on each ``video_path`` in the render manifest. Loudness
only (no grade) copies the video stream untouched, so there is no extra
generation loss.
"""

from __future__ import annotations

import os
import subprocess

GRADES: dict[str, str] = {
    "none": "",
    "subtle": "eq=contrast=1.05:saturation=1.08",
    "punch": "eq=contrast=1.12:saturation=1.15:gamma=0.98,unsharp=5:5:0.4:5:5:0.0",
    "cinematic": (
        "colorbalance=rs=0.04:bs=-0.05:rm=0.03:bm=-0.04,"
        "eq=contrast=1.10:saturation=1.05,vignette=PI/7"
    ),
}

# Social-feed loudness: -14 LUFS is the usual Reels/Shorts/TikTok target; -16 is safer
# against platform re-normalisation. True-peak capped at -1.5 dBTP.
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def build_command(src: str, dst: str, grade: str, loudnorm: bool, encoder_args: list[str]) -> list[str]:
    vf = GRADES.get(grade, "")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src]
    if vf:
        cmd += ["-vf", vf, *encoder_args, "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    if loudnorm:
        cmd += ["-af", LOUDNORM, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        cmd += ["-c:a", "copy"]
    return cmd + ["-movflags", "+faststart", dst]


def polish_clips(manifest: list[dict], cfg, encoder_args: list[str] | None = None) -> None:
    """Grade / normalise every rendered clip in place."""
    grade = getattr(cfg, "grade", "none")
    loudnorm = getattr(cfg, "loudnorm", False)
    if grade == "none" and not loudnorm:
        return
    if grade not in GRADES:
        print(f"⚠️ Unknown grade '{grade}' — skipping (choose: {', '.join(GRADES)}).")
        return
    enc = encoder_args or ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    print(f"\n🎨 Polish: grade={grade}, loudnorm={'on' if loudnorm else 'off'}")
    for item in manifest:
        src = item.get("video_path")
        if not src or not os.path.exists(src):
            continue
        tmp = src + ".polish.mp4"
        try:
            subprocess.run(build_command(src, tmp, grade, loudnorm, enc), check=True)
            os.replace(tmp, src)
            print(f"   ✅ Rank {item.get('rank')}: {os.path.basename(src)}")
        except subprocess.CalledProcessError as e:
            print(f"   ⚠️ Rank {item.get('rank')}: polish failed ({e}); original kept.")
            if os.path.exists(tmp):
                os.remove(tmp)
