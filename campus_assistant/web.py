"""Flask UI on 127.0.0.1: Ask, Timetable, Notes and Campus FAQ tabs."""
from __future__ import annotations

from flask import Flask, Response, abort, jsonify, render_template, request

from . import __version__
from .assistant import CampusAssistant
from .backends import BackendError
from .config import LANGUAGES, Settings
from .timetable import DAYS, Timetable, TimetableError
from .usage import QuotaExceeded

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
MAX_TEXT = 200_000


def hostname_of(host_header: str) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[: h.find("]") + 1] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def create_app(settings: Settings | None = None, assistant: CampusAssistant | None = None) -> Flask:
    settings = settings or Settings.from_env()
    bot = assistant or CampusAssistant(settings)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1_000_000
    app.config["BOT"] = bot

    @app.before_request
    def guard():
        if hostname_of(request.host) not in LOCAL_HOSTS and not app.config.get("TESTING_ANY_HOST"):
            abort(403)  # blocks DNS rebinding
        if request.method == "POST" and request.headers.get("X-Campus-Assistant") != "1":
            abort(403)  # simple CSRF guard: other sites cannot add custom headers

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return resp

    @app.errorhandler(BackendError)
    def backend_error(exc):
        return jsonify(error=str(exc), hint=exc.hint), 502

    @app.errorhandler(QuotaExceeded)
    def quota_error(exc):
        return jsonify(error=str(exc), hint="Free-tier friendly limit. Raise CAMPUS_DAILY_LIMIT if you need more."), 429

    @app.errorhandler(TimetableError)
    def tt_error(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(ValueError)
    def value_error(exc):
        return jsonify(error=str(exc)), 400

    def body() -> dict:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("send a JSON object")
        for k, v in data.items():
            if isinstance(v, str) and len(v) > MAX_TEXT:
                raise ValueError(f"field {k!r} is too long")
        return data

    def lang(data: dict):
        value = data.get("lang") or None
        if value is not None and value not in LANGUAGES:
            raise ValueError("lang must be en, hi or hinglish")
        return value

    @app.get("/")
    def index():
        return render_template("index.html", version=__version__, languages=LANGUAGES,
                               backend=bot.backend.name, model=getattr(bot.backend, "model", ""),
                               default_lang=settings.language)

    @app.get("/api/status")
    def status():
        return jsonify(bot.status())

    @app.get("/api/timetable")
    def timetable():
        tt, now = bot.timetable, bot.now()
        nxt = tt.next_class(now)
        cur = tt.current(now)
        today = DAYS[now.weekday()]
        return jsonify(
            now=now.strftime("%a %d %b %Y, %H:%M"), today=today,
            days=[d for d in DAYS if any(s.day == d for s in tt.slots)],
            slots=[s.as_dict() for s in tt.slots],
            current=cur.as_dict() if cur else None,
            next={**nxt[0].as_dict(), "starts": nxt[1].strftime("%a %H:%M")} if nxt else None,
            free_today=[f"{a:%H:%M}-{b:%H:%M}" for a, b in tt.free_slots(today)] if today in DAYS else [],
            clashes=[[a.as_dict(), b.as_dict()] for a, b in tt.clashes()],
            hours=tt.weekly_hours())

    @app.post("/api/timetable/upload")
    def upload_timetable():
        data = body()
        tt = Timetable.from_csv_text(str(data.get("csv", "")))
        if not tt.slots:
            raise ValueError("timetable has no classes")
        bot._timetable = tt  # in memory only; your file on disk is not changed
        return jsonify(ok=True, classes=len(tt.slots), clashes=len(tt.clashes()))

    @app.get("/api/timetable.ics")
    def ics():
        now = bot.now()
        text = bot.timetable.to_ics(now.date(), tz=settings.timezone, stamp=now.replace(tzinfo=None))
        return Response(text, mimetype="text/calendar",
                        headers={"Content-Disposition": "attachment; filename=timetable.ics"})

    @app.post("/api/ask")
    def ask():
        data = body()
        return jsonify(bot.ask(str(data.get("question", "")), language=lang(data)))

    @app.post("/api/faq")
    def faq():
        data = body()
        q = str(data.get("question", "")).strip()
        if not q:
            raise ValueError("question is empty")
        return jsonify(bot.ask_faq(q, language=lang(data)))

    @app.get("/api/faq/sources")
    def faq_sources():
        return jsonify(sources=bot.faq.sources, chunks=len(bot.faq.chunks))

    @app.post("/api/notes/<action>")
    def notes(action):
        data = body()
        text = str(data.get("text", ""))
        source = str(data.get("source") or "pasted-notes")[:120]
        if not text.strip():
            raise ValueError("paste or upload some notes first")
        if action == "summarise":
            return jsonify(bot.summarise(text, source, bullets=int(data.get("bullets", 6)), language=lang(data)))
        if action == "flashcards":
            return jsonify(bot.flashcards(text, source, count=int(data.get("count", 5)), language=lang(data)))
        if action == "ask":
            q = str(data.get("question", "")).strip()
            if not q:
                raise ValueError("question is empty")
            return jsonify(bot.ask_notes(q, text=text, source=source, language=lang(data)))
        abort(404)

    return app


def run(settings: Settings, host: str = "127.0.0.1", port: int = 5077, now=None) -> int:
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("Refusing to listen on a public address: this app is meant for your own laptop.")
        return 2
    app = create_app(settings, assistant=CampusAssistant(settings, now=now))
    bot = app.config["BOT"]
    print(f"Gemini Campus Assistant on http://{host}:{port}  (backend: {bot.backend.name})")
    app.run(host=host, port=port, debug=False)
    return 0
