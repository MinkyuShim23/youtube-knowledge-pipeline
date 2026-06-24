# YouTube Knowledge Pipeline

Turn videos from the creators I follow into durable notes in my **Technical Brain** Obsidian
vault — minimal time watching, maximum signal kept. Detection + alerting run 24/7 on my
always-on server; the residential-IP-sensitive capture + distillation run on my Mac.

**Two hosts, by necessity:** YouTube bot-walls datacenter IPs for transcripts/audio, and the
vault lives on the Mac — so the OCI server can only *detect*, and the Mac does the *fetching +
writing*. An approval gate sits in between: nothing is captured until I approve it.

## Architecture

```
creator uploads
  └─[OCI] YouTube Upload Watch  (hourly, polls RSS — datacenter-safe)
       └─ 📹 Telegram alert  →  I reply  `yt approve <id>`  (or 👍)
            └─[OCI] youtube_approve.py  →  capture queue (JSON on the server)
                 └─[Mac] launchd drainer (auto_capture.py, on wake / every 30m):
                      fetch.py       →  Source note    in 00_Resources/
                      claude distil  →  atomic notes   in 02_Notes/  + Creator Wisdom MOC
                      clear queue
```

- **Detect + alarm (OCI / Hermes):** the `YouTube Upload Watch` cron polls each creator's RSS
  feed (`youtube.com/feeds/videos.xml?channel_id=…`, a plain XML endpoint that is *usually*
  datacenter-safe) and Telegrams only on genuinely new uploads, approve command inline. The watcher
  uses retry/backoff and only reports persistent feed failures, because YouTube RSS can return
  transient 404/500 responses from OCI/datacenter paths even when the channel ID is correct.
- **Approve (gate):** I reply `yt approve <id>`; Hermes runs `youtube_approve.py`, which appends
  the video to a capture queue. Nothing is fetched until I approve.
- **Capture + distil (Mac):** a `launchd` agent drains the queue — captures the transcript, then
  distils atomic notes via headless Claude, then clears the queue. **Sleep-tolerant:** `launchd`
  runs a missed job when the Mac next wakes, and an archive ledger makes capture idempotent, so a
  Mac that's often asleep loses nothing — it just catches up.

## The pieces (two repos)

| Where | File | Role |
|---|---|---|
| **Mac** (this repo) | `auto_capture.py` | **the drainer** — reads the OCI queue, captures + distils, clears it (what `launchd` runs) |
| | `src/fetch.py` | yt-dlp fetch (captions → else audio→Whisper); channel-aware, resumable |
| | `src/batch.py` | fetched transcripts → `type: source` notes in the vault |
| | `src/youtube_to_source.py` | cleaner: dedupe rolling captions → ~1-min timestamped paragraphs |
| | `pyproject.toml` / `uv.lock` | uv project (yt-dlp pinned) |
| **OCI** (`oci-free-arm-vm` repo) | `automations/scripts/youtube_upload_watch.py` | RSS watcher → Telegram alert (Hermes `no_agent` cron) |
| | `automations/scripts/youtube_approve.py` | approval → capture queue |
| | `automations/scripts/youtube_creators.json` | creators to watch (machine copy of `creators.md`) |
| | `automations/scripts/youtube_upload_watch.SETUP.md` | watcher ops doc |

State lives on the server: queue `~/.hermes/state/youtube_capture_queue.json`, seen-set
`~/.hermes/state/youtube_upload_seen.json`. The agent's approval protocol is in `~/.hermes/SOUL.md`.

## Day-to-day

1. Creator uploads → within the hour, a 📹 Telegram alert.
2. Reply `yt approve <id>` (the alert shows the exact command) — or 👍 / "approve".
3. Next time the Mac is awake, the Source note + atomic notes appear in the vault. Done.

## Setup (one-time, macOS) — uv

```bash
brew install ffmpeg deno          # system CLIs (deno solves YouTube's JS challenge)
uv sync                           # yt-dlp + lockfile (uv-managed — never pip/conda/venv directly)
```

**Headless Claude token** (for unattended distil — a long-lived token, NOT the interactive login):
```bash
claude setup-token                # copy the sk-ant-oat01-… it prints
mkdir -p ~/.config/youtube-knowledge
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' 'PASTE_TOKEN' > ~/.config/youtube-knowledge/claude.env
chmod 600 ~/.config/youtube-knowledge/claude.env
```

**Install the drainer (launchd):**
```bash
launchctl load -w ~/Library/LaunchAgents/com.minkyu.youtube-knowledge-drainer.plist
```

The OCI watcher + approval job register separately — see the SETUP doc in `oci-free-arm-vm`.
After editing the server's `SOUL.md`, restart Hermes: `systemctl --user restart hermes-gateway`.

## Operate

```bash
make drain        # drain the approval queue now (exactly what launchd runs)
make capture URL="https://www.youtube.com/@edmundyong/videos"   # whole channel, resumable (bypasses the gate)
make demo         # offline: prove the cleaner on a bundled sample transcript
```

Everything runs through `uv run` (see the Makefile). The drainer degrades safely: with no token
it still captures raw Source notes and flags them distil-pending — never a silent failure.

## Watcher ops / troubleshooting

On the OCI host:

```bash
python3 ~/.hermes/scripts/youtube_upload_watch.py --discover   # verify each RSS feed + latest videos
python3 ~/.hermes/scripts/youtube_upload_watch.py --dry-run    # render any pending alert without state writes
python3 ~/.hermes/scripts/youtube_upload_watch.py              # normal silent run when no new upload/problem
tail -n 50 ~/.hermes/logs/youtube_upload_watch.log
```

RSS failure policy (2026-06-24):

- Retry each feed with short backoff before counting a failure.
- If **all watched feeds fail in the same tick**, classify it as shared YouTube RSS edge/OCI-egress trouble, not N broken creators; alert only after **6 consecutive all-feed failed hourly runs**.
- If only one creator/feed fails while others succeed, alert that creator after **4 consecutive failed hourly runs**.
- Throttle repeat failure alerts to **24h**.
- Clear `errors` / `error_counts` / shared failure state immediately after a successful fetch.
- Treat one-off `HTTP 404` / `HTTP 500` as YouTube edge noise unless `--discover` keeps failing.

**Add a creator** (no code change):
1. Resolve the channel id: `yt-dlp --print "%(channel_id)s" "<any video URL>"`.
2. Add a row to `oci-free-arm-vm/automations/scripts/youtube_creators.json`
   (`{ "name": "...", "channel_id": "UC..." }`) and redeploy it to `~/.hermes/youtube_creators.json`.
3. Keep `creators.md` here in sync. The next watcher run **bootstraps the new creator silently**
   (records current uploads as seen — no historical spam), then alerts only on new ones.

## Notes & limits (2026)

- Extraction must run on a **residential IP** (the Mac), never the server — the server only detects (RSS).
- The Claude token expires; if distil starts failing, re-run `claude setup-token` and update
  `~/.config/youtube-knowledge/claude.env`. Capture is unaffected.
- *"Sign in to confirm you're not a bot"* → add `--cookies-from-browser safari` to yt-dlp, and keep
  it current: `uv lock --upgrade-package yt-dlp` (it's cat-and-mouse with YouTube).
- Korean auto-captions are weak; `fetch.py` falls back to Whisper, or use `--force-whisper`.
  mlx-whisper is the optional extra: `uv sync --extra whisper`.
- The vault is knowledge-only; this repo is the tooling. House style → vault
  `99_Misc/02_Meta/Conventions.md`; system map → `Learning & Study/Second-Brain-Operating-Model.md`.
