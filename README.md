# YouTube Knowledge Pipeline

Turn videos from the creators / KOLs I follow into durable notes in my **Technical Brain** Obsidian vault — minimal time watching, maximum signal kept.

Reproducible and **local-first**: extraction runs on my Mac (residential IP), because YouTube blocks datacenter IPs and now gates some subtitles behind PO tokens. Everything after the transcript is automatic.

## What it does (two speeds)

```
channel / video URL
   │  fetch.py   (auto-detect: captions → else audio → Whisper)
   ▼
work/<creator>/…           info.json + .srt per video
   │  batch.py  →  youtube_to_source.py   (clean + file)
   ▼
<vault>/00_Resources/      one `type: source` note per video (transcript + TL;DR)
   │  you flag the keepers, then Claude distils
   ▼
<vault>/02_Notes/          atomic idea-notes, linked into the Creator Wisdom MOC
```

- **Capture** (cheap, whole-channel) — `fetch.py` pulls captions; if a video has none it grabs audio and transcribes with Whisper. `batch.py` cleans each transcript (dedupes rolling captions → ~1-min timestamped paragraphs) and writes a Source note.
- **Triage** — you pick which videos deserve deep notes.
- **Promote** — Claude distils flagged sources into atomic English notes (one idea each), attributing opinions and linking back. (The *processing gate*: a transcript stays a `source` note until reworded into a `note`.)

## Setup (one-time, macOS)

```bash
brew install yt-dlp ffmpeg
python3 -m pip install -r requirements.txt    # yt-dlp + mlx-whisper (Apple-Silicon Whisper)
cp config.example.json config.json            # then edit the vault path if needed
```

## Use

```bash
# whole channel, resumable (re-run later and it grabs only new uploads)
make capture URL="https://www.youtube.com/@edmundyong/videos"

# …or step by step
python3 src/fetch.py "<url>" --workdir work --archive work/archive.txt
python3 src/batch.py --workdir work --vault "<vault>" --domains creator-wisdom
```
Then ask Claude: *"distil idea-notes from the new Source notes."*

For a Korean channel you want at Whisper quality from the start, add `--force-whisper` to `fetch.py`.

## Demo (no network)

Proves the construction pipeline on a bundled sample transcript:

```bash
make demo
```
Cleans `demo/sample_transcript.srt` (note the rolling-caption duplicates) and writes a Source note into `demo/_demo_vault/00_Resources/`, then prints it.

## Layout

| Path | What |
|---|---|
| `src/fetch.py` | yt-dlp auto-detect fetch (captions → else audio → Whisper); channel-aware, resumable |
| `src/batch.py` | turns fetched transcripts into Source notes in the vault |
| `src/youtube_to_source.py` | the cleaner: dedupe rolling captions → ~1-min timestamped paragraphs → `type: source` note |
| `creators.md` | creator registry (per-creator defaults) |
| `config.example.json` | vault path + defaults |
| `demo/` | sample transcript + the `make demo` target |

## Notes & limits (2026)

- Extraction must run on a **residential IP** (your Mac), not a server or automation sandbox.
- If you hit *"Sign in to confirm you're not a bot"*, add `--cookies-from-browser safari` to yt-dlp, or install a PO-token provider plugin. Keep `yt-dlp` updated (`brew upgrade yt-dlp`) — it's a cat-and-mouse with YouTube.
- Korean auto-captions are weak; `fetch.py` falls back to Whisper `large-v3` when captions are missing, or use `--force-whisper` for a whole channel.
- The vault is knowledge-only; this repo is the tooling. House style → the vault's `99_Misc/02_Meta/Conventions.md`; system map → `Learning & Study/Second-Brain-Operating-Model.md`.
