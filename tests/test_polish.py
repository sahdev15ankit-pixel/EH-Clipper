"""Tests for clipping.polish — pure logic, no GPU, no API keys. Run: pytest tests/"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipping.polish import review, tighten, web_broll  # noqa: E402

FPS = 30.0
W = lambda word, a, b: {"word": word, "start": a, "end": b}  # noqa: E731


def test_normalize_handles_punctuation_and_devanagari():
    assert tighten.normalize_word("Um,") == "um"
    assert tighten.normalize_word("हम्म…") == "हम्म"


def test_long_pause_is_shortened_not_removed():
    words = [W("hello", 0.0, 0.5), W("world", 3.0, 3.5)]
    keeps = tighten.plan_keep_intervals(words, 3.5, FPS, max_gap=0.7, keep_gap=0.18)
    kept = sum(b - a for a, b in keeps)
    assert len(keeps) == 2
    assert kept == pytest.approx(3.5 - (3.0 - 0.5 - 0.36), abs=0.07)  # ~0.36s of air left


def test_short_pause_untouched():
    words = [W("a", 0.0, 0.4), W("b", 0.8, 1.2)]
    assert len(tighten.plan_keep_intervals(words, 1.2, FPS)) == 1


def test_filler_removed_even_inside_short_gap():
    words = [W("so", 0.0, 0.3), W("um", 0.4, 0.8), W("yes", 0.9, 1.2)]
    keeps = tighten.plan_keep_intervals(words, 1.2, FPS)
    assert len(keeps) == 2
    assert all(not (a < 0.6 < b) for a, b in keeps)  # middle of the filler is gone


def test_keep_fillers_flag():
    words = [W("so", 0.0, 0.3), W("um", 0.4, 0.8), W("yes", 0.9, 1.2)]
    assert len(tighten.plan_keep_intervals(words, 1.2, FPS, drop_fillers=False)) == 1


def test_intervals_are_on_frame_grid_and_ordered():
    words = [W("a", 0.0, 0.5), W("um", 0.7, 1.1), W("b", 4.0, 4.4)]
    keeps = tighten.plan_keep_intervals(words, 5.0, FPS)
    for a, b in keeps:
        assert a * FPS == pytest.approx(round(a * FPS), abs=1e-6)
        assert b * FPS == pytest.approx(round(b * FPS), abs=1e-6)
    assert keeps == sorted(keeps)
    assert all(keeps[i][1] <= keeps[i + 1][0] for i in range(len(keeps) - 1))


def test_no_words_keeps_everything():
    assert tighten.plan_keep_intervals([], 10.0, FPS) == [(0.0, 10.0)]


def test_remap_shifts_later_words_and_drops_fillers():
    segs = [{"start": 0, "end": 5.6, "words": [W("hi", 0.0, 0.5), W("uh", 1.0, 1.3), W("later", 5.0, 5.6)]}]
    keeps = tighten.plan_keep_intervals(tighten.flatten_words(segs), 6.0, FPS)
    text, out = tighten.remap_segments(segs, keeps)
    words = [w for s in out for w in s["words"]]
    assert [w["word"] for w in words] == ["hi", "later"]
    assert words[1]["start"] < 5.0                      # pulled earlier by the cut
    assert words[1]["end"] - words[1]["start"] == pytest.approx(0.6, abs=0.04)  # duration preserved
    assert "later" in text and "uh" not in text


def test_remapper_is_monotonic():
    remap = tighten.make_remapper([(0.0, 1.0), (3.0, 4.0), (7.0, 8.0)])
    ts = [0.0, 0.5, 1.0, 2.0, 3.0, 3.5, 5.0, 7.0, 7.5, 8.0]
    mapped = [remap(t) for t in ts]
    assert mapped == sorted(mapped)
    assert remap(3.5) == pytest.approx(1.5)
    assert remap(7.5) == pytest.approx(2.5)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")
def test_render_keeps_video_and_audio_in_sync(tmp_path):
    src = str(tmp_path / "src.mp4")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src],
        check=True,
    )
    keeps = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]  # 12 hypothetical cuts' worth of drift risk, compressed
    dst = str(tmp_path / "out.mp4")
    tighten.render_tightened(src, dst, keeps, fps=30.0)
    frames = int(subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", dst],
        capture_output=True, text=True, check=True).stdout.strip())
    assert frames == 90  # exactly 3.0s at 30fps: no extra frame per interval


def test_review_page_escapes_html_and_writes_postpack(tmp_path):
    manifest = [{"rank": 1, "video_path": str(tmp_path / "c1.mp4"), "duration": 12.0,
                 "youtube_title_final": "<script>alert(1)</script>", "hastag": "#a #b"}]
    page = review.write_review_page(manifest, str(tmp_path))
    html = open(page, encoding="utf-8").read()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert (tmp_path / "postpack.json").exists()


def test_web_broll_picks_topic_matches_first_and_builds_channel_url():
    srcs = [{"name": "A", "channel": "https://x/@a", "topics": ["tiles"]},
            {"name": "B", "channel": "https://x/@b", "topics": ["kitchen"]}]
    assert web_broll.pick_sources(srcs, "modular kitchen")[0]["name"] == "B"
    assert web_broll.channel_search_url("https://x/@a/", "a b") == "https://x/@a/search?query=a+b"


def test_web_broll_does_nothing_without_sources(tmp_path):
    from types import SimpleNamespace
    cfg = SimpleNamespace(trusted_sources=str(tmp_path / "missing.json"), outputs_dir=str(tmp_path))
    assert web_broll.download_web_broll("x", "9:16", str(tmp_path / "o.mp4"), cfg) is False
