# RELAY — Roadmap / Path Forward

Phased delivery mapped onto the software development lifecycle. Each milestone has a clear exit gate so we don't move on until the previous piece actually works.

---

## M0 — Requirements sign-off  *(you are here)*
**SDLC stage:** Requirements
- Review and approve [requirements.md](./requirements.md)
- Answer the open questions (OQ-1…OQ-9) — or accept the stated assumptions
- **Exit gate:** requirements signed off

## M1 — Design + repo scaffold
**SDLC stage:** Design + project setup
- Short design document: component responsibilities, data flow, storage schema, API/event contracts (OpenAI session config, internal WebSocket messages, HLS output layout)
- Define the PostgreSQL schema for event/recording metadata
- Scaffold the repository: directory structure, `docker-compose.yml` skeleton, service stubs (FastAPI, nginx, Postgres, MinIO), `README`, `.gitignore`, env-var template
- **Exit gate:** design approved; `docker compose up` brings empty services online cleanly

## M2 — Core pipeline (translate + record, no broadcast yet)
**SDLC stage:** Implementation
- Capture station page sends mic audio (PCM16 24 kHz) to the FastAPI server over WebSocket
- Server opens the OpenAI `/v1/realtime/translations` session (`gpt-realtime-translate`, voice `marin`/`cedar`), streams audio up, receives translated audio + transcript deltas
- Server writes the original and translated audio to storage with metadata
- **Exit gate:** speak Arabic → translated English audio file + original file saved correctly; tone preservation spot-checked by a bilingual reviewer

## M3 — Broadcast (LL-HLS + listener page)
**SDLC stage:** Implementation
- Pipe translated audio into ffmpeg → LL-HLS segments
- nginx serves the HLS playlist + segments
- Listener web page plays the stream via hls.js with connection status
- **Exit gate:** one listener hears live translated audio over the LAN within ~5s

## M4 — Scale & resilience test
**SDLC stage:** Testing
- Simulate up to the target listener count pulling HLS segments
- Validate venue WiFi + switch headroom (server wired via gigabit)
- Test listener reconnects, mid-session network blips, and a session restart
- **Exit gate:** target concurrency sustained with no audio dropouts

## M5 — Hardening + archival/export flow
**SDLC stage:** Implementation + Testing
- Operator controls: start/stop, session state, error surfacing
- Post-event export of both recordings in the format the public website needs (per OQ-5)
- Pre-public-exposure groundwork: TLS termination, auth hook points, `OpenAI-Safety-Identifier` header, rate limiting (kept dormant for LAN launch)
- **Exit gate:** a full dry-run event start→finish→export with no manual surgery

## M6 — Launch
**SDLC stage:** Deployment
- Operations runbook (start checklist, troubleshooting, recovery)
- Warm-spare server ready
- First live event
- **Exit gate:** successful live event; recordings published to the public site

## Post-launch backlog (future phases)
- Multi-language: one OpenAI session per language, one HLS rendition per language, listener language selector (FR-F1)
- Live subtitles from transcript deltas (FR-F2)
- Video capture + broadcast (FR-F3)
- Public-internet exposure: flip on TLS/auth/rate limits, move behind a proper reverse proxy, optionally migrate storage to cloud via the existing S3 API
- Automated publishing to the public website (FR-F4)

---

## Immediate next step
Once you sign off the requirements (M0), I'll produce the **M1 design doc + repo scaffold** — a runnable `docker-compose` skeleton with stubbed services, so you have a real codebase to build into. Feature code begins at M2.