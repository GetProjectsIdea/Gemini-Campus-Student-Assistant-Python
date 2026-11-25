from datetime import datetime

import pytest

from campus_assistant.assistant import CampusAssistant
from campus_assistant.backends import GeminiBackend, MockBackend
from campus_assistant.config import Settings
from campus_assistant.usage import QuotaExceeded
from conftest import IST, MONDAY_0940, FakeTransport, gemini_ok


def live_bot(tmp_path, transport, **kw):
    s = Settings.from_env(backend="gemini", api_key="test-key-xyz", home=tmp_path / "h", **kw)
    return CampusAssistant(s, backend=GeminiBackend(s, transport=transport, sleep=lambda x: None), now=MONDAY_0940)


def test_next_class(bot):
    res = bot.ask("What is my next class?")
    assert res["kind"] == "timetable" and res["intent"] == "next"
    assert "Now (Mon 09:40)" in res["answer"] and "Operating Systems" in res["answer"] and "in 20 min" in res["answer"]
    assert res["backend"] == "local"


def test_tomorrow_hinglish_question(bot):
    res = bot.ask("kal kaunsi classes hai?")
    assert res["answer"].startswith("Tuesday 24 Nov 2026") and "Computer Networks" in res["answer"]


def test_course_lookup(bot):
    res = bot.ask("When is the DBMS lab?")
    assert res["intent"] == "course" and "Mon 14:00-17:00 | DBMS Lab" in res["answer"]
    assert "Mathematics" not in res["answer"]


def test_course_on_day(bot):
    res = bot.ask("Where is the CN lab on Thursday?")
    assert res["answer"].startswith("Thu 14:00-16:00 | Computer Networks Lab")


def test_free_and_week_and_clashes(bot):
    assert "12:15-15:00" in bot.ask("free slots on wednesday")["answer"]
    assert "Sat:" in bot.ask("show my week timetable")["answer"]
    assert "No clashes" in bot.ask("any clashes in my timetable?")["answer"]


def test_next_class_on_saturday_evening(settings):
    b = CampusAssistant(settings, backend=MockBackend(), now=datetime(2026, 11, 28, 20, 0, tzinfo=IST))
    ans = b.ask("next class")["answer"]
    assert "on Monday" in ans and "Database Management Systems" in ans


def test_faq_answer_with_sources(bot):
    res = bot.ask("What is the fine for a late library book?")
    assert res["kind"] == "faq" and res["found"]
    assert "Rs 2 per book per day" in res["answer"] and "[1]" in res["answer"]
    assert res["sources"][0]["ref"] == "library.md › Library fine"


def test_faq_hinglish(bot):
    res = bot.ask("hostel gate kab band hota hai?")
    assert "10:00 PM" in res["answer"] and res["sources"][0]["source"] == "hostel.md"


def test_faq_not_found_does_not_call_model(settings):
    class Never(MockBackend):
        def generate(self, *a, **k):
            raise AssertionError("model must not be called")
    b = CampusAssistant(settings, backend=Never(), now=MONDAY_0940)
    res = b.ask_faq("canteen menu today")
    assert not res["found"] and "could not find" in res["answer"]


def test_notes_routing(bot):
    res = bot.ask("What is transitive dependency in 3NF?")
    assert res["kind"] == "notes_qa"
    assert res["sources"][0]["heading"] == "Third normal form (3NF)"
    assert "transitively dependent" in res["answer"]


def test_ask_notes_with_pasted_text(bot):
    res = bot.ask_notes("what is round robin", text="## RR\nRound Robin gives each process a time quantum.", source="os.md")
    assert "time quantum" in res["answer"] and res["sources"][0]["ref"] == "os.md › RR"


def test_general_question_offline(bot):
    res = bot.ask("Who won the cricket world cup?")
    assert res["kind"] == "general" and "mock" in res["answer"]


def test_empty_question(bot):
    with pytest.raises(ValueError):
        bot.ask("   ")


def test_summarise_and_flashcards(bot, sample_dir):
    text = (sample_dir / "notes" / "dbms-normalization.md").read_text()
    s = bot.summarise(text, "dbms.md", bullets=3)
    assert s["kind"] == "summary" and s["answer"].count("\n- ") == 3
    f = bot.flashcards(text, "dbms.md", count=2)
    assert f["answer"].count("Q: ") == 2


def test_summarise_empty(bot):
    with pytest.raises(ValueError):
        bot.summarise("  ")


def test_redaction_before_model(settings):
    seen = {}

    class Spy(MockBackend):
        def generate(self, prompt, system="", task=None):
            seen["prompt"] = prompt
            return super().generate(prompt, system, task)
    b = CampusAssistant(settings, backend=Spy(), now=MONDAY_0940)
    res = b.summarise("## Me\nCall me on 9876543210 or riya@college.edu. DBMS is fun.", "me.md")
    assert "9876543210" not in seen["prompt"] and "[PHONE]" in seen["prompt"]
    assert res["redactions"] == {"EMAIL": 1, "PHONE": 1}


def test_redaction_can_be_disabled(tmp_path):
    s = Settings.from_env(backend="mock", home=tmp_path, redact=False)
    res = CampusAssistant(s, backend=MockBackend()).summarise("## A\nCall 9876543210 today.")
    assert res["redactions"] == {}


def test_live_faq_uses_gemini_and_counts_quota(tmp_path):
    t = FakeTransport(gemini_ok("The library fine is Rs 2 per day [1]."))
    b = live_bot(tmp_path, t)
    res = b.ask("What is the library fine?")
    assert res["backend"] == "gemini" and res["answer"].startswith("The library fine")
    prompt = t.calls[0]["body"]["contents"][0]["parts"][0]["text"]
    assert "<context>" in prompt and "library.md › Library fine" in prompt
    assert "Answer ONLY from the text inside <context>" in t.calls[0]["body"]["systemInstruction"]["parts"][0]["text"]
    assert b.usage.used() == 1


def test_live_timetable_english_needs_no_api_call(tmp_path):
    b = live_bot(tmp_path, FakeTransport())
    assert b.ask("next class")["backend"] == "local"
    assert b.usage.used() == 0


def test_live_timetable_hindi_is_rephrased(tmp_path):
    t = FakeTransport(gemini_ok("अगली क्लास 10:00 बजे Operating Systems है।"))
    b = live_bot(tmp_path, t)
    res = b.ask("next class", language="hi")
    assert res["backend"] == "gemini" and "Operating Systems" in res["answer"]
    assert "Hindi (Devanagari" in t.calls[0]["body"]["systemInstruction"]["parts"][0]["text"]


def test_live_general_question(tmp_path):
    b = live_bot(tmp_path, FakeTransport(gemini_ok("General knowledge: ...")))
    res = b.ask("Explain photosynthesis briefly")
    assert res["kind"] == "general" and res["backend"] == "gemini"


def test_live_daily_limit(tmp_path):
    b = live_bot(tmp_path, FakeTransport(gemini_ok("a")), daily_limit=1)
    b.ask_faq("library fine")
    with pytest.raises(QuotaExceeded):
        b.ask_faq("revaluation fee")


def test_embeddings_mode(tmp_path):
    s = Settings.from_env(backend="mock", home=tmp_path, use_embeddings=True)
    b = CampusAssistant(s, backend=MockBackend(), now=MONDAY_0940)
    assert b.ask_faq("library fine")["sources"][0]["source"] == "library.md"
    assert (tmp_path / "emb-faq-mock.json").exists()


def test_status(bot):
    st = bot.status()
    assert st["backend"] == "mock" and st["classes"] == 20 and st["api_key"] == "(not set)"
    assert "library.md" in st["faq_files"]


def test_bad_timetable_in_ask(tmp_path):
    bad = tmp_path / "t.csv"
    bad.write_text("day,start,end,course\nMon,10:00,09:00,X")
    s = Settings.from_env(backend="mock", home=tmp_path, timetable=bad)
    res = CampusAssistant(s, backend=MockBackend(), now=MONDAY_0940).ask("next class")
    assert "Timetable problem" in res["answer"]
    assert "error" in str(CampusAssistant(s, backend=MockBackend()).status()["classes"])


def test_small_pasted_notes_not_found_for_unrelated_question(bot):
    res = bot.ask_notes("hostel mess timings", text="## RR\nRound Robin gives each process a time quantum.")
    assert not res["found"]


def test_weak_passages_are_dropped(bot):
    res = bot.ask_faq("Library timings on Saturday?")
    top = res["sources"][0]["score"]
    assert all(s["score"] >= 0.4 * top for s in res["sources"])
    assert "anti-ragging-helpdesk.md" not in [s["source"] for s in res["sources"]]
