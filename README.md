# RELAY (HTFTM)

Self-hosted, near-real-time **Arabic → English** speech translation with LAN broadcast.
A single on-site speaker talks Arabic; RELAY translates to English in near-real-time
(preserving tone), broadcasts the translated audio to listeners on the local WiFi with
live subtitles, records both audio streams, and generates a post-event article.

> **Current phase: M1 — design + repo scaffold.** Services are runnable stubs; feature
> code begins at M2. See [`CLAUDE.md`](./CLAUDE.md) for the operating brief.

## Documentation

- [`halal_translator/requirements.md`](./halal_translator/requirements.md) — SRS / scope (source of truth)
- [`halal_translator/roadmap.md`](./halal_translator/roadmap.md) — milestones M0–M6
- [`halal_translator/docs/design.md`](./halal_translator/docs/design.md) — M1 design (components, WS contract, DB schema, HLS layout)
- [`halal_translator/wiki.md`](./halal_translator/wiki.md) — architecture overview + decision log

## Repository layout

```
.
├── docker-compose.yml          # root compose: server, nginx, postgres, minio
├── .env.example                # copy to .env (never commit .env)
└── halal_translator/
    ├── docs/design.md           # M1 design document
    ├── server/                  # FastAPI app (OpenAI session, capture WS, recording, signaling)
    │   ├── app/main.py          # M1 stub: /healthz, /api/events, /ws/capture, /ws/operator
    │   ├── db/schema.sql         # Postgres metadata schema (loaded on first init)
    │   ├── requirements.txt
    │   └── Dockerfile
    ├── capture/                 # phone capture page (mic → WebSocket PCM16) — placeholder at M1
    ├── listener/                # listener page (hls.js + subtitles) — placeholder at M1
    └── streaming/               # nginx config (+ admin page); ffmpeg/HLS pipeline lands at M3
```

## Run it

Requires Docker + Docker Compose.

```bash
cp .env.example .env        # then set OPENAI_API_KEY (needed from M2; unused at M1)
docker compose up --build
```

Then:

| URL | What |
|---|---|
| <http://localhost:8080/> | Listener page |
| <http://localhost:8080/capture/> | Capture station page |
| <http://localhost:8080/admin/> | Operator console |
| <http://localhost:8080/healthz> | Server health (proxied) |
| <http://localhost:9001/> | MinIO console |

Stop with `Ctrl+C`, then `docker compose down` (add `-v` to also drop the data volumes).

> Compose ships safe **dev defaults** for all non-secret values, so it comes up without a
> `.env`. Change the dev passwords before any non-local deployment, and never commit `.env`,
> recordings, HLS output, or `.venv` (enforced by [`.gitignore`](./.gitignore)).

### Local Python dev (optional — IDE/lint/tests only)

```bash
cd halal_translator/server
python3 -m venv .venv && source .venv/bin/activate   # never committed
pip install -r requirements.txt
```

## M1 exit gate

`docker compose up --build` brings server (FastAPI `/healthz`), nginx, Postgres (schema
loaded), and MinIO online cleanly — no feature logic. Design doc written and approved.
