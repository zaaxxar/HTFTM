"""RELAY server — M2 core translate-and-record loop.

Checkpoint A: the capture WebSocket now drives a real OpenAI realtime TRANSLATION
session (design §8). Audio in (PCM16/24k/mono binary frames, §4.1) is appended to
a continuous translation session; translated audio + transcript deltas stream back.
For verification ONLY, translated audio is written to a local .wav under a
gitignored scratch dir — MinIO/Postgres persistence arrives at Checkpoint B.

The M1 contracts are preserved, not changed: /healthz, /api/events, the /ws/capture
welcome/state/transcript/error message shapes (§4.3), and the /ws/operator stub.
Out of scope here: HLS/broadcast (M3), operator control UI (M5). See docs/design.md.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket

from .audio import WavWriter
from .config import load_settings
from .translate import TranslationSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("relay.server")

app = FastAPI(title="RELAY server", version="0.2.0-m2")

PHASE = "M2"
# Audio format the capture page must send (design §4.1).
EXPECTED_AUDIO = {"format": "pcm_s16le", "sampleRate": 24000, "channels": 1, "chunkMs": 20}


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
    """Stub — event persistence (design §5/§6) lands at Checkpoint B."""
    return []


async def _drain(ws: WebSocket) -> None:
    """Accept frames and discard them until the client disconnects."""
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            break


@app.websocket("/ws/capture")
async def ws_capture(ws: WebSocket) -> None:
    """Capture → server → OpenAI translation loop (design §4, §8).

    The OpenAI session is opened lazily on the first audio frame (so no API cost
    accrues until audio actually flows — design §4.4) and drained on disconnect so
    trailing translated audio isn't dropped.
    """
    await ws.accept()
    await ws.send_json({"type": "welcome", "eventId": None, "state": "idle", "expects": EXPECTED_AUDIO})

    settings = load_settings()
    session: TranslationSession | None = None
    wav: WavWriter | None = None
    started = time.monotonic()

    async def ensure_session() -> bool:
        """Open the OpenAI session + WAV writer on first audio. Returns False on failure."""
        nonlocal session, wav
        if session is not None:
            return True
        if not settings.has_api_key:
            await ws.send_json({"type": "error", "code": "upstream_unavailable",
                                "message": "OPENAI_API_KEY not configured on the server", "fatal": True})
            return False

        os.makedirs(settings.scratch_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(settings.scratch_dir, f"translated-{ts}.wav")
        wav = WavWriter(path)

        async def on_audio(pcm: bytes) -> None:
            assert wav is not None
            wav.write(pcm)

        async def on_transcript(text: str, is_final: bool) -> None:
            logger.info("transcript%s: %s", " [final]" if is_final else "", text)
            # Best-effort: the capture socket may already be closed while we drain
            # trailing transcript deltas after Stop — don't let that crash the loop.
            try:
                await ws.send_json({"type": "transcript", "text": text, "delta": not is_final,
                                    "tStartMs": int((time.monotonic() - started) * 1000)})
            except Exception:  # noqa: BLE001 — capture gone; keep recording/draining
                pass

        session = TranslationSession(settings, on_audio=on_audio, on_transcript=on_transcript)
        try:
            await session.connect()
        except Exception as exc:  # noqa: BLE001 — surface any upstream failure to capture
            logger.exception("failed to open OpenAI translation session")
            await ws.send_json({"type": "error", "code": "upstream_unavailable",
                                "message": str(exc), "fatal": True})
            session = None
            return False

        await ws.send_json({"type": "state", "state": "live", "eventId": None, "detail": "translating"})
        logger.info("translation session live -> %s", path)
        return True

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if (chunk := msg.get("bytes")) is not None:
                if await ensure_session():
                    assert session is not None
                    await session.send_audio(chunk)
            elif (text := msg.get("text")) is not None:
                try:
                    data = json.loads(text)
                except ValueError:
                    continue
                mtype = data.get("type")
                if mtype == "hello":
                    logger.info("capture hello: %s",
                                {k: data.get(k) for k in ("clientId", "format", "sampleRate", "channels")})
                elif mtype == "bye":
                    break
                # heartbeat / mute / unmute: no-op at M2
    finally:
        if session is not None:
            await session.close()
        if wav is not None:
            wav.close()
            logger.info("wrote %s (%.1fs, %d bytes pcm16)", wav.path, wav.duration_seconds, wav.bytes_written)


@app.websocket("/ws/operator")
async def ws_operator(ws: WebSocket) -> None:
    """Operator monitor contract (design §5) — stub until M5."""
    await ws.accept()
    await ws.send_json(
        {"type": "state", "state": "idle", "eventId": None, "detail": "operator control lands at M5"}
    )
    await _drain(ws)
    logger.info("operator socket closed")
