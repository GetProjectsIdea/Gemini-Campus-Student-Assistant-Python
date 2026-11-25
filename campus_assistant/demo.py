"""Offline tour: python -m campus_assistant demo"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .assistant import CampusAssistant
from .backends import MockBackend
from .config import SAMPLE_DIR, Settings

QUESTIONS = [
    "What is my next class?",
    "kal kaunsi classes hai?",
    "When is the DBMS lab?",
    "Library timings on Saturday?",
    "What is the fine for a late library book?",
    "How much attendance do I need to sit the end-sem exam?",
    "What is transitive dependency in 3NF?",
    "Who won the cricket world cup?",
]


def run_demo(settings: Settings | None = None, now: datetime | None = None) -> int:
    settings = settings or Settings.from_env(backend="mock")
    now = now or datetime(2026, 11, 23, 9, 40, tzinfo=ZoneInfo(settings.timezone))
    backend = None if settings.resolved_backend == "gemini" else MockBackend()
    bot = CampusAssistant(settings, backend=backend, now=now)
    print(f"Gemini Campus Assistant demo · backend={bot.backend.name} · now={now:%a %d %b %Y %H:%M}\n")
    for q in QUESTIONS:
        res = bot.ask(q)
        print(f"Q: {q}\n{res['answer']}")
        if res.get("sources") and res["kind"] in ("faq", "notes_qa"):
            print("   sources: " + "; ".join(s["ref"] for s in res["sources"][:2]))
        print(f"   [{res['kind']} · {res['backend']}]\n")
    notes = (SAMPLE_DIR / "notes" / "os-cpu-scheduling.md").read_text()
    print("Summary of os-cpu-scheduling.md:\n" + bot.summarise(notes, "os-cpu-scheduling.md", bullets=4)["answer"])
    return 0
