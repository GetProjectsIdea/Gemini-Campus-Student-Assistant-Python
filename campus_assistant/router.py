"""Decide which tool answers a question: timetable, notes, campus FAQ or general."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .timetable import DAY_ALIASES, DAYS

TIMETABLE_WORDS = {
    "class", "classes", "lecture", "lectures", "lab", "labs", "timetable", "time-table", "schedule",
    "period", "periods", "tutorial", "next", "today", "tomorrow", "free", "slot", "slots", "room",
    "aaj", "kal", "agla", "agli", "parso", "khali", "clash", "clashes", "week", "weekly", "seminar",
    "आज", "कल", "क्लास", "लैब",
}
STRONG_TIMETABLE = {"timetable", "time-table", "schedule", "next", "tomorrow", "today", "aaj", "kal",
                    "agla", "agli", "free", "khali", "clash", "clashes", "आज", "कल"}
NOTES_WORDS = {"notes", "note", "summarise", "summarize", "summary", "flashcard", "flashcards",
               "revise", "revision", "unit", "chapter", "explain", "define", "difference"}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9-]+|[\u0900-\u097F]+", text.lower())


def is_timetable_question(text: str) -> bool:
    w = set(words(text))
    if w & STRONG_TIMETABLE:
        return True
    if any(d in w for d in DAY_ALIASES) and w & TIMETABLE_WORDS:
        return True
    return len(w & TIMETABLE_WORDS) >= 2 or bool(re.search(r"\bwhen is\b.*\b(class|lab|lecture)\b", text.lower()))


def is_notes_question(text: str) -> bool:
    return bool(set(words(text)) & NOTES_WORDS)


def target_day(text: str, now: datetime) -> date | None:
    w = words(text)
    ws = set(w)
    if ws & {"tomorrow", "kal", "कल"}:
        return now.date() + timedelta(days=1)
    if ws & {"parso"}:
        return now.date() + timedelta(days=2)
    if ws & {"today", "aaj", "आज"}:
        return now.date()
    for token in w:
        if token in DAY_ALIASES:
            want = DAYS.index(DAY_ALIASES[token])
            delta = (want - now.weekday()) % 7
            return now.date() + timedelta(days=delta)
    return None


def timetable_intent(text: str) -> str:
    w = set(words(text))
    if w & {"free", "khali", "gap", "slot", "slots"}:
        return "free"
    if w & {"clash", "clashes", "overlap"}:
        return "clashes"
    if w & {"week", "weekly", "hafte", "pura"}:
        return "week"
    if w & {"next", "agla", "agli", "now", "abhi"}:
        return "next"
    return "day"


WHEN_WORDS = {"when", "where", "kab", "kahan", "kaha", "kidhar", "time", "timing", "kitne", "baje", "कब", "कहाँ"}


def asks_when(text: str) -> bool:
    return bool(set(words(text)) & WHEN_WORDS)
