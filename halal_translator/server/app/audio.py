"""Tiny PCM16 → WAV writer for local verification (Checkpoint A).

Audio bytes are PCM16, 24 kHz, mono (the format used end-to-end, design §4.1/§8).
This writes a playable .wav so the translated output can be auditioned. At
Checkpoint B, audio goes to MinIO instead (paths only in Postgres — golden rule #3).
"""

from __future__ import annotations

import wave


class WavWriter:
    """Append PCM16 frames to a WAV file; finalize the header on close()."""

    def __init__(self, path: str, *, sample_rate: int = 24000, channels: int = 1) -> None:
        self.path = path
        self._wf = wave.open(path, "wb")
        self._wf.setnchannels(channels)
        self._wf.setsampwidth(2)  # PCM16 = 2 bytes/sample
        self._wf.setframerate(sample_rate)
        self.bytes_written = 0

    def write(self, pcm16: bytes) -> None:
        self._wf.writeframes(pcm16)
        self.bytes_written += len(pcm16)

    @property
    def duration_seconds(self) -> float:
        # mono PCM16 @ sample_rate; 2 bytes/sample
        return self.bytes_written / 2 / self._wf.getframerate()

    def close(self) -> None:
        self._wf.close()
