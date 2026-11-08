"""
clipping.polish.tighten — deterministic silence + filler-word cutting.

The upstream ``--silence-trim`` flag only *asks Gemini* to avoid dead air.
This module actually cuts it, from word-level Whisper timestamps, so every cut
lands on a word boundary instead of in the middle of speech.

Flow (called from runner.py right after transcription):
    1. ``plan_keep_intervals``  -> which parts of the source survive
    2. ``render_tightened``     -> one ffmpeg pass writes the tightened video
    3. ``remap_segments``       -> shift every word timestamp onto the new
                                   timeline and drop the filler words, so the
                                   transcript (and Gemini's timings) match the
                                   tightened video without re-transcribing.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

# Conservative on purpose: only sounds that are never real content.
# Extend with --filler-words (e.g. "matlab,basically") if you want more.
DEFAULT_FILLERS = frozenset(
    {
        "um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "hm", "mm", "mmm",
        "अं", "हम्म", "उम", "उम्म",
    }
)

_PUNCT = re.compile(r"[^\wऀ-ॿ]+")


def normalize_word(word: str) -> str:
    return _PUNCT.sub("", (word or "").lower())


def parse_filler_words(extra: str | None) -> frozenset[str]:
    """Merge the defaults with a comma-separated user list."""
    words = set(DEFAULT_FILLERS)
    for w in (extra or "").split(","):
        w = normalize_word(w)
        if w:
            words.add(w)
    return frozenset(words)


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def probe_video(path: str) -> tuple[float, float]:
    """Return (duration_seconds, fps) using ffprobe."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate:format=duration",
            "-of", "default=nw=1", path,
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    fps, duration = 30.0, 0.0
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k == "r_frame_rate" and "/" in v:
            n, d = v.split("/")
            if float(d):
                fps = float(n) / float(d)
        elif k == "duration":
            duration = float(v)
    return duration, fps


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def flatten_words(data_segmen: list[dict]) -> list[dict]:
    words: list[dict] = []
    for seg in data_segmen:
        for w in seg.get("words", []):
            words.append({"word": w["word"], "start": float(w["start"]), "end": float(w["end"])})
    words.sort(key=lambda w: w["start"])
    return words


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def plan_keep_intervals(
    words: list[dict],
    duration: float,
    fps: float,
    *,
    max_gap: float = 0.7,
    keep_gap: float = 0.18,
    min_cut: float = 0.12,
    drop_fillers: bool = True,
    fillers: frozenset[str] = DEFAULT_FILLERS,
) -> list[tuple[float, float]]:
    """
    Decide which source intervals to keep.

    * A pause longer than ``max_gap`` shrinks to ``2 * keep_gap`` of natural air.
    * Filler words are cut out entirely.
    * Cuts shorter than ``min_cut`` are ignored (they'd sound like a glitch).
    * Every boundary is snapped to the frame grid so video and audio, which are
      selected with the *same* intervals, cannot drift apart over many cuts.
    """
    if not words or duration <= 0:
        return [(0.0, duration)] if duration > 0 else []

    max_gap = max(max_gap, 2 * keep_gap + 0.05)
    spoken = [w for w in words if not (drop_fillers and normalize_word(w["word"]) in fillers)]
    cuts: list[tuple[float, float]] = []

    if drop_fillers:
        for w in words:
            if normalize_word(w["word"]) in fillers:
                cuts.append((w["start"], w["end"]))

    if spoken:
        if spoken[0]["start"] > max_gap:
            cuts.append((0.0, spoken[0]["start"] - keep_gap))
        for a, b in zip(spoken, spoken[1:]):
            if b["start"] - a["end"] > max_gap:
                cuts.append((a["end"] + keep_gap, b["start"] - keep_gap))
        if duration - spoken[-1]["end"] > max_gap:
            cuts.append((spoken[-1]["end"] + keep_gap, duration))

    cuts = [(max(0.0, a), min(duration, b)) for a, b in _merge(cuts) if b - a >= min_cut]

    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in cuts:
        if a > cursor:
            keeps.append((cursor, a))
        cursor = b
    if cursor < duration:
        keeps.append((cursor, duration))

    # Snap to the frame grid, then drop anything that collapsed to nothing.
    snapped = [(round(a * fps) / fps, round(b * fps) / fps) for a, b in keeps]
    return [(a, b) for a, b in _merge(snapped) if b - a >= 1.0 / fps]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _select_expr(intervals: list[tuple[float, float]], shift: float = 0.0) -> str:
    """Half-open [a, b) selection. ``between()`` is inclusive at both ends, which
    would keep one extra frame per interval and let video outgrow audio."""
    return "+".join(f"gte(t,{a - shift:.5f})*lt(t,{b - shift:.5f})" for a, b in intervals)


def render_tightened(
    src: str,
    dst: str,
    keeps: list[tuple[float, float]],
    *,
    fps: float = 30.0,
    video_encoder_args: list[str] | None = None,
) -> None:
    """One ffmpeg pass: keep only ``keeps`` and re-stamp timestamps."""
    if not keeps:
        raise ValueError("No intervals to keep.")
    # Frame times sit exactly on the grid the intervals were snapped to, so the
    # video window is shifted half a frame to be immune to float error. Audio is
    # sample-based and uses the exact window.
    vexpr = _select_expr(keeps, shift=0.5 / fps)
    aexpr = _select_expr(keeps)
    graph = (
        f"[0:v]select='{vexpr}',setpts=N/FRAME_RATE/TB[v];"
        f"[0:a]aselect='{aexpr}',asetpts=N/SR/TB[a]"
    )
    enc = video_encoder_args or ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]
    # The expression can be thousands of characters: pass it as a script file.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(graph)
        script = f.name
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                "-filter_complex_script", script, "-map", "[v]", "-map", "[a]",
                *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", dst,
            ],
            check=True,
        )
    finally:
        os.unlink(script)


# ---------------------------------------------------------------------------
# Timestamp remapping
# ---------------------------------------------------------------------------

def make_remapper(keeps: list[tuple[float, float]]):
    """Return f(t_old) -> t_new for a timeline with the gaps between ``keeps`` removed."""
    starts, offsets, total = [], [], 0.0
    for a, b in keeps:
        starts.append(a)
        offsets.append(total - a)  # new = old + offset inside this interval
        total += b - a

    def remap(t: float) -> float:
        new = 0.0
        for (a, b), off in zip(keeps, offsets):
            if t < a:
                return new  # t was inside a removed region: snap to its edge
            if t <= b:
                return t + off
            new = b + off
        return new

    return remap


def remap_segments(
    data_segmen: list[dict],
    keeps: list[tuple[float, float]],
    *,
    drop_fillers: bool = True,
    fillers: frozenset[str] = DEFAULT_FILLERS,
) -> tuple[str, list[dict]]:
    """Shift word times onto the tightened timeline; return (transcript, segments)."""
    remap = make_remapper(keeps)
    out: list[dict] = []
    for seg in data_segmen:
        words = []
        for w in seg.get("words", []):
            if drop_fillers and normalize_word(w["word"]) in fillers:
                continue
            words.append({"word": w["word"], "start": remap(float(w["start"])), "end": remap(float(w["end"]))})
        if words:
            out.append({"start": words[0]["start"], "end": words[-1]["end"], "words": words})
    transcript = "".join(
        f"[{s['start']:.1f} - {s['end']:.1f}] {' '.join(w['word'] for w in s['words'])}\n" for s in out
    )
    return transcript, out


# ---------------------------------------------------------------------------
# Entry point used by runner.py
# ---------------------------------------------------------------------------

def tighten_source(
    video_path: str,
    data_segmen: list[dict],
    cfg,
    *,
    video_encoder_args: list[str] | None = None,
) -> tuple[str, list[dict], str] | None:
    """
    Cut silence / fillers out of ``video_path``.

    Returns ``(new_video_path, new_segments, new_transcript)`` or ``None`` when
    there was nothing worth cutting (the caller then carries on unchanged).
    """
    duration, fps = probe_video(video_path)
    fillers = parse_filler_words(getattr(cfg, "filler_words", None))
    drop_fillers = not getattr(cfg, "keep_fillers", False)

    keeps = plan_keep_intervals(
        flatten_words(data_segmen), duration, fps,
        max_gap=getattr(cfg, "silence_max_gap", 0.7),
        drop_fillers=drop_fillers, fillers=fillers,
    )
    kept = sum(b - a for a, b in keeps)
    removed = duration - kept
    if not keeps or removed < 0.5:
        print(f"      ✂️ Tighten: nothing worth cutting ({removed:.1f}s) — skipped.")
        return None

    dst = os.path.splitext(video_path)[0] + "_tight.mp4"
    print(f"      ✂️ Tighten: {duration:.1f}s -> {kept:.1f}s "
          f"(removed {removed:.1f}s across {len(keeps) - 1} cuts)")
    render_tightened(video_path, dst, keeps, fps=fps, video_encoder_args=video_encoder_args)
    transcript, segments = remap_segments(data_segmen, keeps, drop_fillers=drop_fillers, fillers=fillers)
    return dst, segments, transcript
