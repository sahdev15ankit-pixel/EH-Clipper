"""
clipping.polish.review — outputs/review.html + postpack.json

One page with every rendered clip playable and its post text (titles, captions,
hashtags, YouTube description and tags) one click from the clipboard. Fully
static: open the file, nothing to host. Uses only fields the clipper already
writes to ``render_manifest.json``.
"""

from __future__ import annotations

import html
import json
import os

_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1a1a1a;--mute:#666;--line:#e3e0d8;--accent:#1f5f4a}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#eee;--mute:#999;--line:#333;--accent:#5fc3a0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
header{padding:20px 16px 4px;max-width:1100px;margin:auto}h1{font-size:20px;margin:0 0 4px}
header p{margin:0;color:var(--mute)}main{max-width:1100px;margin:auto;padding:12px 16px 48px;display:grid;gap:16px}
.clip{display:grid;grid-template-columns:minmax(0,260px) 1fr;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
@media(max-width:640px){.clip{grid-template-columns:1fr}}
video{width:100%;border-radius:8px;background:#000;max-height:460px}
h2{font-size:16px;margin:0 0 2px}.meta{color:var(--mute);font-size:13px;margin-bottom:10px}
.field{margin:0 0 10px}.field label{display:flex;justify-content:space-between;align-items:center;font-size:12px;
text-transform:uppercase;letter-spacing:.04em;color:var(--mute);margin-bottom:3px}
.box{border:1px solid var(--line);border-radius:8px;padding:8px 10px;white-space:pre-wrap;word-break:break-word;font-size:14px}
button{font:inherit;font-size:12px;border:1px solid var(--accent);color:var(--accent);background:transparent;border-radius:6px;padding:2px 10px;cursor:pointer}
button:hover{background:var(--accent);color:var(--bg)}
"""

_JS = """
function cp(btn){var t=btn.closest('.field').querySelector('.box').innerText;
(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(done,function(){var r=document.createRange();
r.selectNodeContents(btn.closest('.field').querySelector('.box'));var s=getSelection();s.removeAllRanges();s.addRange(r);
document.execCommand('copy');done()});function done(){var o=btn.textContent;btn.textContent='Copied';setTimeout(function(){btn.textContent=o},1200)}}
"""


def _field(label: str, value) -> str:
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    value = str(value or "").strip()
    if not value:
        return ""
    return (f'<div class="field"><label>{html.escape(label)}'
            f'<button onclick="cp(this)">Copy</button></label>'
            f'<div class="box">{html.escape(value)}</div></div>')


def build_postpack(manifest: list[dict]) -> list[dict]:
    pack = []
    for m in sorted(manifest, key=lambda x: x.get("rank", 0)):
        pack.append({
            "rank": m.get("rank"),
            "video": os.path.basename(m.get("video_path", "")),
            "duration_s": m.get("duration"),
            "title": m.get("youtube_title_final") or m.get("title_inggris") or m.get("title_indonesia", ""),
            "caption": m.get("tiktok_caption_final") or m.get("hastag", ""),
            "hashtags": m.get("hastag", ""),
            "youtube_description": m.get("youtube_description_final", ""),
            "youtube_tags": m.get("youtube_tags_final", []),
            "why_it_works": m.get("alasan", ""),
        })
    return pack


def write_review_page(manifest: list[dict], outputs_dir: str, source_label: str = "") -> str:
    pack = build_postpack(manifest)
    with open(os.path.join(outputs_dir, "postpack.json"), "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)

    cards = []
    for p in pack:
        dur = f"{p['duration_s']:.0f}s" if isinstance(p["duration_s"], (int, float)) else ""
        cards.append(
            '<section class="clip">'
            f'<video controls preload="metadata" src="{html.escape(p["video"])}"></video>'
            f'<div><h2>Clip {html.escape(str(p["rank"]))}</h2>'
            f'<div class="meta">{html.escape(dur)} · {html.escape(p["video"])}</div>'
            + _field("Title", p["title"])
            + _field("Caption (TikTok / Reels)", p["caption"])
            + _field("Hashtags", p["hashtags"])
            + _field("YouTube description", p["youtube_description"])
            + _field("YouTube tags", p["youtube_tags"])
            + _field("Why this moment", p["why_it_works"])
            + "</div></section>"
        )
    sub = f"{len(pack)} clips" + (f" · from {html.escape(source_label)}" if source_label else "")
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>EH-Clipper review</title><style>{_CSS}</style></head><body>"
        f"<header><h1>EH-Clipper review</h1><p>{sub}</p></header><main>"
        + "".join(cards) + f"</main><script>{_JS}</script></body></html>"
    )
    path = os.path.join(outputs_dir, "review.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path
