from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from campus_assistant.assistant import CampusAssistant
from campus_assistant.backends import MockBackend
from campus_assistant.config import SAMPLE_DIR, Settings

IST = ZoneInfo("Asia/Kolkata")
MONDAY_0940 = datetime(2026, 11, 23, 9, 40, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "CAMPUS_BACKEND", "GEMINI_MODEL", "CAMPUS_LANG",
              "CAMPUS_EMBEDDINGS", "CAMPUS_TIMETABLE", "CAMPUS_FAQ_DIR", "CAMPUS_NOTES_DIR", "CAMPUS_DAILY_LIMIT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CAMPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def settings(tmp_path):
    return Settings.from_env(backend="mock", home=tmp_path / "home")


@pytest.fixture
def bot(settings):
    return CampusAssistant(settings, backend=MockBackend(), now=MONDAY_0940)


@pytest.fixture
def sample_dir():
    return SAMPLE_DIR


class FakeTransport:
    """Records requests and replays canned (status, json, headers) responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected extra request")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        status, data = r[0], r[1]
        hdrs = r[2] if len(r) > 2 else {}
        return status, data, hdrs


def gemini_ok(text="Answer [1]", thought=None, usage=None):
    parts = []
    if thought:
        parts.append({"text": thought, "thought": True})
    parts.append({"text": text})
    return (200, {"candidates": [{"content": {"parts": parts, "role": "model"}, "finishReason": "STOP"}],
                  "usageMetadata": usage or {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                  "modelVersion": "gemini-4-hydrogen"})


@pytest.fixture
def fake_transport():
    return FakeTransport
