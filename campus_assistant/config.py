"""Settings come from environment variables (never from files in the repo)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = PACKAGE_DIR / "sample"   # ships inside the package, so "pip install ." works too

DEFAULT_MODEL = "gemini-4-hydrogen"        # free tier on the Gemini API (Nov 2026)
FALLBACK_MODEL = "gemini-3.5-flash-lite"   # cheaper / higher free-tier daily limit
DEFAULT_EMBED_MODEL = "gemini-embedding-2"
LANGUAGES = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}
BACKENDS = ("auto", "mock", "gemini")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    backend: str = "auto"
    api_key: str = field(default="", repr=False)   # repr=False: never printed by accident
    model: str = DEFAULT_MODEL
    embed_model: str = DEFAULT_EMBED_MODEL
    use_embeddings: bool = False
    language: str = "en"
    timezone: str = "Asia/Kolkata"
    timetable: Path = SAMPLE_DIR / "timetable.csv"
    faq_dir: Path = SAMPLE_DIR / "faq"
    notes_dir: Path = SAMPLE_DIR / "notes"
    home: Path = Path.home() / ".campus-assistant"
    daily_limit: int = 20          # requests per day we allow ourselves (free tier friendly)
    redact: bool = True            # mask phone numbers, emails, Aadhaar-like numbers before sending
    timeout: int = 60

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        env = os.environ
        s = cls(
            backend=env.get("CAMPUS_BACKEND", "auto"),
            api_key=env.get("GEMINI_API_KEY", "") or env.get("GOOGLE_API_KEY", ""),
            model=env.get("GEMINI_MODEL", DEFAULT_MODEL),
            embed_model=env.get("GEMINI_EMBED_MODEL", DEFAULT_EMBED_MODEL),
            use_embeddings=env.get("CAMPUS_EMBEDDINGS", "0") in ("1", "true", "yes"),
            language=env.get("CAMPUS_LANG", "en"),
            timezone=env.get("CAMPUS_TZ", "Asia/Kolkata"),
            timetable=Path(env.get("CAMPUS_TIMETABLE", SAMPLE_DIR / "timetable.csv")),
            faq_dir=Path(env.get("CAMPUS_FAQ_DIR", SAMPLE_DIR / "faq")),
            notes_dir=Path(env.get("CAMPUS_NOTES_DIR", SAMPLE_DIR / "notes")),
            home=Path(env.get("CAMPUS_HOME", Path.home() / ".campus-assistant")),
            daily_limit=_int("CAMPUS_DAILY_LIMIT", 20),
            redact=env.get("CAMPUS_REDACT", "1") not in ("0", "false", "no"),
            timeout=_int("CAMPUS_TIMEOUT", 60),
        )
        for k, v in overrides.items():
            if v is not None:
                setattr(s, k, v)
        s.validate()
        return s

    def validate(self) -> None:
        if self.backend not in BACKENDS:
            raise ValueError(f"backend must be one of {BACKENDS}, got {self.backend!r}")
        if self.language not in LANGUAGES:
            raise ValueError(f"language must be one of {sorted(LANGUAGES)}, got {self.language!r}")
        if self.daily_limit < 0:
            raise ValueError("daily_limit must be >= 0")

    @property
    def resolved_backend(self) -> str:
        if self.backend == "auto":
            return "gemini" if self.api_key else "mock"
        return self.backend

    def masked_key(self) -> str:
        if not self.api_key:
            return "(not set)"
        return self.api_key[:4] + "…" + f"({len(self.api_key)} chars)"
