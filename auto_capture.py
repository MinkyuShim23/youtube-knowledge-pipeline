#!/usr/bin/env python3
"""Mac-side drainer for the YouTube Knowledge Pipeline (Stage 2).

Run by launchd (catches up on wake). For each video 마스터 approved (Hermes queued
it on the OCI box), this: captures the transcript into the Technical Brain (raw
Source note), distills atomic notes via headless Claude, then marks it done on OCI.

Capture needs no Claude. Distill needs a long-lived Claude token in
  ~/.config/youtube-knowledge/claude.env   ->  CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
Without the token, the video is still captured and flagged distill-pending — never a
silent failure. The OCI archive ledger makes capture idempotent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HOME = Path.home()
REPO = HOME / "Projects" / "personal" / "youtube-knowledge-pipeline"
VAULT = Path("/Users/minkyushim/Library/CloudStorage/OneDrive-Personal/Desktop/04_Technical Brain")
RESOURCES = VAULT / "00_Resources"
OCI = "free-arm-vm"
QUEUE_REMOTE = "/home/ubuntu/.hermes/state/youtube_capture_queue.json"
TOKEN_ENV = HOME / ".config" / "youtube-knowledge" / "claude.env"
CLAUDE = HOME / ".local" / "bin" / "claude"
ARCHIVE = REPO / "state" / "archive.txt"          # persistent capture-dedup ledger
LOG = Path.home() / "Library" / "Logs" / "youtube-knowledge" / "auto_capture.log"
LOCK = Path("/tmp/youtube_auto_capture.lock")

# launchd gives a minimal PATH; make sure brew tools + claude resolve.
# Run under `uv run` (launchd does this) so sys.executable + venv yt-dlp resolve.
# Append brew + ~/.local/bin for the system CLIs (deno/ffmpeg/claude) without shadowing the venv.
os.environ["PATH"] = os.environ.get("PATH", "/usr/bin:/bin") + f":/opt/homebrew/bin:{HOME}/.local/bin"


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")


def sh(args: list[str], timeout: int = 600, cwd: Path | None = None, env: dict | None = None):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          cwd=str(cwd) if cwd else None, env=env)


def read_queue() -> list[dict]:
    r = sh(["ssh", "-o", "ConnectTimeout=12", OCI, f"cat {QUEUE_REMOTE} 2>/dev/null || echo '{{}}'"], timeout=40)
    try:
        data = json.loads(r.stdout or "{}")
        return [it for it in data.get("queue", []) if it.get("status", "queued") == "queued"]
    except Exception as e:  # noqa: BLE001
        log(f"queue read/parse failed: {e}; raw={r.stdout[:200]!r}")
        return []


def clear_on_oci(vid: str) -> None:
    sh(["ssh", "-o", "ConnectTimeout=12", OCI,
        f"python3 ~/.hermes/scripts/youtube_approve.py --clear {vid}"], timeout=40)


def load_token() -> str | None:
    if not TOKEN_ENV.exists():
        return None
    for line in TOKEN_ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


DISTILL_PROMPT = """You are distilling a creator-wisdom YouTube transcript into a personal \
Obsidian knowledge vault (plain Markdown). The vault root is your working directory.

Source note to distill: 00_Resources/{note}

Steps:
1. Read 00_Resources/{note} (a transcript, possibly with an empty TL;DR/takeaways scaffold).
2. Read 99_Misc/01_Templates/Concept note.md for the atomic-note format, and skim existing \
filenames in 02_Notes/ so you EXTEND/LINK rather than duplicate an existing concept.
3. Create 2-5 ATOMIC concept notes in 02_Notes/ — each one durable, reusable idea (a mental \
model, principle, or tactic), NOT a video summary. English. Use the template's frontmatter \
(type: note) and ADD two provenance fields: source: "[[{stem}]]" and auto_distilled: {today}. \
Title each note by the idea, not the video.
4. If the Source note's TL;DR / key-takeaways are empty, fill them concisely.
5. Link the new notes into 01_MOC/Creator Wisdom — MOC.md under the right themes (wikilinks).
High-signal only; skip filler. Do not modify unrelated files. End by printing the list of \
note files you created."""


def capture(url: str) -> list[Path]:
    """Fetch + clean one video into a Source note. Returns new Source-note paths."""
    before = set(RESOURCES.glob("*.md")) if RESOURCES.exists() else set()
    tmp = Path(tempfile.mkdtemp(prefix="ytcap_"))
    try:
        r1 = sh([sys.executable, str(REPO / "src" / "fetch.py"), url, "--workdir", str(tmp),
                 "--langs", "en.*,ko.*", "--archive", str(ARCHIVE), "--no-whisper"],
                timeout=600, cwd=REPO)
        if r1.returncode != 0:
            log(f"  fetch rc={r1.returncode}: {(r1.stderr or r1.stdout)[-300:]}")
        r2 = sh([sys.executable, str(REPO / "src" / "batch.py"), "--workdir", str(tmp),
                 "--vault", str(VAULT), "--domains", "creator-wisdom"], timeout=300, cwd=REPO)
        if r2.returncode != 0:
            log(f"  batch rc={r2.returncode}: {(r2.stderr or r2.stdout)[-300:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    after = set(RESOURCES.glob("*.md")) if RESOURCES.exists() else set()
    return sorted(after - before)


def distill(note: Path, token: str) -> bool:
    env = dict(os.environ)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    prompt = DISTILL_PROMPT.format(note=note.name, stem=note.stem,
                                   today=datetime.now().strftime("%Y-%m-%d"))
    r = sh([str(CLAUDE), "-p", prompt, "--add-dir", str(VAULT),
            "--dangerously-skip-permissions"], timeout=900, cwd=VAULT, env=env)
    ok = r.returncode == 0 and "401" not in (r.stderr or "")
    log(f"  distill {'OK' if ok else 'FAILED'}: {(r.stdout or r.stderr or '')[-200:].strip()}")
    return ok


def main() -> int:
    if LOCK.exists():
        log("another run in progress (lock present); exiting")
        return 0
    LOCK.write_text(str(os.getpid()))
    try:
        queue = read_queue()
        if not queue:
            log("queue empty; nothing to do")
            return 0
        token = load_token()
        log(f"draining {len(queue)} approved video(s); distill={'on' if token else 'OFF (no token)'}")
        archive_ids = set()
        if ARCHIVE.exists():
            archive_ids = {ln.split()[-1] for ln in ARCHIVE.read_text().splitlines() if ln.strip()}
        for it in queue:
            vid, url = it["id"], it.get("url", f"https://www.youtube.com/watch?v={it['id']}")
            log(f"• {vid}  {it.get('title','')[:60]}")
            new_notes = capture(url)
            if not new_notes and vid not in archive_ids:
                log("  no Source note produced and not in archive — leaving queued for retry")
                continue
            if new_notes:
                log(f"  captured: {', '.join(n.name for n in new_notes)}")
                if token:
                    for n in new_notes:
                        distill(n, token)
                else:
                    log("  distill pending (no token) — raw Source note saved")
            else:
                log("  already in archive — clearing")
            clear_on_oci(vid)
        return 0
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
