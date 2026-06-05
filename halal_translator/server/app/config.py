"""Server configuration, sourced from the environment (secrets stay server-side).

See halal_translator/docs/design.md §8/§9 and CLAUDE.md golden rule #1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # OpenAI realtime translation session (design §8)
    openai_api_key: str
    openai_realtime_url: str          # wss base, no query string
    model: str                        # gpt-realtime-translate
    source_lang: str                  # 'ar' (endpoint auto-detects; kept for metadata)
    target_lang: str                  # 'en' -> session.audio.output.language
    # NOTE: the translation endpoint does NOT support output-voice selection. It uses
    # dynamic voice adaptation (the translation follows the source speaker's tone) —
    # which suits tone-preservation (FR-2). marin/cedar are gpt-realtime(-2) only.
    safety_identifier: str | None     # OpenAI-Safety-Identifier (public exposure only)

    # Local verification output for Checkpoint A (gitignored scratch dir)
    scratch_dir: str

    @property
    def has_api_key(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    """Read settings from the process environment."""
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        openai_realtime_url=os.environ.get(
            "OPENAI_REALTIME_URL", "wss://api.openai.com/v1/realtime/translations"
        ),
        model=os.environ.get("OPENAI_TRANSLATE_MODEL", "gpt-realtime-translate"),
        source_lang=os.environ.get("RELAY_SOURCE_LANG", "ar"),
        target_lang=os.environ.get("RELAY_TARGET_LANG", "en"),
        safety_identifier=(os.environ.get("OPENAI_SAFETY_IDENTIFIER") or None),
        scratch_dir=os.environ.get("RELAY_SCRATCH_DIR", "/scratch"),
    )
