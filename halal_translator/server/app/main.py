"""RELAY server — M2 core translate-and-record loop.

Checkpoint A: capture WS → real OpenAI translation session (design §8).
Checkpoint B: on session start create an `events` row honoring the FR-15 opt-out
flags; when `save_recording` is true, record BOTH original (Arabic) and translated
(English) audio to MinIO and write `recordings` + `transcript_segments` rows
(paths only — golden rule #3). When `save_recording` is false, only the event row
is created and persistence is skipped entirely.

M1 contracts are preserved (welcome/state/transcript/error shapes, operator stub).
Out of scope: HLS/broadcast (M3), operator control UI (M5). See docs/design.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone  # noqa: F401  (kept for future use)

from fastapi import FastAPI, WebSocket

from .config import load_settings
from .db import Database
from .recording import RecordingSink
from .storage import ObjectStore
from .translate import TranslationSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("relay.server")

PHASE = "M2"
# Audio format the capture page must send (design §4.1).
EXPECTED_AUDIO = {"format": "pcm_s16le", "sampleRate": 24000, "channels": 1, "chunkMs": 20}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the Postgres pool + MinIO client and provision the recordings bucket."""
    settings = load_settings()
    app.state.settings = settings

    db = Database(settings.database_url)
    try:
        await db.connect()
    except Exception:  # noqa: BLE001 — stay up so health is green; persistence degrades
        logger.exception("could not connect to Postgres; recording metadata disabled")
    app.state.db = db

    store = ObjectStore(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key)
    try:
        await asyncio.to_thread(store.ensure_bucket, settings.recordings_bucket)
    except Exception:  # noqa: BLE001
        logger.exception("could not reach MinIO / ensure bucket; recording uploads may fail")
    app.state.store = store

    try:
        yield
    finally:
        await db.close()


app = FastAPI(title="RELAY server", version="0.2.0-m2", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness probe used by the compose healthcheck and by nginx."""
    return {"status": "ok", "service": "relay-server", "phase": PHASE}


@app.get("/")
async def root() -> dict:
    return {
        "service": "relay-server",
        "phase": PHASE,
        "design": "halal_translator/docs/design.md",
        "endpoints": ["/healthz", "/api/events", "/ws/capture", "/ws/operator"],
    }


@app.get("/api/events")
async def list_events() -> list:
    """Stub — the operator REST surface lands at M5."""
    return []


async def _drain(ws: WebSocket) -> None:
    """Accept frames and discard them until the client disconnects."""
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            break


@app.websocket("/ws/capture")
async def ws_capture(ws: WebSocket) -> None:
    """Capture → server → OpenAI loop with recording + metadata (design §4, §6, §8).

    The OpenAI session and recorder open lazily on the first audio frame; on
    disconnect we drain trailing translated audio, finalize recordings, and mark
    the event stopped.
    """
    await ws.accept()
    await ws.send_json({"type": "welcome", "eventId": None, "state": "idle", "expects": EXPECTED_AUDIO})

    settings = app.state.settings
    db: Database = app.state.db
    store: ObjectStore = app.state.store

    # Per-session opt-out flags (FR-15). M2 bridge: carried on the capture `hello`
    # until the operator API/UI sets them (M5). Defaults: save + article on.
    flags = {"name": "Untitled session", "save_recording": True, "generate_article": True}
    event_id: str | None = None
    session: TranslationSession | None = None
    sink: RecordingSink | None = None
    session_started: float | None = None

    async def create_event_if_needed() -> None:
        nonlocal event_id
        if event_id is not None or not db.available:
            return
        try:
            event_id = await db.create_event(
                name=flags["name"], source_lang=settings.source_lang, target_lang=settings.target_lang,
                save_recording=flags["save_recording"], generate_article=flags["generate_article"],
            )
            logger.info("event %s created (save_recording=%s generate_article=%s)",
                        event_id, flags["save_recording"], flags["generate_article"])
        except Exception:  # noqa: BLE001
            logger.exception("failed to create event row")

    async def ensure_session() -> bool:
        nonlocal session, sink, session_started
        if session is not None:
            return True
        if not settings.has_api_key:
            await ws.send_json({"type": "error", "code": "upstream_unavailable",
                                "message": "OPENAI_API_KEY not configured on the server", "fatal": True})
            return False

        session_started = time.monotonic()

        if flags["save_recording"] and db.available and event_id is not None:
            sink = RecordingSink(event_id, store, db, settings.recordings_bucket)
            logger.info("recording -> s3://%s/events/%s/ (original + translated)",
                        settings.recordings_bucket, event_id)
        else:
            logger.info("recording skipped (save_recording=%s)", flags["save_recording"])

        async def on_audio(pcm: bytes) -> None:        # translated audio from OpenAI
            if sink is not None:
                sink.add_translated(pcm)

        async def on_transcript(text: str, is_final: bool) -> None:
            logger.info("transcript%s: %s", " [final]" if is_final else "", text)
            if sink is not None:
                try:
                    await sink.add_transcript(text, is_final)
                except Exception:  # noqa: BLE001
                    logger.exception("transcript persist failed")
            try:
                await ws.send_json({"type": "transcript", "text": text, "delta": not is_final,
                                    "tStartMs": int((time.monotonic() - (session_started or 0)) * 1000)})
            except Exception:  # noqa: BLE001 — capture gone during drain
                pass

        session = TranslationSession(settings, on_audio=on_audio, on_transcript=on_transcript)
        try:
            await session.connect()
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to open OpenAI translation session")
            await ws.send_json({"type": "error", "code": "upstream_unavailable",
                                "message": str(exc), "fatal": True})
            if event_id is not None and db.available:
                await db.mark_event_failed(event_id, str(exc))
            session = None
            return False

        await ws.send_json({"type": "state", "state": "live", "eventId": event_id, "detail": "translating"})
        return True

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if (chunk := msg.get("bytes")) is not None:
                await create_event_if_needed()
                if await ensure_session():
                    if sink is not None:
                        sink.add_original(chunk)       # record original (Arabic)
                    assert session is not None
                    await session.send_audio(chunk)
            elif (text := msg.get("text")) is not None:
                try:
                    data = json.loads(text)
                except ValueError:
                    continue
                mtype = data.get("type")
                if mtype == "hello":
                    if data.get("eventName"):
                        flags["name"] = str(data["eventName"])
                    if "saveRecording" in data:
                        flags["save_recording"] = bool(data["saveRecording"])
                    if "generateArticle" in data:
                        flags["generate_article"] = bool(data["generateArticle"])
                    logger.info("capture hello: %s", {k: data.get(k) for k in
                                ("clientId", "format", "sampleRate", "channels", "saveRecording", "generateArticle")})
                    await create_event_if_needed()
                elif mtype == "bye":
                    break
                # heartbeat / mute / unmute: no-op at M2
    finally:
        # Capture span = first audio → disconnect. Recorded BEFORE the OpenAI drain so
        # the event duration matches original.wav (the drain only adds translated audio).
        capture_end = time.monotonic()
        if session is not None:
            await session.close()
        if sink is not None:
            try:
                await sink.finalize()
            except Exception:  # noqa: BLE001
                logger.exception("failed to finalize recordings")
        if event_id is not None and db.available:
            duration = int(capture_end - session_started) if session_started else 0
            try:
                await db.mark_event_stopped(event_id, duration)
            except Exception:  # noqa: BLE001
                logger.exception("failed to mark event stopped")
        logger.info("capture session ended (event=%s)", event_id)


@app.websocket("/ws/operator")
async def ws_operator(ws: WebSocket) -> None:
    """Operator monitor contract (design §5) — stub until M5."""
    await ws.accept()
    await ws.send_json(
        {"type": "state", "state": "idle", "eventId": None, "detail": "operator control lands at M5"}
    )
    await _drain(ws)
    logger.info("operator socket closed")
