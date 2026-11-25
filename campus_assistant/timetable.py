"""Timetable from a CSV file: today, next class, week view, free slots, clashes and .ics export."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_ALIASES = {
    "monday": "Mon", "mon": "Mon", "somvar": "Mon", "सोमवार": "Mon",
    "tuesday": "Tue", "tue": "Tue", "tues": "Tue", "mangalvar": "Tue", "मंगलवार": "Tue",
    "wednesday": "Wed", "wed": "Wed", "budhvar": "Wed", "बुधवार": "Wed",
    "thursday": "Thu", "thu": "Thu", "thur": "Thu", "thurs": "Thu", "guruvar": "Thu", "गुरुवार": "Thu",
    "friday": "Fri", "fri": "Fri", "shukravar": "Fri", "शुक्रवार": "Fri",
    "saturday": "Sat", "sat": "Sat", "shanivar": "Sat", "शनिवार": "Sat",
    "sunday": "Sun", "sun": "Sun", "ravivar": "Sun", "रविवार": "Sun",
}
REQUIRED = ("day", "start", "end", "course")
FILLER = {"and", "of", "the", "for", "in", "to", "iii", "ii", "iv", "i", "lab", "optional"}
TYPE_WORDS = {"lab": "Lab", "practical": "Lab", "lecture": "Lecture", "tutorial": "Tutorial", "seminar": "Seminar"}


class TimetableError(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    day: str
    start: time
    end: time
    course: str
    code: str = ""
    type: str = ""
    room: str = ""
    faculty: str = ""
    short: str = ""

    @property
    def aliases(self) -> set[str]:
        """Words a student may use for this class: DBMS, CS301, 'networks', initials 'os'..."""
        words = [w for w in re.findall(r"[a-z0-9]+", self.course.lower()) if w not in FILLER]
        out = set(words) | {w[:-1] for w in words if w.endswith("s") and len(w) > 3}
        if self.code:
            out.add(self.code.lower())
        if self.short:
            out |= {a.strip().lower() for a in self.short.split("/") if a.strip()}
        if len(words) >= 2:
            out.add("".join(w[0] for w in words))
        return out

    @property
    def minutes(self) -> int:
        return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)

    def label(self) -> str:
        bits = [f"{self.start:%H:%M}-{self.end:%H:%M}", self.course]
        if self.code:
            bits[-1] += f" ({self.code})"
        if self.type:
            bits.append(self.type)
        if self.room:
            bits.append(self.room)
        if self.faculty:
            bits.append(self.faculty)
        return " | ".join(bits)

    def as_dict(self) -> dict:
        return {"day": self.day, "start": f"{self.start:%H:%M}", "end": f"{self.end:%H:%M}",
                "course": self.course, "code": self.code, "type": self.type, "room": self.room,
                "faculty": self.faculty}


def norm_day(value: str) -> str:
    v = (value or "").strip()
    d = DAY_ALIASES.get(v.lower()) or DAY_ALIASES.get(v)
    if not d:
        raise TimetableError(f"unknown day {value!r}")
    return d


def parse_time(value: str) -> time:
    v = (value or "").strip().upper().replace(".", ":")
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H%M"):
        try:
            return datetime.strptime(v, fmt).time()
        except ValueError:
            continue
    raise TimetableError(f"bad time {value!r} (use 24h HH:MM like 14:00)")


class Timetable:
    def __init__(self, slots: list[Slot]):
        self.slots = sorted(slots, key=lambda s: (DAYS.index(s.day), s.start, s.course))

    # ---- loading --------------------------------------------------------------------
    @classmethod
    def from_csv_text(cls, text: str) -> "Timetable":
        reader = csv.DictReader(io.StringIO(text.strip()))
        if not reader.fieldnames:
            raise TimetableError("empty timetable")
        fields = [f.strip().lower() for f in reader.fieldnames]
        missing = [f for f in REQUIRED if f not in fields]
        if missing:
            raise TimetableError(f"timetable CSV is missing column(s): {', '.join(missing)}")
        slots = []
        for n, raw in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if not any(row.values()):
                continue
            try:
                s = Slot(norm_day(row["day"]), parse_time(row["start"]), parse_time(row["end"]),
                         row["course"], row.get("code", ""), row.get("type", ""),
                         row.get("room", ""), row.get("faculty", ""), row.get("short", ""))
            except TimetableError as exc:
                raise TimetableError(f"line {n}: {exc}") from None
            if not s.course:
                raise TimetableError(f"line {n}: course is empty")
            if s.minutes <= 0:
                raise TimetableError(f"line {n}: end time must be after start time")
            slots.append(s)
        return cls(slots)

    @classmethod
    def load(cls, path: Path | str) -> "Timetable":
        p = Path(path)
        if not p.exists():
            raise TimetableError(f"timetable file not found: {p}")
        return cls.from_csv_text(p.read_text(encoding="utf-8-sig"))

    # ---- queries --------------------------------------------------------------------
    def day(self, day: str) -> list[Slot]:
        d = norm_day(day)
        return [s for s in self.slots if s.day == d]

    def on(self, when: date) -> list[Slot]:
        return self.day(DAYS[when.weekday()])

    def current(self, now: datetime) -> Slot | None:
        t = now.time()
        for s in self.on(now.date()):
            if s.start <= t < s.end:
                return s
        return None

    def next_class(self, now: datetime) -> tuple[Slot, datetime] | None:
        """Next class that has not started yet (looks up to 7 days ahead)."""
        for offset in range(0, 8):
            d = now.date() + timedelta(days=offset)
            for s in self.on(d):
                start = datetime.combine(d, s.start, tzinfo=now.tzinfo)
                if start > now:
                    return s, start
        return None

    def free_slots(self, day: str, start: str = "09:00", end: str = "17:00",
                   min_minutes: int = 30) -> list[tuple[time, time]]:
        day_start, day_end = parse_time(start), parse_time(end)
        cursor = day_start
        free = []
        for s in self.day(day):
            if s.end <= day_start or s.start >= day_end:
                continue
            if s.start > cursor:
                free.append((cursor, min(s.start, day_end)))
            cursor = max(cursor, s.end)
        if cursor < day_end:
            free.append((cursor, day_end))

        def mins(a, b):
            return (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
        return [(a, b) for a, b in free if mins(a, b) >= min_minutes]

    def clashes(self) -> list[tuple[Slot, Slot]]:
        out = []
        for d in DAYS:
            items = [s for s in self.slots if s.day == d]
            for i, a in enumerate(items):
                for b in items[i + 1:]:
                    if b.start < a.end and a.start < b.end:
                        out.append((a, b))
        return out

    def weekly_hours(self) -> dict[str, float]:
        hours: dict[str, float] = {}
        for s in self.slots:
            key = s.code or s.course
            hours[key] = hours.get(key, 0) + s.minutes / 60
        return dict(sorted(hours.items(), key=lambda kv: -kv[1]))

    def match(self, question: str) -> list[Slot]:
        """Classes a question is about: 'when is the DBMS lab?' -> the DBMS Lab slots."""
        q = set(re.findall(r"[a-z0-9]+", question.lower()))
        want_type = {TYPE_WORDS[w] for w in q if w in TYPE_WORDS}
        scored = []
        for s in self.slots:
            hit = len(q & s.aliases)
            if not hit:
                continue
            score = hit + (1 if s.type in want_type or (want_type and "lab" in s.course.lower() and "Lab" in want_type) else 0)
            scored.append((score, s))
        if not scored:
            return []
        best = max(sc for sc, _ in scored)
        return [s for sc, s in scored if sc == best]

    def find(self, text: str) -> list[Slot]:
        t = text.lower()
        return [s for s in self.slots if t in s.course.lower() or (s.code and t in s.code.lower())
                or (s.faculty and t in s.faculty.lower())]

    # ---- output ---------------------------------------------------------------------
    def to_ics(self, week_start: date, weeks: int = 1, tz: str = "Asia/Kolkata",
               stamp: datetime | None = None) -> str:
        """iCalendar file you can import into Google Calendar (one event per class)."""
        stamp = stamp or datetime(2026, 1, 1)
        monday = week_start - timedelta(days=week_start.weekday())
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GetProjects//Gemini Campus Assistant//EN",
                 "CALSCALE:GREGORIAN", f"X-WR-TIMEZONE:{tz}"]
        for w in range(weeks):
            for n, s in enumerate(self.slots):
                d = monday + timedelta(days=7 * w + DAYS.index(s.day))
                uid = f"{d:%Y%m%d}-{s.start:%H%M}-{(s.code or s.course).replace(' ', '')}-{n}@campus-assistant"
                lines += ["BEGIN:VEVENT", f"UID:{_ics_escape(uid)}", f"DTSTAMP:{stamp:%Y%m%dT%H%M%S}Z",
                          f"DTSTART;TZID={tz}:{d:%Y%m%d}T{s.start:%H%M}00",
                          f"DTEND;TZID={tz}:{d:%Y%m%d}T{s.end:%H%M}00",
                          f"SUMMARY:{_ics_escape(s.course + (' (' + s.type + ')' if s.type else ''))}"]
                if s.room:
                    lines.append(f"LOCATION:{_ics_escape(s.room)}")
                if s.faculty:
                    lines.append(f"DESCRIPTION:{_ics_escape(s.faculty)}")
                lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"

    def render_day(self, day: str) -> str:
        items = self.day(day)
        if not items:
            return f"{norm_day(day)}: no classes"
        return "\n".join([f"{norm_day(day)}:"] + [f"  {s.label()}" for s in items])

    def render_week(self) -> str:
        days = [d for d in DAYS if any(s.day == d for s in self.slots)]
        return "\n\n".join(self.render_day(d) for d in days)


def _ics_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
