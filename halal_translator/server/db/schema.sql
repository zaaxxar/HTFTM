-- RELAY metadata schema (PostgreSQL 16) — design §6.
-- Loaded by the postgres image on first init (docker-entrypoint-initdb.d).
-- Audio blobs live in MinIO/local volume; only METADATA lives here (golden rule #3).
-- gen_random_uuid() is built into core Postgres (>= 13).

-- One row per translation session / event.
CREATE TABLE events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT        NOT NULL,
    source_lang      TEXT        NOT NULL DEFAULT 'ar',
    target_lang      TEXT        NOT NULL DEFAULT 'en',
    openai_voice     TEXT        NOT NULL DEFAULT 'marin'
                     CHECK (openai_voice IN ('marin', 'cedar')),
    save_recording   BOOLEAN     NOT NULL DEFAULT true,   -- FR-15 opt-out; enforced at M2 (recording)
    generate_article BOOLEAN     NOT NULL DEFAULT true,   -- FR-15 opt-out; enforced at M6 (article)
    status           TEXT        NOT NULL DEFAULT 'created'
                     CHECK (status IN ('created','armed','live','stopping','stopped','failed')),
    started_at       TIMESTAMPTZ,           -- set when first going live
    stopped_at       TIMESTAMPTZ,           -- set on finalize
    duration_seconds INTEGER,               -- filled on stop
    operator         TEXT,                  -- who started it (nullable until auth, M5)
    error            TEXT,                  -- last fatal error, if status='failed'
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per stored audio artifact. Exactly one 'original' and one 'translated' per event/format.
CREATE TABLE recordings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    kind             TEXT NOT NULL CHECK (kind IN ('original','translated')),
    storage_backend  TEXT NOT NULL DEFAULT 'minio' CHECK (storage_backend IN ('minio','local')),
    bucket           TEXT NOT NULL,         -- e.g. 'relay-recordings'
    object_key       TEXT NOT NULL,         -- e.g. 'events/<id>/translated.mp3'
    format           TEXT NOT NULL DEFAULT 'mp3' CHECK (format IN ('mp3','wav','pcm16')),
    sample_rate_hz   INTEGER NOT NULL DEFAULT 24000,
    channels         SMALLINT NOT NULL DEFAULT 1,
    bitrate_kbps     INTEGER,               -- e.g. 192 for exported MP3 (NFR-3)
    size_bytes       BIGINT,
    duration_seconds NUMERIC(10,3),
    sha256           TEXT,
    status           TEXT NOT NULL DEFAULT 'recording'
                     CHECK (status IN ('recording','finalizing','ready','failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at     TIMESTAMPTZ,
    UNIQUE (event_id, kind, format)         -- one original + one translated per format
);
CREATE INDEX idx_recordings_event ON recordings(event_id);

-- Translated transcript, segmented with timing. Feeds live subtitles (FR-13) + the article (FR-14).
CREATE TABLE transcript_segments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,           -- monotonically increasing per event
    t_start_ms  INTEGER NOT NULL,           -- ms from event start
    t_end_ms    INTEGER,
    text        TEXT NOT NULL,
    is_final    BOOLEAN NOT NULL DEFAULT false,  -- false = interim delta, true = settled
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, seq)
);
CREATE INDEX idx_transcript_event_seq ON transcript_segments(event_id, seq);

-- Post-event generated article + summary (FR-14). One (or more revisions) per event.
CREATE TABLE articles (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id      UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    model         TEXT NOT NULL,            -- text model used
    title         TEXT,
    summary       TEXT,
    body_markdown TEXT,
    status        TEXT NOT NULL DEFAULT 'generated'
                  CHECK (status IN ('generated','published')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_articles_event ON articles(event_id);
