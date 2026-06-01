# Project RELAY — Wiki Home

> Working codename: **RELAY** (placeholder — rename anytime). A self-hosted, near-real-time speech translation and local broadcast system.

---

## What this is

A single on-site speaker talks (Arabic at launch); the system translates their speech to English in near-real-time while preserving tone, and broadcasts the translated audio to listeners who "tune in" through a web page on the local WiFi. Both the original and translated audio are recorded and, after the event, published to the organization's existing public website.

## Status

| Item | Value |
|---|---|
| Phase | 1 — Requirements (in sign-off) |
| Launch scope | Audio + live English subtitles, 1 language pair: **Arabic → English** |
| Deployment | On-premise, LAN-only at launch; built to migrate to public internet later |
| Paid dependency | OpenAI API only (everything else open-source / self-hosted) |

## Document index

- [Requirements Specification](./requirements.md) — what the system must do (sign-off needed)
- [Roadmap / Path Forward](./roadmap.md) — phased milestones
- Design Document — *to be written after requirements sign-off*
- Operations Runbook — *to be written before first event*

## Architecture at a glance

```
Podium mic (browser)
      │  WebSocket: PCM16 24kHz audio
      ▼
FastAPI server  ──────────────►  OpenAI /v1/realtime/translations
   │   │   ▲                         (gpt-realtime-translate)
   │   │   └── translated audio + transcript deltas ◄──┘
   │   │
   │   ├── records ORIGINAL audio  ─► local storage (MinIO / disk)
   │   └── records TRANSLATED audio ─► local storage (MinIO / disk)
   │
   ▼  translated audio
ffmpeg ─► LL-HLS segments ─► nginx ─► listener browsers (hls.js)
                                         (on local WiFi)
Metadata (events, paths, timestamps) ─► PostgreSQL
```

**Also:** transcript deltas from the translation session feed the **live subtitles** on the listener page; after the event, the full translated transcript is sent to a text AI model to produce a **structured article + summary** for publishing alongside the MP3s.

## Chosen stack (Phase 2)

| Layer | Choice | Why |
|---|---|---|
| OS | Ubuntu Server 26.04 LTS (or Debian 13) | Stable, supported to 2031, large ecosystem |
| App / session host | FastAPI + uvicorn | Async; holds the OpenAI session and WebSocket signaling |
| Reverse proxy + stream server | nginx | Serves HLS over HTTP; fans out to many listeners cheaply |
| Media muxing | ffmpeg | Translated audio → LL-HLS segments |
| Metadata DB | PostgreSQL | Lightweight metadata only (DB is near-idle in this workload) |
| Blob storage | MinIO (S3-compatible) or local FS | Recorded audio; S3 API eases later cloud migration |
| Packaging | Docker / docker-compose | Reproducible, portable, isolates each service |

## Glossary

- **Translation session** — one continuous connection to OpenAI that translates one speaker into one language. Cost depends on number of *languages*, not number of listeners.
- **Fan-out** — distributing one translated stream to many listeners. Handled by HLS over nginx.
- **LL-HLS** — Low-Latency HTTP Live Streaming. Scales to many viewers over plain HTTP; ~2-5s latency.
- **Capture station** — the device + mic that picks up the speaker and sends audio to the server.
- **Operator** — person who starts/stops a session for an event.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| Phase 1 | Launch with 1 language pair (Arabic→English) | Reduce scope; prove the pipeline |
| Phase 1 | Audio only at launch (no video) | Big bandwidth + complexity reduction; video deferred |
| Phase 1 | HLS for fan-out | Listeners don't understand source language, so latency is acceptable; scales cheaply |
| Phase 1 | Keep all original + translated audio | Archival + post-event publishing |
| Phase 1 | Server holds the OpenAI session (WebSocket) | Server needs translated audio for recording + broadcast; keeps API key server-side |
| Phase 1 | Capture via phone (browser page) | Simplest mobile capture; no feedback-loop risk; sound-board line feed is a later quality upgrade |
| Phase 1 | Live English subtitles in scope at launch | Transcript deltas come free from the translation session |
| Phase 1 | Post-event AI-generated article + summary | Reuse the transcript to produce publishable text alongside the audio |
| Phase 1 | Export recordings as MP3 | Easy manual drag-and-drop upload to the (likely WordPress) site |