"""Per-session recording sink (M2 Checkpoint B).

Captures BOTH audio streams for the full session:
  • original   — the untranslated Arabic PCM16 from the capture page
  • translated — the English PCM16 from the OpenAI session

Audio is written to temp WAV files during the session (cheap local writes, off the
live path) then, on finalize(), uploaded to MinIO and recorded as `recordings` rows
(paths only — golden rule #3). Translated transcript deltas are segmented into
`transcript_segments` rows.

Only constructed when `save_recording` is true — when the speaker opts out (FR-15),
no sink exists, so nothing is persisted (design §4 / requirements FR-15).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time

from .audio import WavWriter
from .db import Database
from .storage import ObjectStore

logger = logging.getLogger("relay.recording")

# A segment is finalized when the accumulated text ends with one of these.
_SENTENCE_ENDINGS = ".!?؟"  # incl. Arabic question mark ؟


class RecordingSink:
    def __init__(self, event_id: str, store: ObjectStore, db: Database, bucket: str,
                 *, sample_rate: int = 24000) -> None:
        self._event_id = event_id
        self._store = store
        self._db = db
        self._bucket = bucket
        self._tmpdir = tempfile.mkdtemp(prefix="relay-rec-")
        self._original = WavWriter(os.path.join(self._tmpdir, "original.wav"), sample_rate=sample_rate)
        self._translated = WavWriter(os.path.join(self._tmpdir, "translated.wav"), sample_rate=sample_rate)
        # transcript segmentation
        self._t0 = time.monotonic()
        self._seq = 0
        self._buf = ""
        self._seg_start_ms: int | None = None

    # --- audio (synchronous, off the live path) ---
    def add_original(self, pcm16: bytes) -> None:
        self._original.write(pcm16)

    def add_translated(self, pcm16: bytes) -> None:
        self._translated.write(pcm16)

    # --- transcript ---
    async def add_transcript(self, text: str, is_final: bool) -> None:
        now_ms = int((time.monotonic() - self._t0) * 1000)
        if self._seg_start_ms is None:
            self._seg_start_ms = now_ms
        self._buf += text
        if is_final or (self._buf.strip()[-1:] in _SENTENCE_ENDINGS):
            await self._flush_segment(now_ms, final=True)

    async def _flush_segment(self, end_ms: int, *, final: bool) -> None:
        text = self._buf.strip()
        if not text:
            self._buf = ""
            self._seg_start_ms = None
            return
        await self._db.insert_transcript_segment(
            event_id=self._event_id, seq=self._seq,
            t_start_ms=self._seg_start_ms or 0, t_end_ms=end_ms,
            text=text, is_final=final,
        )
        self._seq += 1
        self._buf = ""
        self._seg_start_ms = None

    # --- finalize ---
    async def finalize(self) -> None:
        """Flush trailing transcript, upload both WAVs to MinIO, write recordings rows."""
        import asyncio

        # Any trailing un-terminated text is persisted as an interim (is_final=false) segment.
        if self._buf.strip():
            await self._flush_segment(int((time.monotonic() - self._t0) * 1000), final=False)

        self._original.close()
        self._translated.close()

        for kind, wav in (("original", self._original), ("translated", self._translated)):
            key = f"events/{self._event_id}/{kind}.wav"
            await asyncio.to_thread(self._store.upload_file, self._bucket, key, wav.path, "audio/wav")
            await self._db.insert_recording(
                event_id=self._event_id, kind=kind, bucket=self._bucket, object_key=key,
                fmt="wav", sample_rate_hz=wav.sample_rate, channels=wav.channels,
                size_bytes=os.path.getsize(wav.path), duration_seconds=wav.duration_seconds,
            )

        shutil.rmtree(self._tmpdir, ignore_errors=True)
        logger.info("finalized recordings for event %s (%d transcript segments)", self._event_id, self._seq)
