#!/usr/bin/env python3
"""
batch.py — turn a workdir of fetched transcripts into `type: source` notes in the vault.

For every <name>.info.json that has a matching <name>.<lang>.srt, build a meta.json and
run youtube_to_source.py (the cleaner) to write the Source note into <vault>/00_Resources/.

Pair with fetch.py's --archive so you never re-fetch. See ../README.md.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,})\]")


def srt_for(info_path):
    m = ID_RE.search(info_path.name)
    vid = m.group(1) if m else None
    for srt in sorted(info_path.parent.glob("*.srt")):
        if vid and f"[{vid}]" in srt.name:
            return srt
    return None


def fmt_date(yyyymmdd):
    if yyyymmdd and len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    return yyyymmdd or ""


def fmt_dur(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description="Build Source notes from fetched transcripts.")
    ap.add_argument("--workdir", default="work")
    ap.add_argument("--vault", default="", help="override vault path (else the cleaner's default)")
    ap.add_argument("--domains", default="creator-wisdom")
    ap.add_argument("--tags", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    wd = Path(a.workdir)
    infos = sorted(wd.rglob("*.info.json"))
    if not infos:
        sys.exit(f"no .info.json under {wd} — run fetch.py first")

    made = 0
    for info in infos:
        srt = srt_for(info)
        if not srt:
            print(f"skip (no transcript yet): {info.name}")
            continue
        d = json.loads(info.read_text(encoding="utf-8"))
        meta = {
            "title": d.get("title", ""),
            "creator": d.get("uploader", ""),
            "channel": d.get("uploader", ""),
            "channel_url": d.get("uploader_url") or d.get("channel_url", ""),
            "url": d.get("webpage_url", ""),
            "published": fmt_date(d.get("upload_date", "")),
            "duration": fmt_dur(d.get("duration")),
            "language": d.get("language") or "",
        }
        meta_path = info.with_name(info.name.replace(".info.json", ".meta.json"))
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [
            sys.executable,
            str(HERE / "youtube_to_source.py"),
            "--meta",
            str(meta_path),
            "--transcript",
            str(srt),
            "--domains",
            a.domains,
        ]
        if a.tags:
            cmd += ["--tags", a.tags]
        if a.vault:
            cmd += ["--vault", a.vault]
        if a.dry_run:
            cmd += ["--dry-run"]
        if subprocess.run(cmd).returncode == 0:
            made += 1

    print(
        f"\n{made} Source note(s) written. "
        f"Next: ask Claude to distil idea-notes from the new Source notes."
    )


if __name__ == "__main__":
    main()
