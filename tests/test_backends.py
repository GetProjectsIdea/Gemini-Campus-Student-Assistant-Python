import pytest

from campus_assistant.backends import (API_ROOT, BackendError, GeminiBackend, MockBackend, _retry_after,
                                       make_backend)
from campus_assistant.config import Settings
from conftest import FakeTransport, gemini_ok

KEY = "test-key-not-real-0123456789"


def gem(transport, **kw):
    s = Settings.from_env(backend="gemini", api_key=KEY, **kw)
    return GeminiBackend(s, transport=transport, sleep=lambda s: None)


# ---- mock -------------------------------------------------------------------------
def test_mock_answer_cites_passages():
    passages = [{"ref": "a", "text": "The library closes at 10 PM. Wi-Fi is free."},
                {"ref": "b", "text": "Mess lunch is at 1 PM."}]
    r = MockBackend().generate("p", task={"kind": "faq", "question": "when does the library close", "passages": passages})
    assert r.text == "The library closes at 10 PM. [1]"
    assert r.backend == "mock"


def test_mock_answer_without_passages():
    r = MockBackend().generate("p", task={"kind": "faq", "question": "x", "passages": []})
    assert "could not find" in r.text


def test_mock_answer_no_overlap():
    r = MockBackend().generate("p", task={"kind": "notes_qa", "question": "zebra",
                                          "passages": [{"ref": "a", "text": "Cats sleep."}]})
    assert "could not find" in r.text


def test_mock_summary_has_sections(sample_dir):
    text = (sample_dir / "notes" / "os-cpu-scheduling.md").read_text()
    r = MockBackend().generate("p", task={"kind": "summary", "text": text, "bullets": 4})
    assert r.text.count("\n- ") == 4
    assert "**Key terms:**" in r.text and "**Likely exam questions**" in r.text


def test_mock_summary_empty():
    assert MockBackend().generate("p", task={"kind": "summary", "text": "# Only title"}).text == "Nothing to summarise."


def test_mock_flashcards(sample_dir):
    text = (sample_dir / "notes" / "dbms-normalization.md").read_text()
    r = MockBackend().generate("p", task={"kind": "flashcards", "text": text, "count": 3})
    assert r.text.count("Q: ") == 3 and r.text.count("A: ") == 3


def test_mock_timetable_passthrough_and_general():
    assert MockBackend().generate("p", task={"kind": "timetable", "facts": "Mon: X"}).text == "Mon: X"
    assert "GEMINI_API_KEY" in MockBackend().generate("p").text


def test_mock_embed_is_normalised_and_deterministic():
    a, b = MockBackend().embed(["library fine", "library fine"])
    assert a == b and len(a) == 256
    assert abs(sum(x * x for x in a) - 1) < 1e-9


# ---- gemini -----------------------------------------------------------------------
def test_gemini_requires_key():
    with pytest.raises(BackendError, match="GEMINI_API_KEY"):
        GeminiBackend(Settings.from_env(backend="gemini"))


def test_gemini_generate_request_shape():
    t = FakeTransport(gemini_ok("Hello [1]"))
    r = gem(t).generate("question?", system="be nice")
    call = t.calls[0]
    assert call["url"] == f"{API_ROOT}/models/gemini-4-hydrogen:generateContent"
    assert call["headers"]["x-goog-api-key"] == KEY
    assert KEY not in call["url"]
    assert call["body"]["contents"][0]["parts"][0]["text"] == "question?"
    assert call["body"]["systemInstruction"]["parts"][0]["text"] == "be nice"
    assert r.text == "Hello [1]" and r.backend == "gemini" and r.usage["totalTokenCount"] == 15


def test_gemini_custom_model():
    t = FakeTransport(gemini_ok())
    gem(t, model="gemini-3.5-flash-lite").generate("q")
    assert "gemini-3.5-flash-lite:generateContent" in t.calls[0]["url"]


def test_gemini_skips_thought_parts():
    t = FakeTransport(gemini_ok("Final", thought="secret reasoning"))
    assert gem(t).generate("q").text == "Final"


def test_gemini_retries_429_then_succeeds():
    sleeps = []
    t = FakeTransport((429, {"error": {"message": "quota"}}, {"Retry-After": "3"}), gemini_ok("ok"))
    s = Settings.from_env(backend="gemini", api_key=KEY)
    r = GeminiBackend(s, transport=t, sleep=sleeps.append).generate("q")
    assert r.text == "ok" and sleeps == [3.0] and len(t.calls) == 2


def test_gemini_retries_5xx_with_backoff():
    sleeps = []
    t = FakeTransport((503, {}), (500, {}), gemini_ok("ok"))
    s = Settings.from_env(backend="gemini", api_key=KEY)
    assert GeminiBackend(s, transport=t, sleep=sleeps.append).generate("q").text == "ok"
    assert sleeps == [2, 4]


def test_gemini_gives_up_after_retries():
    t = FakeTransport(*[(429, {"error": {"message": "Resource exhausted"}})] * 3)
    with pytest.raises(BackendError) as e:
        gem(t).generate("q")
    assert e.value.status == 429 and "flash-lite" in e.value.hint


def test_gemini_bad_key():
    t = FakeTransport((400, {"error": {"message": "API key not valid. Please pass a valid API key.",
                                       "details": [{"reason": "API_KEY_INVALID"}]}}))
    with pytest.raises(BackendError, match="rejected the API key") as e:
        gem(t).generate("q")
    assert KEY not in str(e.value) and len(t.calls) == 1


def test_gemini_403():
    with pytest.raises(BackendError, match="API key"):
        gem(FakeTransport((403, {"error": {"message": "denied"}}))).generate("q")


def test_gemini_model_not_found_hint():
    with pytest.raises(BackendError) as e:
        gem(FakeTransport((404, {"error": {"message": "models/x is not found"}}))).generate("q")
    assert "GEMINI_MODEL" in e.value.hint


def test_gemini_other_400():
    with pytest.raises(BackendError, match="rejected the request"):
        gem(FakeTransport((400, {"error": {"message": "bad field"}}))).generate("q")


def test_gemini_blocked_prompt():
    with pytest.raises(BackendError, match="blocked"):
        gem(FakeTransport((200, {"promptFeedback": {"blockReason": "SAFETY"}}))).generate("q")


def test_gemini_no_candidates():
    with pytest.raises(BackendError, match="no answer"):
        gem(FakeTransport((200, {"candidates": []}))).generate("q")


def test_gemini_empty_text_reports_finish_reason():
    t = FakeTransport((200, {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}))
    with pytest.raises(BackendError, match="MAX_TOKENS"):
        gem(t).generate("q")


def test_gemini_network_error_propagates():
    t = FakeTransport(BackendError("cannot reach the Gemini API", "offline"))
    with pytest.raises(BackendError, match="cannot reach"):
        gem(t).generate("q")


def test_gemini_embed_batches():
    texts = [f"t{i}" for i in range(150)]
    t = FakeTransport((200, {"embeddings": [{"values": [0.1, 0.2]}] * 100}),
                      (200, {"embeddings": [{"values": [0.3, 0.4]}] * 50}))
    vecs = gem(t).embed(texts)
    assert len(vecs) == 150 and len(t.calls) == 2
    assert t.calls[0]["url"].endswith("models/gemini-embedding-2:batchEmbedContents")
    req = t.calls[0]["body"]["requests"][0]
    assert req["model"] == "models/gemini-embedding-2" and req["outputDimensionality"] == 768


def test_gemini_embed_count_mismatch():
    with pytest.raises(BackendError, match="mismatch"):
        gem(FakeTransport((200, {"embeddings": []}))).embed(["a"])


def test_retry_after_from_error_details():
    assert _retry_after({}, {"error": {"details": [{"retryDelay": "7s"}]}}) == 7.0
    assert _retry_after({"retry-after": "x"}, {}) is None


def test_make_backend_auto(monkeypatch):
    assert isinstance(make_backend(Settings.from_env()), MockBackend)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    assert isinstance(make_backend(Settings.from_env()), GeminiBackend)
    assert isinstance(make_backend(Settings.from_env(backend="mock")), MockBackend)


def test_mock_flashcards_question_headings():
    r = MockBackend().generate("p", task={"kind": "flashcards", "text": "## Why normalization\nIt reduces redundancy.\n\n## BCNF\nStronger 3NF.", "count": 5})
    assert "Q: Why normalization?" in r.text and "Q: What is BCNF?" in r.text
