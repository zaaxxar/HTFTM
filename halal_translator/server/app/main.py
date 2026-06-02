"""RELAY server — M1 scaffold.

Runnable stub for the M1 exit gate. Exposes a health endpoint plus thin stubs
for the contract surface in docs/design.md (capture/operator WebSockets, operator
REST). There is intentionally NO M2 feature logic here: no OpenAI session, no
audio handling, no recording, no ffmpeg/HLS. See halal_translator/docs/design.md.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, WebSocket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("relay.server")

app = FastAPI(title="RELAY server", version="0.1.0-m1")

PHASE = "M1"
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
    """Stub — event persistence (design §5/§6) lands at M2."""
    return []


async def _drain(ws: WebSocket) -> None:
    """Accept frames and discard them until the client disconnects (M1 — no processing)."""
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            break


@app.websocket("/ws/capture")
async def ws_capture(ws: WebSocket) -> None:
    """Capture <-> server contract (design §4) — M1 stub.

    Accepts the socket, sends a `welcome` + idle `state`, then drains frames
    without processing. The audio pipeline (OpenAI, recording, HLS) arrives at M2.
    """
    await ws.accept()
    await ws.send_json({"type": "welcome", "eventId": None, "state": "idle", "expects": EXPECTED_AUDIO})
    await ws.send_json(
        {"type": "state", "state": "idle", "eventId": None, "detail": "M1 scaffold — capture pipeline lands at M2"}
    )
    await _drain(ws)
    logger.info("capture socket closed")


@app.websocket("/ws/operator")
async def ws_operator(ws: WebSocket) -> None:
    """Operator monitor contract (design §5) — M1 stub."""
    await ws.accept()
    await ws.send_json(
        {"type": "state", "state": "idle", "eventId": None, "detail": "M1 scaffold — operator control lands at M5"}
    )
    await _drain(ws)
    logger.info("operator socket closed")
