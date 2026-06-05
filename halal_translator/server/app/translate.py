"""OpenAI realtime translation session client (design §8).

Holds ONE WebSocket connection to OpenAI's dedicated translation endpoint
(`/v1/realtime/translations`, model `gpt-realtime-translate`). This is a
CONTINUOUS session: we never call `response.create` and never commit a turn —
we append audio (including silence) and handle translated audio + transcript
deltas as they stream back (CLAUDE.md, design §8).

Event contract (confirmed against the OpenAI realtime-translation guide):
  client → server:
    {"type": "session.update", "session": {"audio": {"output": {"language": "en"}}}}
    {"type": "session.input_audio_buffer.append", "audio": "<base64 pcm16>"}
    {"type": "session.close"}

Note: the translation endpoint has NO output-voice parameter — it adapts the voice
to the source speaker (preserving tone). Sending a `voice` field is rejected and
(because the whole session.update is rejected) silently drops the language setting.
  server → client:
    session.output_audio.delta        {"delta": "<base64 pcm16>"}   translated audio
    session.output_transcript.delta   {"delta": "<text>"}          target transcript (interim)
    session.output_transcript.done    {"transcript": "<text>"}     target transcript (final)
    session.input_transcript.delta    {"delta": "<text>"}          source transcript
    session.closed                                                  drain complete
    error                             {...}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

import websockets

from .config import Settings

logger = logging.getLogger("relay.translate")

# (pcm16_bytes) -> None
AudioCallback = Callable[[bytes], Awaitable[None]]
# (text, is_final) -> None
TranscriptCallback = Callable[[str, bool], Awaitable[None]]

_CLOSE_DRAIN_TIMEOUT_S = 15.0


class TranslationSession:
    """A single continuous Arabic→English translation session."""

    def __init__(
        self,
        settings: Settings,
        *,
        on_audio: AudioCallback,
        on_transcript: TranscriptCallback | None = None,
        on_source_transcript: TranscriptCallback | None = None,
    ) -> None:
        self._s = settings
        self._on_audio = on_audio
        self._on_transcript = on_transcript
        self._on_source_transcript = on_source_transcript
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._reader: asyncio.Task | None = None
        self._closed = asyncio.Event()

    async def connect(self) -> None:
        """Open the OpenAI WS, configure the session, and start reading events."""
        if not self._s.has_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set (server-side only)")

        url = f"{self._s.openai_realtime_url}?{urlencode({'model': self._s.model})}"
        headers = {"Authorization": f"Bearer {self._s.openai_api_key}"}
        if self._s.safety_identifier:
            headers["OpenAI-Safety-Identifier"] = self._s.safety_identifier

        logger.info("opening OpenAI translation session: model=%s target=%s",
                    self._s.model, self._s.target_lang)
        self._ws = await websockets.connect(url, extra_headers=headers, max_size=None)
        await self._configure()
        self._reader = asyncio.create_task(self._read_loop(), name="openai-reader")

    async def _configure(self) -> None:
        """Set the target output language (design §8). Source language is auto-detected.

        The endpoint has no voice parameter (voice adapts to the source speaker), and
        any unknown field rejects the whole session.update — so keep this minimal.
        """
        assert self._ws is not None
        await self._ws.send(json.dumps({
            "type": "session.update",
            "session": {"audio": {"output": {"language": self._s.target_lang}}},
        }))

    async def send_audio(self, pcm16: bytes) -> None:
        """Append a PCM16/24k/mono chunk to the translation input buffer."""
        if self._ws is None:
            return
        await self._ws.send(json.dumps({
            "type": "session.input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
        }))

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    event = json.loads(raw)
                except (ValueError, TypeError):
                    logger.warning("non-JSON event from OpenAI: %r", raw[:200])
                    continue
                await self._handle_event(event)
        except websockets.exceptions.ConnectionClosed:
            logger.info("OpenAI socket closed")
        finally:
            self._closed.set()

    async def _handle_event(self, event: dict) -> None:
        etype = event.get("type", "")
        if etype == "session.output_audio.delta":
            chunk = event.get("delta")
            if chunk:
                await self._on_audio(base64.b64decode(chunk))
        elif etype == "session.output_transcript.delta":
            if self._on_transcript and (text := event.get("delta")):
                await self._on_transcript(text, False)
        elif etype == "session.output_transcript.done":
            if self._on_transcript and (text := event.get("transcript")):
                await self._on_transcript(text, True)
        elif etype == "session.input_transcript.delta":
            if self._on_source_transcript and (text := event.get("delta")):
                await self._on_source_transcript(text, False)
        elif etype == "session.closed":
            logger.info("received session.closed (drain complete)")
            self._closed.set()
        elif etype == "error":
            logger.error("OpenAI error event: %s", json.dumps(event))
        else:
            # session.created / session.updated / *.done / etc. — log for visibility.
            logger.debug("OpenAI event: %s", etype)

    async def close(self) -> None:
        """Graceful shutdown: session.close, drain until session.closed, then close.

        Keeps reading (and emitting) trailing translated audio so it isn't dropped
        (design §4.4 / §8). Safe to call more than once.
        """
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "session.close"}))
        except websockets.exceptions.ConnectionClosed:
            pass

        try:
            await asyncio.wait_for(self._closed.wait(), timeout=_CLOSE_DRAIN_TIMEOUT_S)
        except TimeoutError:
            logger.warning("timed out waiting for session.closed; closing anyway")

        await self._ws.close()
        if self._reader is not None:
            try:
                await asyncio.wait_for(self._reader, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._reader.cancel()
        self._ws = None
