# YouTube Knowledge Pipeline — common tasks.
# Override on the command line, e.g.  make capture URL="https://www.youtube.com/@edmundyong/videos"

VAULT ?= /Users/minkyushim/Library/CloudStorage/OneDrive-Personal/Desktop/04_Technical Brain
WORK  ?= work
LANGS ?= en.*,ko.*
WHISPER_MODEL ?= mlx-community/whisper-large-v3-turbo
DOMAINS ?= creator-wisdom

.PHONY: setup fetch notes capture demo clean

setup:
	brew install yt-dlp ffmpeg
	python3 -m pip install -r requirements.txt

# Fetch transcripts for a URL (video / playlist / channel). Auto-detects captions vs audio->Whisper.
fetch:
	python3 src/fetch.py "$(URL)" --workdir "$(WORK)" --langs "$(LANGS)" \
	  --whisper-model "$(WHISPER_MODEL)" --archive "$(WORK)/archive.txt"

# Turn fetched transcripts into Source notes in the vault.
notes:
	python3 src/batch.py --workdir "$(WORK)" --vault "$(VAULT)" --domains "$(DOMAINS)"

# Capture a whole channel end-to-end (fetch + notes).
capture: fetch notes

# Self-contained demo (no network): sample transcript -> Source note in demo/_demo_vault, then print it.
demo:
	python3 src/youtube_to_source.py --meta demo/sample_meta.json --transcript demo/sample_transcript.srt \
	  --domains "$(DOMAINS)" --tags entrepreneurship --vault demo/_demo_vault
	@echo "----- generated Source note -----"
	@cat "demo/_demo_vault/00_Resources/Demo Creator — How I think about building products.md"

clean:
	rm -rf "$(WORK)" demo/_demo_vault
