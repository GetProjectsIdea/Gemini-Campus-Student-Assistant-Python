from datetime import date

import pytest

from campus_assistant.config import DEFAULT_MODEL, Settings
from campus_assistant.usage import QuotaExceeded, UsageTracker


def test_defaults():
    s = Settings.from_env()
    assert s.backend == "auto" and s.resolved_backend == "mock" and s.model == DEFAULT_MODEL
    assert s.language == "en" and s.daily_limit == 20 and s.redact


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 39)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("CAMPUS_LANG", "hinglish")
    monkeypatch.setenv("CAMPUS_DAILY_LIMIT", "50")
    monkeypatch.setenv("CAMPUS_EMBEDDINGS", "1")
    s = Settings.from_env()
    assert s.resolved_backend == "gemini" and s.model == "gemini-3.5-flash-lite"
    assert s.language == "hinglish" and s.daily_limit == 50 and s.use_embeddings


def test_google_api_key_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g" * 39)
    assert Settings.from_env().api_key == "g" * 39


def test_bad_int_env_uses_default(monkeypatch):
    monkeypatch.setenv("CAMPUS_DAILY_LIMIT", "lots")
    assert Settings.from_env().daily_limit == 20


def test_overrides_win_over_env(monkeypatch):
    monkeypatch.setenv("CAMPUS_LANG", "hi")
    assert Settings.from_env(language="en").language == "en"


@pytest.mark.parametrize("kw", [{"backend": "openai"}, {"language": "fr"}, {"daily_limit": -1}])
def test_validation(kw):
    with pytest.raises(ValueError):
        Settings.from_env(**kw)


def test_key_never_in_repr_and_masked():
    s = Settings.from_env(api_key="AIzaSySECRETSECRETSECRETSECRET1234567")
    assert "SECRET" not in repr(s)
    assert "SECRET" not in s.masked_key() and s.masked_key().startswith("AIza")
    assert Settings.from_env().masked_key() == "(not set)"


def test_usage_counts_and_limits(tmp_path):
    u = UsageTracker(tmp_path / "u.json", limit=2, today=lambda: date(2026, 11, 25))
    assert u.used() == 0 and u.remaining() == 2
    u.check_and_add()
    u.check_and_add()
    assert u.used() == 2 and u.remaining() == 0
    with pytest.raises(QuotaExceeded):
        u.check_and_add()


def test_usage_resets_next_day(tmp_path):
    p = tmp_path / "u.json"
    UsageTracker(p, 1, today=lambda: date(2026, 11, 25)).check_and_add()
    u2 = UsageTracker(p, 1, today=lambda: date(2026, 11, 26))
    assert u2.used() == 0
    u2.check_and_add()


def test_usage_unlimited(tmp_path):
    u = UsageTracker(tmp_path / "u.json", limit=0)
    for _ in range(30):
        u.check_and_add()
    assert u.remaining() is None and u.used() == 30


def test_usage_file_is_private_and_survives_corruption(tmp_path):
    p = tmp_path / "u.json"
    p.write_text("{not json")
    u = UsageTracker(p, 5)
    assert u.used() == 0
    u.check_and_add()
    assert oct(p.stat().st_mode & 0o777) == "0o600"
