import pytest

from campus_assistant.assistant import CampusAssistant
from campus_assistant.backends import MockBackend
from campus_assistant.web import create_app, hostname_of
from conftest import MONDAY_0940

H = {"X-Campus-Assistant": "1"}


@pytest.fixture
def client(settings):
    bot = CampusAssistant(settings, backend=MockBackend(), now=MONDAY_0940)
    app = create_app(settings, assistant=bot)
    return app.test_client()


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Campus Saathi" in r.data and b"Offline mock backend" in r.data
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_static(client):
    assert client.get("/static/app.js").status_code == 200


def test_status(client):
    assert client.get("/api/status").get_json()["classes"] == 20


def test_timetable(client):
    t = client.get("/api/timetable").get_json()
    assert t["today"] == "Mon" and t["current"]["code"] == "CS301" and t["next"]["code"] == "CS302"
    assert t["free_today"] == ["12:15-14:00"] and t["clashes"] == [] and len(t["slots"]) == 20


def test_ics(client):
    r = client.get("/api/timetable.ics")
    assert r.mimetype == "text/calendar" and b"BEGIN:VEVENT" in r.data


def test_ask(client):
    r = client.post("/api/ask", json={"question": "library fine"}, headers=H)
    assert r.status_code == 200 and "Rs 2" in r.get_json()["answer"]


def test_ask_requires_csrf_header(client):
    assert client.post("/api/ask", json={"question": "x"}).status_code == 403


def test_bad_host_blocked(client):
    assert client.get("/", headers={"Host": "evil.example:5077"}).status_code == 403


@pytest.mark.parametrize("h,expected", [("localhost:5077", "localhost"), ("[::1]:5077", "[::1]"),
                                        ("127.0.0.1", "127.0.0.1"), ("Evil.COM:80", "evil.com")])
def test_hostname_of(h, expected):
    assert hostname_of(h) == expected


def test_faq_and_validation(client):
    assert "Rs 500" in client.post("/api/faq", json={"question": "revaluation fee"}, headers=H).get_json()["answer"]
    assert client.post("/api/faq", json={"question": " "}, headers=H).status_code == 400
    assert client.post("/api/faq", json={"question": "x", "lang": "fr"}, headers=H).status_code == 400
    assert client.post("/api/faq", data="nope", headers=H).status_code == 400


def test_faq_sources(client):
    assert "exams.md" in client.get("/api/faq/sources").get_json()["sources"]


def test_notes_endpoints(client, sample_dir):
    text = (sample_dir / "notes" / "dbms-normalization.md").read_text()
    s = client.post("/api/notes/summarise", json={"text": text, "source": "dbms.md"}, headers=H).get_json()
    assert s["kind"] == "summary"
    f = client.post("/api/notes/flashcards", json={"text": text, "count": 2}, headers=H).get_json()
    assert f["answer"].count("Q: ") == 2
    a = client.post("/api/notes/ask", json={"text": text, "question": "what is BCNF"}, headers=H).get_json()
    assert "super key" in a["answer"]


def test_notes_errors(client):
    assert client.post("/api/notes/summarise", json={"text": ""}, headers=H).status_code == 400
    assert client.post("/api/notes/ask", json={"text": "## A\nb", "question": ""}, headers=H).status_code == 400
    assert client.post("/api/notes/nope", json={"text": "x"}, headers=H).status_code == 404
    assert client.post("/api/notes/summarise", json={"text": "x" * 200_001}, headers=H).status_code == 400


def test_upload_timetable(client):
    csv = "day,start,end,course\nMon,09:00,10:30,A\nMon,10:00,11:00,B"
    r = client.post("/api/timetable/upload", json={"csv": csv}, headers=H).get_json()
    assert r == {"ok": True, "classes": 2, "clashes": 1}
    assert len(client.get("/api/timetable").get_json()["slots"]) == 2


def test_upload_bad_timetable(client):
    r = client.post("/api/timetable/upload", json={"csv": "day,start\nMon,9"}, headers=H)
    assert r.status_code == 400 and "missing column" in r.get_json()["error"]
    assert client.post("/api/timetable/upload", json={"csv": "day,start,end,course\n"}, headers=H).status_code == 400


def test_backend_error_maps_to_502(settings):
    from campus_assistant.backends import BackendError

    class Broken(MockBackend):
        def generate(self, *a, **k):
            raise BackendError("Gemini down", "try later")
    app = create_app(settings, assistant=CampusAssistant(settings, backend=Broken(), now=MONDAY_0940))
    r = app.test_client().post("/api/faq", json={"question": "library fine"}, headers=H)
    assert r.status_code == 502 and r.get_json()["hint"] == "try later"
