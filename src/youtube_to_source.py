#!/usr/bin/env python3
"""
youtube_to_source.py — turn a raw YouTube transcript + metadata into a clean
`type: source` note in the Technical Brain vault (00_Resources/).

Part of the YouTube Knowledge System. See WORKFLOW.md.

Why a script: the automation sandbox cannot reach YouTube, so the transcript is
acquired either
  (A) by Claude via the browser (Claude-in-Chrome reads the "Show transcript" panel), or
  (B) manually  (open video -> "..." -> Show transcript -> Copy -> paste into a .txt).
This script does the DETERMINISTIC part — clean the transcript (drop rolling-caption
duplicates, merge into ~1-min timestamped paragraphs) and write the Source note from
the template. The THINKING part (TL;DR, key takeaways, atomic idea-notes) is done by
Claude on top of the stored transcript.

Stdlib only — runs anywhere with Python 3.8+.

Usage
-----
  uv run youtube_to_source.py \
      --meta meta.json \
      --transcript raw.txt \
      [--vault "/Users/.../04 Technical Brain"] \
      [--interval 60] [--tldr "..."] [--dry-run]

meta.json keys (all optional strings; missing -> left blank):
  title, creator, channel, channel_url, url, published, duration, language
"""

import argparse
import datetime
import json
import re
from pathlib import Path

DEFAULT_VAULT = (
    "/Users/minkyushim/Library/CloudStorage/OneDrive-Personal/Desktop/04_Technical Brain"
)
RESOURCES = "00_Resources"

TS_LINE = re.compile(r"^(\d{1,2}:\d{2}(?::\d{2})?)(?:\.\d+)?$")
CUE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})\s*-->")
INLINE_TAG = re.compile(r"<[^>]+>")
LEAD_DASH = re.compile(r"^[-–•]\s*")


def to_seconds(ts: str) -> int:
    ts = ts.replace(",", ".")
    parts = [float(p) for p in ts.split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        h, m, s = 0, 0, parts[0]
    return int(h * 3600 + m * 60 + s)


def fmt_ts(sec: int) -> str:
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def clean(t: str) -> str:
    t = INLINE_TAG.sub("", t)
    t = LEAD_DASH.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_segments(raw: str):
    """Return list of (seconds|None, text) from VTT/SRT, panel paste, or plain prose."""
    lines = [l.rstrip("\n") for l in raw.splitlines()]

    # --- VTT / SRT (cues contain '-->') ---
    if any("-->" in l for l in lines):
        segs, cur_sec, buf = [], None, []
        for l in lines:
            if "-->" in l:
                if buf:
                    segs.append((cur_sec, " ".join(buf)))
                    buf = []
                m = CUE.search(l)
                cur_sec = to_seconds(m.group(1)) if m else None
            elif (
                not l.strip()
                or l.strip().isdigit()
                or l.strip().upper() == "WEBVTT"
                or l.startswith(("Kind:", "Language:", "NOTE"))
            ):
                continue
            else:
                c = clean(l)
                if c:
                    buf.append(c)
        if buf:
            segs.append((cur_sec, " ".join(buf)))
        return segs

    # --- YouTube transcript-panel paste / plain prose ---
    segs, i = [], 0
    while i < len(lines):
        l = lines[i].strip()
        if not l:
            i += 1
            continue
        m = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)[\t ]+(.*)$", l)  # "0:12  text"
        if m:
            segs.append((to_seconds(m.group(1)), clean(m.group(2))))
            i += 1
            continue
        if TS_LINE.match(l):  # lone timestamp, text on next line
            sec = to_seconds(l)
            if i + 1 < len(lines):
                c = clean(lines[i + 1])
                if c:
                    segs.append((sec, c))
                i += 2
            else:
                i += 1
            continue
        segs.append((None, clean(l)))  # plain prose
        i += 1
    return segs


def dedupe(segs):
    """Drop consecutive identical lines (the common rolling-caption duplication)."""
    out, prev = [], None
    for sec, t in segs:
        key = t.lower()
        if key and key == prev:
            continue
        out.append((sec, t))
        prev = key
    return out


def _norm(w):
    """Lowercase + strip surrounding punctuation, so 'problem.' matches 'problem,' when detecting overlaps."""
    return re.sub(r"[^\w]", "", w.lower())


def trim_rolling(segs, min_overlap=3):
    """Remove the rolling word-overlap YouTube auto-captions leave between cues:
    each cue repeats the tail of the previous one. Append only the new suffix.
    Only trims overlaps of >= min_overlap words to avoid clobbering coincidental
    short repeats. Punctuation-insensitive. No-op on already-clean transcript-panel text."""
    out, prev_words = [], []
    for sec, t in segs:
        words = t.split()
        maxk = min(len(prev_words), len(words))
        k = 0
        for kk in range(maxk, min_overlap - 1, -1):
            if [_norm(w) for w in prev_words[-kk:]] == [_norm(w) for w in words[:kk]]:
                k = kk
                break
        new_words = words[k:]
        if new_words:
            out.append((sec, " ".join(new_words)))
        prev_words = words if words else prev_words
    return out


def paragraphs(segs, interval=60) -> str:
    if not segs:
        return ""
    timed = any(s is not None for s, _ in segs)
    if not timed:
        text = " ".join(t for _, t in segs)
        sents = re.split(r"(?<=[.!?。！？])\s+", text)
        blocks = [" ".join(sents[j : j + 6]).strip() for j in range(0, len(sents), 6)]
        return "\n\n".join(b for b in blocks if b)
    blocks, bucket, start, cur_sec, buf = [], None, 0, 0, []
    for sec, t in segs:
        s = sec if sec is not None else cur_sec
        cur_sec = s
        b = s // interval
        if bucket is None:
            bucket, start = b, s
        if b != bucket and buf:
            blocks.append((start, " ".join(buf)))
            buf, bucket, start = [], b, s
        buf.append(t)
    if buf:
        blocks.append((start, " ".join(buf)))
    return "\n\n".join(f"**[{fmt_ts(st)}]** {txt}" for st, txt in blocks)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120].rstrip(" .")


def main():
    ap = argparse.ArgumentParser(description="Build a Source note from a YouTube transcript.")
    ap.add_argument("--meta", required=True, help="path to meta.json")
    ap.add_argument(
        "--transcript", required=True, help="path to raw transcript (vtt/srt/panel/plain)"
    )
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    ap.add_argument("--domains", default="", help="comma-separated domains, e.g. creator-wisdom")
    ap.add_argument("--interval", type=int, default=60, help="seconds per transcript paragraph")
    ap.add_argument("--tldr", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    meta = json.loads(Path(a.meta).read_text(encoding="utf-8"))
    raw = Path(a.transcript).read_text(encoding="utf-8")

    segs = trim_rolling(dedupe(parse_segments(raw)))
    body = paragraphs(segs, a.interval)
    wc = sum(len(t.split()) for _, t in segs)

    title = meta.get("title", "").strip()
    creator = meta.get("creator", "").strip()
    full_title = (
        f"{creator} — {title}" if creator and title else (title or creator or "Untitled video")
    )
    today = datetime.date.today().isoformat()

    # The Technical Brain is deliberately tag-free — `domains` + MOCs + links do the
    # organizing (see the vault Conventions). Do NOT add a `tags:` frontmatter field here.
    doms = [d.strip() for d in a.domains.split(",") if d.strip()]
    domains_yaml = "[" + ", ".join(doms) + "]"

    chan, chan_url = meta.get("channel", "").strip(), meta.get("channel_url", "").strip()
    chan_md = f"[{chan}]({chan_url})" if chan and chan_url else (chan or "")

    note = f"""---
type: source
media: youtube
aliases: []
domains: {domains_yaml}
status: to-distill
source: {meta.get("url", "")}
updated: {today}
---

# {full_title}

> [!info] Source
> **Creator:** {creator} · **Channel:** {chan_md}
> **Published:** {meta.get("published", "")} · **Duration:** {meta.get("duration", "")} · **Language:** {meta.get("language", "")}
> **URL:** {meta.get("url", "")}
> **Captured:** {today}

## TL;DR
{a.tldr or "<2–4 sentences — filled by Claude from the transcript.>"}

## Key takeaways
-

## Extracted notes
> Atomic ideas distilled from this source into `02_Notes/` — link both ways.
- [[ ]]

## Transcript
%% Verbatim, lightly cleaned (rolling-caption duplicates removed, merged into ~{a.interval}s paragraphs). Raw resource — notes above are distilled from it. Word count ≈ {wc}. %%

{body}
"""

    fname = sanitize_filename(full_title) + ".md"
    dest = Path(a.vault) / RESOURCES / fname
    if a.dry_run:
        print(f"[dry-run] would write: {dest}")
        print(f"[dry-run] {len(segs)} segments · ≈{wc} transcript words")
        print("---- preview ----")
        print(note[:1800])
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(note, encoding="utf-8")
    print(f"Wrote {dest}")
    print(f"Segments: {len(segs)} · transcript words ≈ {wc}")


if __name__ == "__main__":
    main()
