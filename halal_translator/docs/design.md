# RELAY — M1 Design Document

**Status:** Draft for sign-off · **SDLC stage:** Design (M1) · **Scope:** Launch (v1.0)

> Codename **RELAY** (a.k.a. **HTFTM** in the repo brief — same project). Self-hosted, near-real-time **Arabic → English** speech translation with LAN broadcast, recording, live subtitles, and a post-event article.

This document specifies the **launch architecture** so the contracts are fixed before feature code begins at M2. It is the design deliverable for the M1 exit gate (see [roadmap.md](../roadmap.md)). It deliberately covers the four things M1 must pin down:

1. [Component responsibilities](#2-component-responsibilities)
2. [Capture ↔ server WebSocket message contract](#4-capture--server-websocket-contract)
3. [PostgreSQL metadata schema](#6-postgresql-metadata-schema)
4. [HLS output layout](#7-hls-output-layout)

Everything here is consistent with [requirements.md](../requirements.md) (scope source of truth) and the root `CLAUDE.md` golden rules. Where a choice depends on an unresolved open question (OQ-*), it is marked **TBD** and a safe default is used.

---

## 1. System overview & data flow

A single speaker talks Arabic into a **phone running the capture page** (FR-1). The phone streams raw audio to the **server**, which holds one continuous **OpenAI translation session** per language (golden rule #4/#5). The server records both audio streams, fans the translated audio out to listeners as **LL-HLS** via **nginx**, and pushes the translation transcript to listeners for **live subtitles**. After the event it exports MP3s and generates an article.

```
 Capture phone (browser)                                   OpenAI Realtime
 mic → AudioWorklet → PCM16/24k mono                /v1/realtime/translations
        │  WebSocket (binary audio + JSON control)   (gpt-realtime-translate)
        ▼                                                     ▲   │
   ┌──────────────────────────────────────────────┐  PCM16 up │   │ PCM16 + transcript deltas
   │                FastAPI server                │───────────┘   │
   │  • capture WS ingest                         │◄──────────────┘
   │  • OpenAI session host (1 per language)      │
   │  • recorder: ORIGINAL + TRANSLATED → storage │──► MinIO / local volume (audio blobs)
   │  • ffmpeg feeder: TRANSLATED PCM → LL-HLS    │──► streaming/hls/  (shared volume)
   │  • transcript publisher (subtitles)          │──► streaming/hls/live/en/subs.json
   │  • operator control plane + session metadata │──► PostgreSQL (metadata only)
   └──────────────────────────────────────────────┘
        ▲ (reverse proxy: /api, /ws/*)                 ▲ (static: listener page, HLS, subs)
        └──────────────────── nginx ───────────────────┘
                                 │  http (LAN)
                ┌────────────────┴───────────────────────────────────┐
        Listener browsers (hls.js + subtitle poller)  Operator console (start/stop, state)
```

**Boundary rules pulled from `CLAUDE.md` that this design honors:**
- The OpenAI API key is server-side only; listeners and capture never see it (NFR-7).
- One OpenAI session **per language**, never per listener (cost scales with languages — golden rule #4).
- Listeners pull a **fanned-out HLS stream from nginx**; they never talk to OpenAI (golden rule #5).
- Audio blobs go to MinIO/local volume; **Postgres stores metadata only** (golden rule #3).
- LAN-only, audio-only, Arabic→English at launch. No video, no multi-language, no public exposure (golden rule #6).

---

## 2. Component responsibilities

| Component | Dir | Responsibility | Out of scope (deferred) |
|---|---|---|---|
| **Capture page** | `capture/` | Phone browser page. Captures mic via Web Audio `AudioWorklet`, downsamples to PCM16/24 kHz/mono, streams to the server over WebSocket. Shows local capture state (connected, level, errors). | Sound-board line-in (future quality upgrade); any translation logic. |
| **Server (FastAPI)** | `server/` | The brain. Accepts the capture WS; holds the single OpenAI translation session; records original + translated audio; feeds translated PCM to ffmpeg for HLS; publishes transcript cues for subtitles; exposes the operator control plane + session state; persists metadata to Postgres; on stop, finalizes/exports MP3s and (later) triggers the article job. | Per-listener connections; serving HLS bytes (nginx does that). |
| **Streaming (nginx + ffmpeg)** | `streaming/` | nginx is the single LAN front door: reverse-proxies `/api` + `/ws/*` to the server, and serves static assets — the listener page, LL-HLS playlists/segments, and the subtitles sidecar. ffmpeg (spawned by the server) muxes translated PCM16 → LL-HLS CMAF segments into a shared volume. | TLS/auth (groundwork only, dormant for LAN — M5). |
| **Listener page** | `listener/` | Browser page on LAN WiFi. Plays `/live/en/master.m3u8` via **hls.js**; shows connection status (FR-12); renders live English subtitles from the transcript sidecar (FR-13). No install (FR-4). | Language selection (single language at launch). |
| **PostgreSQL** | compose service | Metadata store: events, recordings (paths only), transcript segments, generated articles. Near-idle workload. | Storing audio bytes (forbidden, golden rule #3). |
| **MinIO** | compose service | S3-compatible blob storage for recorded audio (original + translated, raw + exported MP3). S3 API keeps a later cloud migration rewrite-free (NFR-6). | — |

**M1 deliverable note:** at M1 each component is a **runnable stub** (health endpoint, placeholder page, empty bucket/DB). Feature logic lands M2–M5 per the roadmap. This doc defines the contracts those stubs will grow into.

---

## 3. Service topology, ports & entry points

Single LAN entry point is **nginx**; everything else is internal to the compose network.

| Service | Internal port | Exposed on host | Volume | Notes |
|---|---|---|---|---|
| `nginx` | 80 | **`8080`** (`http://<server-lan-ip>:8080/`) | mounts `streaming/hls` (ro) | Front door: static + reverse proxy. |
| `server` | 8000 | not exposed (reached via nginx) | mounts `streaming/hls` (rw) | uvicorn/FastAPI. |
| `postgres` | 5432 | not exposed (dev: optional `5432`) | `postgres-data` | Metadata only. |
| `minio` | 9000 (S3), 9001 (console) | `9000`, `9001` (dev) | `minio-data` | Console for ops; S3 for the server. |

**HTTP/WS surface (through nginx):**

| Path | Served by | Purpose |
|---|---|---|
| `GET /` | nginx static | Listener page (`listener/`). |
| `GET /capture` | nginx static | Capture page (`capture/`). |
| `GET /admin` | nginx static | Operator console (start/stop, state). *(simple page; auth deferred to M5)* |
| `GET /healthz` | server (proxied) | Liveness for the compose healthcheck. |
| `GET /api/...` | server (proxied) | Operator REST (events: create/start/stop/list, export). |
| `WS /ws/capture` | server (proxied) | **Capture ↔ server** audio + control (see §4). |
| `WS /ws/operator` | server (proxied) | Operator live state/transcript monitor (see §5). |
| `GET /live/en/*` | nginx static | LL-HLS playlists + segments (see §7). |
| `GET /live/en/subs.json` | nginx static | Rolling subtitle cues for the listener (see §4.5 / §7). |

> **Port choice:** host `8080` avoids needing root for port 80 during dev and keeps the design portable. The venue can map `80 → 8080` at deploy time. Confirm at M3.

---

## 4. Capture ↔ server WebSocket contract

The internal contract between the **capture page** and the **server**, on `WS /ws/capture`. This is the most latency-sensitive interface, so audio uses **binary frames** and control uses **JSON text frames** on the same socket.

### 4.1 Audio frames (binary)

| Property | Value |
|---|---|
| Frame type | WebSocket **binary** |
| Sample format | **PCM16, little-endian, signed** (`pcm_s16le`) |
| Sample rate | **24 000 Hz** (matches the OpenAI session; no server-side resample) |
| Channels | **1 (mono)** |
| Recommended chunk | **20 ms = 480 samples = 960 bytes** (keep ≤ 60 ms to stay within latency budget NFR-2) |
| Framing | Raw PCM only — **no header, no JSON wrapper.** One binary frame = one audio chunk. |

The capture page must produce exactly this format (downsample/mix in the browser) so the server can append bytes straight to the OpenAI session, the recorder, and the ffmpeg pipe with zero transcoding.

### 4.2 Control frames (JSON text) — client → server

All text frames are JSON objects with a `type` discriminator.

| `type` | Fields | When | Meaning |
|---|---|---|---|
| `hello` | `clientId` (str), `format` (`"pcm_s16le"`), `sampleRate` (`24000`), `channels` (`1`), `userAgent` (str), `swVersion` (str) | once, immediately after connect | Announces capture and **declares audio format**. Server validates; mismatch → `error` + close. |
| `heartbeat` | `t` (epoch ms) | every ~5 s | Keepalive + rough clock for drift checks. |
| `mute` / `unmute` | — | on demand | Capture intends to pause/resume sending audio (binary frames simply stop/resume; this just annotates intent for the operator UI). |
| `bye` | `reason` (str) | before client-initiated close | Graceful disconnect (e.g. page unload). |

### 4.3 Control frames (JSON text) — server → client

| `type` | Fields | Meaning |
|---|---|---|
| `welcome` | `eventId` (uuid \| null), `state` (see §4.4), `expects` (`{format,sampleRate,channels,chunkMs}`) | Handshake reply; echoes the required audio format. `eventId` is null if no live event yet. |
| `state` | `state`, `eventId`, `detail` (str) | Session-state change (idle/armed/live/stopping/error). Drives the capture-page status. |
| `ack` | `bytesReceived` (int), `bufferedMs` (int), `seq` (int) | Periodic ingest stats / soft backpressure signal. |
| `transcript` | `text` (str), `delta` (bool), `tStartMs` (int) | *Optional* echo of the translated transcript so a colocated operator can monitor on the capture device. |
| `warning` | `code` (`backpressure` \| `audio_gap` \| `format_soft`), `message` | Non-fatal; capture should adapt (e.g. slow down, check mic). |
| `error` | `code` (see §4.6), `message`, `fatal` (bool) | Problem. If `fatal`, the server closes the socket after sending. |

### 4.4 Session state machine

The **operator** owns lifecycle (FR-10); the capture station follows it. State is reported to capture (`state` msg), to the operator (`/ws/operator`), and persisted (`events.status`).

```
 idle ──operator create+start──► armed ──first audio after live──► live
                                   │                                 │
                                   │                                 │ operator stop
                                   │                                 ▼
                                   └──────────────────────────► stopping ──► stopped
                       error (any state, fatal) ─────────────────────────────► error
```

- **armed → live (lazy OpenAI open):** to respect cost (golden rule #4 / NFR-5), the server opens the OpenAI translation session and starts recording on the **first audio chunk after the operator goes live**, not merely when armed. No audio is billed while idle/armed.
- **stopping:** on operator stop the server sends OpenAI `session.close`, **keeps reading until `session.closed`** (so draining audio isn't dropped — per `CLAUDE.md`), flushes the recorder + ffmpeg, finalizes the MP3 exports, then → `stopped`.

### 4.5 Transcript → subtitles (FR-13)

Transcript **deltas** arrive from the OpenAI session alongside the translated audio. The server appends them to `transcript_segments` (persistence, for the article) **and** writes a rolling **`subs.json`** (recent cues, ~last 30 s) into the nginx-served stream directory. The listener polls `subs.json` (~1 Hz) and renders cues against the audio clock.

> **Decision — subtitle transport:** a polled JSON sidecar served by nginx, *not* per-listener SSE/WebSocket. This preserves the fan-out model (golden rule #5: nginx serves many listeners, the app server holds one session, no per-viewer app load) and tolerates the accepted subtitle/audio drift (requirements §5 Risks). **Future upgrade:** segmented WebVTT as an HLS subtitle track for tighter sync.

### 4.6 Error codes (capture WS)

| `code` | Meaning |
|---|---|
| `bad_format` | `hello` declared an unsupported format/rate/channels. Fatal. |
| `no_live_event` | Audio arrived with no live event (soft — buffered/discarded; warns). |
| `upstream_unavailable` | The OpenAI session could not be opened/maintained. Fatal for the session. |
| `backpressure` | Server ingest buffer exceeded; capture must slow/drop. Warning. |
| `internal` | Unexpected server error. Fatal. |

---

## 5. Operator control plane (brief)

Lifecycle and state surfacing (FR-10, FR-11). Detailed in M5; pinned here because the schema and state machine depend on it.

- `POST /api/events` `{name, sourceLang:"ar", targetLang:"en", voice:"marin"}` → creates an event (`status=created`).
- `POST /api/events/{id}/start` → `armed` then `live`; arms the pipeline.
- `POST /api/events/{id}/stop` → `stopping` → finalize → `stopped`.
- `GET /api/events` / `GET /api/events/{id}` → list/detail incl. recordings + state.
- `GET /api/events/{id}/recordings` → MP3 download/export links (FR-9; presigned MinIO URLs).
- `WS /ws/operator` → live `state`, `transcript`, and ingest stats for the console.

---

## 6. PostgreSQL metadata schema

**Metadata only — no audio bytes (golden rule #3).** Recording rows hold storage *coordinates* (bucket + key), never the file. HLS segments are ephemeral and are **not** tracked in the DB. The schema below is the launch schema and seeds the M1 init migration; tables can be empty at the M1 gate.

```sql
-- RELAY metadata schema (PostgreSQL 16). Audio blobs live in MinIO/local volume; only metadata here.
-- gen_random_uuid() is built into core Postgres (>= 13).

-- One row per translation session / event.
CREATE TABLE events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT        NOT NULL,
    source_lang      TEXT        NOT NULL DEFAULT 'ar',
    target_lang      TEXT        NOT NULL DEFAULT 'en',
    openai_voice     TEXT        NOT NULL DEFAULT 'marin'
                     CHECK (openai_voice IN ('marin', 'cedar')),
    status           TEXT        NOT NULL DEFAULT 'created'
                     CHECK (status IN ('created','armed','live','stopping','stopped','failed')),
    started_at       TIMESTAMPTZ,           -- set when first going live
    stopped_at       TIMESTAMPTZ,           -- set on finalize
    duration_seconds INTEGER,               -- filled on stop
    operator         TEXT,                  -- who started it (nullable until auth, M5)
    error            TEXT,                  -- last fatal error, if status='failed'
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per stored audio artifact. Exactly one 'original' and one 'translated' per event/format.
CREATE TABLE recordings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    kind             TEXT NOT NULL CHECK (kind IN ('original','translated')),
    storage_backend  TEXT NOT NULL DEFAULT 'minio' CHECK (storage_backend IN ('minio','local')),
    bucket           TEXT NOT NULL,         -- e.g. 'relay-recordings'
    object_key       TEXT NOT NULL,         -- e.g. 'events/<id>/translated.mp3'
    format           TEXT NOT NULL DEFAULT 'mp3' CHECK (format IN ('mp3','wav','pcm16')),
    sample_rate_hz   INTEGER NOT NULL DEFAULT 24000,
    channels         SMALLINT NOT NULL DEFAULT 1,
    bitrate_kbps     INTEGER,               -- e.g. 192 for exported MP3 (NFR-3)
    size_bytes       BIGINT,
    duration_seconds NUMERIC(10,3),
    sha256           TEXT,
    status           TEXT NOT NULL DEFAULT 'recording'
                     CHECK (status IN ('recording','finalizing','ready','failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at     TIMESTAMPTZ,
    UNIQUE (event_id, kind, format)         -- one original + one translated per format
);
CREATE INDEX idx_recordings_event ON recordings(event_id);

-- Translated transcript, segmented with timing. Feeds live subtitles (FR-13) + the article (FR-14).
CREATE TABLE transcript_segments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,           -- monotonically increasing per event
    t_start_ms  INTEGER NOT NULL,           -- ms from event start
    t_end_ms    INTEGER,
    text        TEXT NOT NULL,
    is_final    BOOLEAN NOT NULL DEFAULT false,  -- false = interim delta, true = settled
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, seq)
);
CREATE INDEX idx_transcript_event_seq ON transcript_segments(event_id, seq);

-- Post-event generated article + summary (FR-14). One (or more revisions) per event.
CREATE TABLE articles (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id      UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    model         TEXT NOT NULL,            -- text model used
    title         TEXT,
    summary       TEXT,
    body_markdown TEXT,
    status        TEXT NOT NULL DEFAULT 'generated'
                  CHECK (status IN ('generated','published')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_articles_event ON articles(event_id);
```

**Notes**
- Text + `CHECK` instead of native enums → simpler, portable migrations (NFR-6).
- `transcript_segments` and `articles` exist in the schema now because their contracts (subtitle cues, article input) are part of this design; they are populated in M2+/post-event, not at M1.
- Storage path convention: `bucket=relay-recordings`, `object_key=events/<event_id>/{original|translated}.{mp3|pcm}`.

---

## 7. HLS output layout

Audio-only **LL-HLS** in **CMAF/fMP4**, written by ffmpeg into a volume that nginx serves read-only. The path is namespaced by **target language** so multi-language is a later additive change, not a rewrite (golden rule #7) — only `en` exists at launch.

```
streaming/hls/                         # shared volume; nginx doc root for /live (gitignored)
└── live/
    └── en/                            # one rendition per target language (launch: 'en' only)
        ├── master.m3u8               # multivariant playlist (audio-only) — listener entry point
        ├── audio.m3u8                # LL-HLS media playlist (EXT-X-PART, low-latency tags)
        ├── init.mp4                  # CMAF init segment (codec config)
        ├── seg00001.m4s             # full media segments (~2 s)
        ├── seg00001.1.m4s          # partial segments (~0.3 s parts) for low latency
        ├── seg00001.2.m4s
        ├── ...                        # rolling window; old segments pruned
        └── subs.json                  # rolling subtitle cues (last ~30 s) for the listener
```

**Encoding / latency parameters (target):**

| Parameter | Value | Why |
|---|---|---|
| Container | fMP4 / CMAF | Required for LL-HLS partial segments. |
| Audio codec | **AAC-LC**, 24 kHz, mono, ~96–128 kbps | hls.js-friendly; speech-grade (NFR-3). Source PCM is transcoded by ffmpeg. |
| Segment duration | ~2 s | Standard HLS segment. |
| Part duration | ~0.3 s (LL-HLS `EXT-X-PART`) | Low-latency parts → end-to-end ≤ ~5 s (NFR-2). |
| Playlist window | ~6 segments, delete old | Bounded disk; `streaming/hls/` is gitignored. |

**Feeding ffmpeg:** the server spawns one ffmpeg per live event and writes translated **PCM16/24k/mono** to ffmpeg's **stdin pipe**; ffmpeg muxes LL-HLS into `streaming/hls/live/en/`. On stop, the server closes stdin so ffmpeg flushes the final partial segment, then the pipeline tears down.

**nginx serving rules (M3 detail, pinned here):**
- `Content-Type`: `application/vnd.apple.mpegurl` for `*.m3u8`, `video/iso.segment`/`video/mp4` for `*.m4s`/`init.mp4`, `application/json` for `subs.json`.
- Playlists: `Cache-Control: no-cache`; segments: short cache; enable `Access-Control-Allow-Origin` for the LAN listener page.
- LL-HLS niceties (`EXT-X-PRELOAD-HINT`, blocking playlist reload) configured in M3.

**Listener wiring:** hls.js loads `/live/en/master.m3u8`; a small poller fetches `/live/en/subs.json` (~1 Hz) and renders cues. Connection status (FR-12) derives from hls.js events.

---

## 8. OpenAI realtime translation session (config recap)

Restated from `CLAUDE.md` so the design is self-contained; the server is the **only** holder of this session.

| Aspect | Value |
|---|---|
| Endpoint | `/v1/realtime/translations` (dedicated translation endpoint, **not** the voice-agent endpoint) |
| Model | `gpt-realtime-translate` |
| Transport | WebSocket (server ↔ OpenAI) |
| Audio I/O | PCM16, 24 kHz, mono, both directions |
| Turn model | **Continuous** — no `response.create`, no client-commit turns; keep appending audio (incl. silence), handle output events as they arrive |
| Voice | `marin` (default) or `cedar`; **locks after first audio** in a session |
| Transcript | Deltas stream alongside audio → drive subtitles (FR-13) + persisted to `transcript_segments` |
| Shutdown | Send `session.close`, keep reading until `session.closed`, *then* close the socket (don't drop draining audio) |
| Sessions | **One per language** (launch: one), never per listener (golden rule #4) |
| Public-exposure later | Add the `OpenAI-Safety-Identifier` header (M5 / post-launch) |

---

## 9. Security & portability posture (launch)

- **Secrets:** `OPENAI_API_KEY` only in the server's environment via `.env` (gitignored); `.env.example` documents the required vars. Never in client code or git (golden rule #1, NFR-7).
- **LAN-only:** no TLS/auth at launch; nginx is structured so TLS termination + an auth hook + rate limiting can be switched on before public exposure without re-architecture (NFR-7, M5). Listener access policy (open WiFi vs event code vs login) is **TBD — OQ-4**; the launch default is open-on-LAN.
- **Portability:** everything in Docker; storage via the S3 API (MinIO) so a cloud move needs no rewrite (NFR-6).
- **Privacy:** the recording/consent notice process is **TBD — OQ-7** (process/legal, not code).

---

## 10. Open items carried from requirements

| Ref | Item | Design default until resolved |
|---|---|---|
| OQ-2 | Concurrent-listener target (≤500?) | Design for 500; HLS fan-out via nginx makes this an nginx/network sizing question (M4 load test). |
| OQ-4 | Listener access (open / code / login) | Open-on-LAN at launch; an auth hook point is reserved in nginx (M5). |
| OQ-9 | Expose the original Arabic stream too? | English-only at launch; the `/live/<lang>/` layout already accommodates adding `/live/ar/` later. |
| — | Subtitle transport | Polled `subs.json` sidecar (see §4.5); segmented WebVTT is the future upgrade. |

---

## 11. M1 exit gate checklist

- [x] Design doc written: component responsibilities, capture↔server WS contract, Postgres schema, HLS layout (this document).
- [ ] **Design approved** (this review).
- [ ] Repo scaffolded to the `CLAUDE.md` target structure: `docker-compose.yml` at root; stubbed `server` (FastAPI `/healthz`), `nginx`, `postgres` (schema init), `minio`; `capture`/`listener` placeholder pages; `.env.example`; `README` run steps.
- [ ] `docker compose up --build` brings all four services online cleanly (healthchecks green); no feature logic.

> Per the roadmap, **feature code begins at M2.** This document fixes the contracts that M2–M5 build against.
