# CLAUDE.md — Halal Translator (HTFTM)

Operating guide for AI coding agents working in this repository. Read this first, every session.

## What this project is

A self-hosted, near-real-time speech translation and local broadcast system. A single on-site speaker talks in **Arabic**; the system translates to **English** in near-real-time (preserving tone), broadcasts the translated audio to listeners who tune in via a web page on the **local WiFi**, shows live English subtitles, records both the original and translated audio, and — after the event — generates a written article + summary from the transcript. Recordings (MP3) are published to an existing public website after the event.

**Current phase: M1 — design + repo scaffold.** Feature code begins at M2. Do not jump ahead and build features before the scaffold and design are agreed.

## Golden rules (do not violate)

1. **Secrets are server-side only.** The OpenAI API key lives in the server's environment, never in client code, never committed. Use `.env` (gitignored); keep `.env.example` updated.
2. **Never commit:** virtual environments (`.venv/`), recorded audio, HLS segments, service data volumes, `.env`, or OS cruft (`.DS_Store`). The `.gitignore` enforces this.
3. **Audio files do not go in the database.** Postgres stores *metadata only* (event, paths, timestamps, duration, language pair). Audio goes to blob storage (MinIO / local volume).
4. **One translation session per language, not per listener.** Cost scales with languages, not audience. Never open an OpenAI session per viewer.
5. **The server holds the OpenAI session.** Listeners receive a fanned-out HLS stream; they do not talk to OpenAI.
6. **Stay in scope.** Launch is audio-only, Arabic→English, LAN-only. Do not build video, multi-language, or public-internet exposure unless explicitly moved into scope.
7. **Keep it portable.** Everything runs in Docker; storage uses an S3-compatible API (MinIO) so we can migrate to the public internet later without a rewrite.

## Tech stack

- **OS (target host):** Ubuntu Server 26.04 LTS or Debian 13
- **Server / session host:** Python + FastAPI + uvicorn (async). Holds the OpenAI session, the capture WebSocket, recording, and signaling. (Note: an earlier Flask experiment was abandoned — do not reintroduce Flask.)
- **Reverse proxy + stream server:** nginx (serves LL-HLS over HTTP, fans out to listeners)
- **Media muxing:** ffmpeg (translated audio → LL-HLS; PCM → MP3 export)
- **Metadata DB:** PostgreSQL
- **Blob storage:** MinIO (S3-compatible) or local volume
- **Packaging:** Docker / docker-compose
- **Post-event article:** a standard (non-realtime) text-model call over the transcript

## Target repository structure

```
HTFTM/
├── CLAUDE.md                 # this file (root so Claude Code auto-loads it)
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
└── halal_translator/
    ├── docs/                 # requirements.md, roadmap.md, wiki.md
    ├── server/               # FastAPI app: OpenAI session, capture WS, recording, signaling
    │   ├── app/
    │   ├── requirements.txt  # or pyproject.toml
    │   └── Dockerfile
    ├── capture/              # phone capture web page (mic → WebSocket PCM16)
    ├── listener/             # listener web page (hls.js player + live subtitles)
    └── streaming/            # nginx + HLS config, ffmpeg pipeline
```
The docs currently live at `halal_translator/{requirements.md, roadmap.md, wiki.md}`; moving them under `halal_translator/docs/` is fine. Confirm structure changes before large file moves.

## OpenAI realtime translation — implementation notes

- **Endpoint:** the dedicated `/v1/realtime/translations` endpoint (not the voice-agent endpoint).
- **Model:** `gpt-realtime-translate`.
- **Transport:** WebSocket (this is a server-side broadcast-ingest pipeline).
- **Audio format:** PCM16, 24 kHz, mono, in and out.
- **Translation sessions are continuous and do NOT use the assistant turn lifecycle:** do not call `response.create`, do not wait for the client to commit a turn. Keep appending audio continuously, including silence between phrases, and handle output events as they arrive.
- **Output voice:** **not configurable on the translation endpoint.** `gpt-realtime-translate` uses *dynamic voice adaptation* — the translated speech follows the source speaker's tone/pitch/style (which serves tone preservation, FR-2). Do **not** send a `voice` field in `session.update`; it's an unknown parameter and (because it's rejected) drops the whole update, including the target language. `marin`/`cedar` belong to `gpt-realtime`/`gpt-realtime-2`, not this endpoint. (Verified at M2; see `docs/design.md` §8/§8.1.)
- **Transcript deltas** stream back alongside audio — use them to drive the live English subtitles (FR-13).
- **Shutdown:** send `session.close` and keep reading events until `session.closed` before closing the socket (closing early drops audio still draining).
- **Later (public exposure):** set the `OpenAI-Safety-Identifier` header with a stable, privacy-preserving value.

## How to run (once scaffolded)

```bash
cp .env.example .env        # fill in OPENAI_API_KEY
docker compose up --build
```
Local Python dev (optional, for IDE/lint/tests only — not required to run):
```bash
cd halal_translator/server
python3 -m venv .venv && source .venv/bin/activate   # fresh, never committed
pip install -r requirements.txt
```

## Conventions

- Python: format with `ruff`/`black`, type-hint public functions, prefer `async` I/O.
- Commits: conventional style (`feat:`, `fix:`, `chore:`, `docs:`).
- Keep `.env.example` in sync whenever a new env var is introduced.
- Document non-obvious decisions in `halal_translator/wiki.md` (the decision log).

## Reference docs

- `halal_translator/requirements.md` — the SRS (functional/non-functional requirements, acceptance criteria, open questions). **Source of truth for scope.**
- `halal_translator/roadmap.md` — milestones M0–M6 with exit gates.
- `halal_translator/wiki.md` — architecture overview, glossary, decision log.

## Definition of done for M1

`docker compose up` brings up stubbed FastAPI, nginx, Postgres, and MinIO services cleanly; the design doc (component responsibilities, internal WebSocket message contract, Postgres metadata schema, HLS output layout) is written and agreed. No feature logic yet.