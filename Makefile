# YouTube Knowledge Pipeline — common tasks (uv-managed).
# Override on the command line, e.g.  make capture URL="https://www.youtube.com/@edmundyong/videos"

VAULT ?= /Users/minkyushim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Technical Brain
# scratch transcripts (gitignored, safe to delete)
WORK ?= work
# persistent capture-dedup ledger (kept)
ARCHIVE ?= state/archive.txt
LANGS ?= en.*,ko.*
WHISPER_MODEL ?= mlx-community/whisper-large-v3-turbo
DOMAINS ?= creator-wisdom

.PHONY: setup fetch notes capture drain demo clean

# yt-dlp is a uv dependency (pinned in uv.lock); ffmpeg + deno are system CLIs.
setup:
	brew install ffmpeg deno
	uv sync

# Fetch transcripts for a URL (video / playlist / channel). Auto-detects captions vs audio->Whisper.
fetch:
	@mkdir -p "$(dir $(ARCHIVE))"
	uv run python src/fetch.py "$(URL)" --workdir "$(WORK)" --langs "$(LANGS)" \
	  --whisper-model "$(WHISPER_MODEL)" --archive "$(ARCHIVE)"

# Turn fetched transcripts into Source notes in the vault.
notes:
	uv run python src/batch.py --workdir "$(WORK)" --vault "$(VAULT)" --domains "$(DOMAINS)"

# Capture a whole channel end-to-end (fetch + notes).
capture: fetch notes

# Drain the OCI approval queue: capture + distill everything 마스터 approved (what launchd runs).
drain:
	uv run auto_capture.py

# Self-contained demo (no network): sample transcript -> Source note in demo/_demo_vault, then print it.
demo:
	uv run python src/youtube_to_source.py --meta demo/sample_meta.json --transcript demo/sample_transcript.srt \
	  --domains "$(DOMAINS)" --vault demo/_demo_vault
	@echo "----- generated Source note -----"
	@cat "demo/_demo_vault/00_Resources/Demo Creator — How I think about building products.md"

# Remove scratch transcripts + demo output (keeps state/archive.txt).
clean:
	rm -rf "$(WORK)" demo/_demo_vault
