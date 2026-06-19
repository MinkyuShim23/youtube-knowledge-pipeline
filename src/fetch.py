#!/usr/bin/env python3
"""
fetch.py — pull transcripts for a video, playlist, or whole channel, AUTO-DETECTING
captions vs audio. Part of the YouTube Knowledge Pipeline (see ../README.md).

Run this on your own Mac (residential IP): YouTube blocks datacenter IPs and now gates
some subtitles behind PO tokens, so local + home network is the reliable path.

Per video:
  * captions exist (manual or auto, in a wanted language) -> download them (cheap)
  * no captions  (or --force-whisper)                     -> download audio + Whisper (mlx-whisper)

Outputs into <workdir>/<uploader>/ :
  <date>--<title> [<id>].info.json     metadata (from yt-dlp)
  <date>--<title> [<id>].<lang>.srt    transcript

Dedup / resume with --archive (yt-dlp --download-archive). batch.py turns these into Source notes.

Requires: yt-dlp, ffmpeg.  Whisper fallback also needs: mlx-whisper (Apple Silicon).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

OUT_TMPL = "%(uploader)s/%(upload_date)s--%(title)s [%(id)s].%(ext)s"
ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,})\]")


def sh(cmd):
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd).returncode


def has(binary):
    return shutil.which(binary) is not None


def metadata_pass(url, workdir, langs, archive, sleep, want_subs):
    """One yt-dlp call: always write info.json; also write captions unless we're forcing Whisper."""
    cmd = ["yt-dlp", "--ignore-errors", "--skip-download", "--write-info-json",
           "--sleep-requests", str(sleep), "-o", str(workdir / OUT_TMPL)]
    if want_subs:
        cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", langs, "--convert-subs", "srt"]
    if archive:
        # --force-write-archive is REQUIRED: with --skip-download, yt-dlp won't record the
        # archive on its own, so dedup/resume silently breaks without this.
        cmd += ["--download-archive", str(archive), "--force-write-archive"]
    cmd.append(url)
    sh(cmd)


def srt_for(info_path):
    """Return an .srt sibling sharing this video's [id], if present."""
    m = ID_RE.search(info_path.name)
    vid = m.group(1) if m else None
    for srt in sorted(info_path.parent.glob("*.srt")):
        if vid and f"[{vid}]" in srt.name:
            return srt
    return None


def whisper_pass(workdir, whisper_model, lang):
    """For every video with metadata but no .srt, download audio and transcribe locally."""
    pending = [i for i in sorted(workdir.rglob("*.info.json")) if not srt_for(i)]
    if not pending:
        return
    if not has("mlx_whisper"):
        print(f"!! {len(pending)} video(s) have no captions and mlx_whisper is not installed — "
              f"skipping. Install with: uv sync --extra whisper", file=sys.stderr)
        return
    for info in pending:
        meta = json.loads(info.read_text(encoding="utf-8"))
        vid = meta.get("id")
        if not vid:
            continue
        base = str(info)[: -len(".info.json")]          # path without the .info.json suffix
        mp3 = base + ".mp3"
        print(f"-- no captions for [{vid}] -> audio + Whisper")
        if sh(["yt-dlp", "-x", "--audio-format", "mp3", "-o", base + ".%(ext)s",
               f"https://www.youtube.com/watch?v={vid}"]) != 0:
            continue
        wl = lang or (meta.get("language") or "")
        cmd = ["mlx_whisper", mp3, "--model", whisper_model, "-f", "srt",
               "--output-dir", str(Path(base).parent)]
        if wl:
            cmd += ["--language", wl.split("-")[0]]
        sh(cmd)
        Path(mp3).unlink(missing_ok=True)                # never keep the audio


def main():
    ap = argparse.ArgumentParser(description="Fetch YouTube transcripts (auto-detect captions vs Whisper).")
    ap.add_argument("url", help="video, playlist, or channel URL, e.g. https://www.youtube.com/@handle/videos")
    ap.add_argument("--workdir", default="work")
    ap.add_argument("--langs", default="en.*,ko.*", help="yt-dlp --sub-langs filter")
    ap.add_argument("--archive", default="", help="download-archive file for dedup/resume")
    ap.add_argument("--whisper-model", default="mlx-community/whisper-large-v3-turbo")
    ap.add_argument("--lang", default="", help="force Whisper language (e.g. ko); else auto")
    ap.add_argument("--sleep", type=int, default=2, help="seconds between requests (politeness)")
    ap.add_argument("--force-whisper", action="store_true",
                    help="ignore captions; transcribe every video with Whisper (quality, e.g. a Korean channel)")
    ap.add_argument("--no-whisper", action="store_true", help="captions only; skip the audio fallback")
    a = ap.parse_args()

    if not has("yt-dlp"):
        sys.exit("yt-dlp not found. Install with: brew install yt-dlp ffmpeg")
    workdir = Path(a.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    archive = Path(a.archive) if a.archive else None

    metadata_pass(a.url, workdir, a.langs, archive, a.sleep, want_subs=not a.force_whisper)
    if not a.no_whisper:
        whisper_pass(workdir, a.whisper_model, a.lang)
    print(f"\nfetch complete -> {workdir}\nnext: uv run src/batch.py --workdir {a.workdir}")


if __name__ == "__main__":
    main()
