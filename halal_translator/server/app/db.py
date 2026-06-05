"""PostgreSQL access (asyncpg) for event/recording/transcript metadata.

METADATA ONLY — no audio bytes ever touch Postgres (golden rule #3 / design §6).
Audio lives in MinIO; `recordings` rows hold the bucket + object key only.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger("relay.db")


def _normalize_dsn(database_url: str) -> str:
    """asyncpg wants a plain libpq DSN — strip the SQLAlchemy-style driver suffix."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class Database:
    def __init__(self, database_url: str) -> None:
        self._dsn = _normalize_dsn(database_url)
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        logger.info("postgres pool ready")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def available(self) -> bool:
        return self._pool is not None

    async def create_event(
        self,
        *,
        name: str,
        source_lang: str,
        target_lang: str,
        save_recording: bool,
        generate_article: bool,
    ) -> str:
        """Insert an `events` row (status='live') and return its id (uuid as str)."""
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            INSERT INTO events (name, source_lang, target_lang, save_recording,
                                generate_article, status, started_at)
            VALUES ($1, $2, $3, $4, $5, 'live', now())
            RETURNING id
            """,
            name, source_lang, target_lang, save_recording, generate_article,
        )
        return str(row["id"])

    async def mark_event_stopped(self, event_id: str, duration_seconds: int) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            UPDATE events SET status='stopped', stopped_at=now(),
                              duration_seconds=$2, updated_at=now()
            WHERE id=$1::uuid
            """,
            event_id, duration_seconds,
        )

    async def mark_event_failed(self, event_id: str, error: str) -> None:
        assert self._pool is not None
        await self._pool.execute(
            "UPDATE events SET status='failed', error=$2, updated_at=now() WHERE id=$1::uuid",
            event_id, error[:1000],
        )

    async def insert_recording(
        self,
        *,
        event_id: str,
        kind: str,                 # 'original' | 'translated'
        bucket: str,
        object_key: str,
        fmt: str = "wav",
        sample_rate_hz: int = 24000,
        channels: int = 1,
        size_bytes: int,
        duration_seconds: float,
    ) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO recordings (event_id, kind, storage_backend, bucket, object_key,
                                    format, sample_rate_hz, channels, size_bytes,
                                    duration_seconds, status, finalized_at)
            VALUES ($1::uuid, $2, 'minio', $3, $4, $5, $6, $7, $8, $9::float8, 'ready', now())
            """,
            event_id, kind, bucket, object_key, fmt, sample_rate_hz, channels,
            size_bytes, duration_seconds,
        )

    async def insert_transcript_segment(
        self,
        *,
        event_id: str,
        seq: int,
        t_start_ms: int,
        t_end_ms: int,
        text: str,
        is_final: bool,
    ) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO transcript_segments (event_id, seq, t_start_ms, t_end_ms, text, is_final)
            VALUES ($1::uuid, $2, $3, $4, $5, $6)
            """,
            event_id, seq, t_start_ms, t_end_ms, text, is_final,
        )
