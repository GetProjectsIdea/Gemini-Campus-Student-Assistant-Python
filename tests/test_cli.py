import json

from campus_assistant.cli import main

NOW = ["--backend", "mock", "--now", "2026-11-23 09:40"]


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_ask_next(capsys):
    code, out, _ = run(capsys, *NOW, "ask", "what", "is", "my", "next", "class")
    assert code == 0 and "Operating Systems" in out and "timetable · local" in out


def test_ask_json(capsys):
    code, out, _ = run(capsys, *NOW, "--json", "ask", "library fine")
    data = json.loads(out)
    assert data["kind"] == "faq" and data["sources"][0]["source"] == "library.md"


def test_faq_with_sources(capsys):
    code, out, _ = run(capsys, *NOW, "faq", "revaluation", "fee")
    assert "Rs 500" in out and "Sources:" in out and "exams.md › Revaluation" in out


def test_faq_list_sources(capsys):
    code, out, _ = run(capsys, *NOW, "faq", "--sources")
    assert "hostel.md" in out.split()


def test_faq_needs_question(capsys):
    code, _, err = run(capsys, *NOW, "faq")
    assert code == 2 and "give a question" in err


def test_timetable_views(capsys):
    assert "Tuesday 24 Nov 2026" in run(capsys, *NOW, "timetable", "tomorrow")[1]
    assert "Thu:" in run(capsys, *NOW, "timetable", "day", "thursday")[1]
    assert "12:15-15:00" in run(capsys, *NOW, "timetable", "free", "wed")[1]
    assert "No clashes." in run(capsys, *NOW, "timetable", "clashes")[1]
    assert "CS351" in run(capsys, *NOW, "timetable", "hours")[1]
    assert "Next class today at 10:00" in run(capsys, *NOW, "timetable", "next")[1]
    assert "Sat:" in run(capsys, *NOW, "timetable", "week")[1]


def test_timetable_day_needs_day(capsys):
    assert run(capsys, *NOW, "timetable", "day")[0] == 2


def test_timetable_clashes_exit_code(capsys, tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("day,start,end,course\nMon,09:00,10:30,A\nMon,10:00,11:00,B")
    code, out, _ = run(capsys, *NOW, "--timetable", str(p), "timetable", "clashes")
    assert code == 1 and "<->" in out


def test_ics_to_file(capsys, tmp_path):
    out_file = tmp_path / "tt.ics"
    code, out, _ = run(capsys, *NOW, "timetable", "ics", "--weeks", "2", "--out", str(out_file))
    assert code == 0 and "wrote 40 events" in out
    assert out_file.read_text().count("BEGIN:VEVENT") == 40


def test_ics_stdout(capsys):
    assert run(capsys, *NOW, "timetable", "ics")[1].startswith("BEGIN:VCALENDAR")


def test_notes_commands(capsys, sample_dir):
    f = str(sample_dir / "notes" / "os-cpu-scheduling.md")
    assert "**Summary**" in run(capsys, *NOW, "notes", "summarise", f, "--bullets", "3")[1]
    assert run(capsys, *NOW, "notes", "flashcards", f, "--count", "2")[1].count("Q: ") == 2
    out = run(capsys, *NOW, "notes", "ask", f, "what", "is", "the", "convoy", "effect")[1]
    assert "convoy effect" in out and "os-cpu-scheduling.md › First Come First Served (FCFS)" in out


def test_notes_missing_file_and_question(capsys, tmp_path, sample_dir):
    assert run(capsys, *NOW, "notes", "summarise", str(tmp_path / "x.md"))[0] == 2
    assert run(capsys, *NOW, "notes", "ask", str(sample_dir / "notes" / "os-cpu-scheduling.md"))[0] == 2


def test_status(capsys):
    code, out, _ = run(capsys, "--backend", "mock", "status")
    assert code == 0 and "mock" in out and "GEMINI_API_KEY is not set" in out


def test_status_json(capsys):
    assert json.loads(run(capsys, "--backend", "mock", "--json", "status")[1])["classes"] == 20


def test_gemini_without_key_fails_cleanly(capsys):
    code, _, err = run(capsys, "--backend", "gemini", "ask", "hi")
    assert code == 2 and "GEMINI_API_KEY" in err and "hint:" in err


def test_bad_now(capsys):
    import pytest
    with pytest.raises(SystemExit):
        main(["--now", "yesterday", "ask", "x"])


def test_demo(capsys):
    code, out, _ = run(capsys, "--backend", "mock", "demo")
    assert code == 0 and "backend=mock" in out and "Summary of os-cpu-scheduling.md" in out


def test_web_refuses_public_bind(capsys):
    code, out, _ = run(capsys, "--backend", "mock", "web", "--host", "0.0.0.0")
    assert code == 2 and "Refusing" in out
