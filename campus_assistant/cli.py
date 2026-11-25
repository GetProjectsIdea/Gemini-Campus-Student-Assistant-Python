"""Command line interface: python -m campus_assistant <command> ..."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .assistant import CampusAssistant
from .backends import BackendError
from .config import BACKENDS, LANGUAGES, Settings
from .timetable import DAYS, TimetableError, norm_day
from .usage import QuotaExceeded

C = {"b": "\x1b[1m", "dim": "\x1b[2m", "g": "\x1b[32m", "y": "\x1b[33m", "c": "\x1b[36m", "r": "\x1b[31m", "0": "\x1b[0m"}


def color(enabled: bool):
    def paint(code: str, text: str) -> str:
        return f"{C[code]}{text}{C['0']}" if enabled else text
    return paint


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="campus-assistant",
                                description="Gemini campus & student assistant: timetable, notes and campus FAQ.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--backend", choices=BACKENDS, help="auto (default) uses Gemini if GEMINI_API_KEY is set")
    p.add_argument("--model", help="Gemini model id (default gemini-4-hydrogen)")
    p.add_argument("--lang", choices=sorted(LANGUAGES), help="answer language: en, hi or hinglish")
    p.add_argument("--embeddings", action="store_true", help="hybrid search: re-rank BM25 hits with embeddings")
    p.add_argument("--timetable", type=Path, help="timetable CSV file")
    p.add_argument("--faq-dir", type=Path, help="folder with campus FAQ .md/.txt files")
    p.add_argument("--notes-dir", type=Path, help="folder with your notes .md/.txt files")
    p.add_argument("--now", help='pretend the time is "YYYY-MM-DD HH:MM" (for demos and tests)')
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("--no-color", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ask", help="ask anything: routed to timetable, notes or campus FAQ")
    a.add_argument("question", nargs="+")

    t = sub.add_parser("timetable", help="timetable views")
    t.add_argument("view", choices=["today", "tomorrow", "next", "week", "day", "free", "clashes", "hours", "ics"])
    t.add_argument("day", nargs="?", help="day for 'day' / 'free' (Mon..Sun)")
    t.add_argument("--weeks", type=int, default=1, help="weeks to export with 'ics'")
    t.add_argument("--out", type=Path, help="write the .ics file here")

    f = sub.add_parser("faq", help="ask the campus FAQ (retrieval + citations)")
    f.add_argument("question", nargs="*")
    f.add_argument("-k", type=int, default=4, help="passages to retrieve")
    f.add_argument("--sources", action="store_true", help="list indexed FAQ files and exit")

    n = sub.add_parser("notes", help="summarise notes, make flashcards, or ask questions about them")
    n.add_argument("action", choices=["summarise", "summarize", "flashcards", "ask"])
    n.add_argument("file", type=Path)
    n.add_argument("question", nargs="*")
    n.add_argument("--bullets", type=int, default=6)
    n.add_argument("--count", type=int, default=5)

    sub.add_parser("status", help="show backend, model, key status (masked) and loaded data")
    sub.add_parser("demo", help="run an offline tour of every feature")
    w = sub.add_parser("web", help="start the Flask UI on http://127.0.0.1:5077")
    w.add_argument("--port", type=int, default=5077)
    w.add_argument("--host", default="127.0.0.1")
    return p


def settings_from(args) -> Settings:
    return Settings.from_env(backend=args.backend, model=args.model, language=args.lang,
                             use_embeddings=True if args.embeddings else None,
                             timetable=args.timetable, faq_dir=args.faq_dir, notes_dir=args.notes_dir)


def parse_now(value: str | None, tz: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        raise SystemExit(f"--now must look like '2026-11-23 09:30', got {value!r}")


def print_result(res: dict, paint, as_json: bool) -> None:
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return
    print(res["answer"])
    srcs = res.get("sources") or []
    if srcs and res.get("kind") in ("faq", "notes_qa"):
        print()
        print(paint("dim", "Sources:"))
        for i, s in enumerate(srcs, 1):
            print(paint("dim", f"  [{i}] {s['ref']}  (score {s.get('score', '-')})"))
    meta = f"{res.get('kind')} · {res.get('backend')} · {res.get('model')}"
    if res.get("redactions"):
        meta += " · redacted " + ", ".join(f"{k}x{v}" for k, v in res["redactions"].items())
    print(paint("dim", f"\n— {meta}"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paint = color(sys.stdout.isatty() and not args.no_color and not os.environ.get("NO_COLOR"))
    try:
        settings = settings_from(args)
        now = parse_now(args.now, settings.timezone)
        if args.cmd == "web":
            from .web import run
            return run(settings, host=args.host, port=args.port, now=now)
        if args.cmd == "demo":
            from .demo import run_demo
            return run_demo(settings, now=now)
        bot = CampusAssistant(settings, now=now)
        return dispatch(args, bot, paint)
    except (BackendError,) as exc:
        print(paint("r", f"error: {exc}"), file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        return 2
    except (QuotaExceeded, TimetableError, ValueError, FileNotFoundError) as exc:
        print(paint("r", f"error: {exc}"), file=sys.stderr)
        return 2


def dispatch(args, bot: CampusAssistant, paint) -> int:
    if args.cmd == "status":
        info = bot.status()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            for k, v in info.items():
                print(f"{paint('c', k.ljust(12))} {v}")
            if info["backend"] == "mock":
                print(paint("y", "\nGEMINI_API_KEY is not set: running offline with the mock backend."))
        return 0
    if args.cmd == "ask":
        print_result(bot.ask(" ".join(args.question)), paint, args.json)
        return 0
    if args.cmd == "faq":
        if args.sources:
            for s in bot.faq.sources:
                print(s)
            return 0
        if not args.question:
            raise ValueError("give a question, e.g. faq \"library timings on saturday\"")
        print_result(bot.ask_faq(" ".join(args.question), k=args.k), paint, args.json)
        return 0
    if args.cmd == "notes":
        if not args.file.exists():
            raise FileNotFoundError(f"notes file not found: {args.file}")
        text = args.file.read_text(encoding="utf-8")
        if args.action in ("summarise", "summarize"):
            res = bot.summarise(text, args.file.name, bullets=args.bullets)
        elif args.action == "flashcards":
            res = bot.flashcards(text, args.file.name, count=args.count)
        else:
            if not args.question:
                raise ValueError("give a question after the file name")
            res = bot.ask_notes(" ".join(args.question), text=text, source=args.file.name)
        print_result(res, paint, args.json)
        return 0
    if args.cmd == "timetable":
        return timetable_cmd(args, bot, paint)
    return 1  # pragma: no cover


def timetable_cmd(args, bot: CampusAssistant, paint) -> int:
    tt, now = bot.timetable, bot.now()
    v = args.view
    if v in ("today", "tomorrow", "next", "week"):
        q = {"today": "today's classes", "tomorrow": "tomorrow's classes",
             "next": "next class", "week": "week timetable"}[v]
        res = bot.ask_timetable(q, language="en")
        print(json.dumps(res, indent=2) if args.json else res["answer"])
    elif v == "day":
        if not args.day:
            raise ValueError("give a day, e.g. timetable day thu")
        print(tt.render_day(args.day))
    elif v == "free":
        day = norm_day(args.day) if args.day else DAYS[now.weekday()]
        free = tt.free_slots(day)
        print(f"Free slots on {day} (09:00-17:00, 30 min+):")
        for a, b in free:
            print(f"  {a:%H:%M}-{b:%H:%M}")
        if not free:
            print("  none")
    elif v == "clashes":
        cl = tt.clashes()
        print("No clashes." if not cl else "\n".join(f"{a.day}: {a.label()} <-> {b.label()}" for a, b in cl))
        return 1 if cl else 0
    elif v == "hours":
        for code, h in tt.weekly_hours().items():
            print(f"  {code:<8} {h:4.1f} h/week")
    elif v == "ics":
        ics = tt.to_ics(now.date(), weeks=args.weeks, tz=bot.settings.timezone, stamp=now.replace(tzinfo=None))
        if args.out:
            args.out.write_text(ics)
            print(f"wrote {ics.count('BEGIN:VEVENT')} events to {args.out} (import it into Google Calendar)")
        else:
            sys.stdout.write(ics)
    return 0
