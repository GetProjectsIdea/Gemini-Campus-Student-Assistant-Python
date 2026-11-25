"""CampusAssistant: glues timetable, notes, FAQ retrieval and the model backend together."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import prompts, router
from .backends import BackendError, MockBackend, make_backend
from .config import Settings
from .retrieval import KnowledgeBase
from .textutil import clip, redact, tokenize
from .timetable import DAYS, Timetable, TimetableError
from .usage import QuotaExceeded, UsageTracker

MIN_SCORE = 1.2          # below this BM25 score we say "not found" instead of guessing
KEEP_RATIO = 0.4        # keep passages scoring at least 40% of the best one
MAX_NOTE_CHARS = 60_000  # keep prompts small: cheaper and faster on the free tier


class CampusAssistant:
    def __init__(self, settings: Settings | None = None, backend=None, now=None):
        self.settings = settings or Settings.from_env()
        self.backend = backend or make_backend(self.settings)
        self._now = now
        self.usage = UsageTracker(self.settings.home / "usage.json", self.settings.daily_limit)
        self._timetable: Timetable | None = None
        self._faq: KnowledgeBase | None = None
        self._notes: KnowledgeBase | None = None

    # ---- lazy resources -------------------------------------------------------------
    def now(self) -> datetime:
        if self._now is not None:
            return self._now() if callable(self._now) else self._now
        return datetime.now(ZoneInfo(self.settings.timezone))

    @property
    def timetable(self) -> Timetable:
        if self._timetable is None:
            self._timetable = Timetable.load(self.settings.timetable)
        return self._timetable

    def _embedder(self):
        return self.backend if self.settings.use_embeddings else None

    @property
    def faq(self) -> KnowledgeBase:
        if self._faq is None:
            cache = self.settings.home / f"emb-faq-{self.backend.name}.json"
            self._faq = KnowledgeBase(self.settings.faq_dir, self._embedder(), cache)
        return self._faq

    @property
    def notes(self) -> KnowledgeBase:
        if self._notes is None:
            cache = self.settings.home / f"emb-notes-{self.backend.name}.json"
            self._notes = KnowledgeBase(self.settings.notes_dir, self._embedder(), cache)
        return self._notes

    @property
    def is_live(self) -> bool:
        return not isinstance(self.backend, MockBackend)

    # ---- model call -----------------------------------------------------------------
    def _call(self, prompt: str, task: dict, language: str | None = None) -> dict:
        lang = language or self.settings.language
        redactions: dict = {}
        if self.settings.redact:
            prompt, redactions = redact(prompt)
        if self.is_live:
            self.usage.check_and_add(1)
        reply = self.backend.generate(prompt, prompts.system_prompt(lang), task)
        return {"answer": reply.text, "backend": reply.backend, "model": reply.model,
                "usage": reply.usage, "redactions": redactions, "language": lang}

    # ---- timetable ------------------------------------------------------------------
    def timetable_facts(self, question: str) -> tuple[str, str]:
        tt, now = self.timetable, self.now()
        intent = router.timetable_intent(question)
        day = router.target_day(question, now)
        if intent == "next" and day in (None, now.date()):
            cur = tt.current(now)
            nxt = tt.next_class(now)
            lines = []
            if cur:
                lines.append(f"Now ({now:%a %H:%M}): {cur.label()} (ends {cur.end:%H:%M})")
            if nxt:
                slot, start = nxt
                mins = int((start - now).total_seconds() // 60)
                when = "today" if start.date() == now.date() else f"on {start:%A}"
                lines.append(f"Next class {when} at {slot.start:%H:%M} (in {_human(mins)}): {slot.label()}")
            return intent, "\n".join(lines) or "No upcoming classes in the timetable."
        if intent == "free":
            d = DAYS[(day or now.date()).weekday()]
            free = tt.free_slots(d)
            if not free:
                return intent, f"{d}: no free slot of 30 minutes or more between 09:00 and 17:00."
            return intent, f"Free slots on {d} (09:00-17:00): " + ", ".join(
                f"{a:%H:%M}-{b:%H:%M}" for a, b in free)
        if intent == "clashes":
            cl = tt.clashes()
            if not cl:
                return intent, "No clashes: no two classes overlap."
            return intent, "Clashes:\n" + "\n".join(f"{a.day}: {a.label()}  <->  {b.label()}" for a, b in cl)
        if intent == "week":
            return intent, tt.render_week()
        # a specific course?  "when is DBMS lab", "OS kab hai"
        found = tt.match(question)
        if found and day is None:
            return "course", "\n".join(f"{s.day} {s.label()}" for s in found)
        if found and day is not None:
            on_day = [s for s in found if s.day == DAYS[day.weekday()]]
            if on_day:
                return "course", "\n".join(f"{s.day} {s.label()}" for s in on_day)
        day = day or now.date()
        return "day", f"{day:%A %d %b %Y}\n" + tt.render_day(DAYS[day.weekday()])

    def ask_timetable(self, question: str, language: str | None = None) -> dict:
        intent, facts = self.timetable_facts(question)
        lang = language or self.settings.language
        base = {"kind": "timetable", "intent": intent, "facts": facts, "sources": [
            {"ref": Path(self.settings.timetable).name, "text": facts}]}
        # Timetable answers are computed locally. English answers need no API call at all
        # (saves free-tier quota). Hindi/Hinglish are rephrased by Gemini when it is available.
        if lang == "en" or not self.is_live:
            return {**base, "answer": facts, "backend": "local", "model": "timetable-csv",
                    "usage": {}, "redactions": {}, "language": lang}
        res = self._call(prompts.timetable_prompt(question, facts),
                         {"kind": "timetable", "facts": facts}, lang)
        return {**base, **res}

    # ---- retrieval Q&A --------------------------------------------------------------
    def _qa(self, kb: KnowledgeBase, question: str, kind: str, k: int, language: str | None) -> dict:
        hits = kb.search(question, k=k)
        if hits:
            # drop weak tail passages: fewer tokens sent, fewer off-topic citations
            hits = [h for h in hits if h.score >= KEEP_RATIO * hits[0].score]
        passages = [h.as_dict() for h in hits]
        if not hits or not _relevant(question, hits[0]):
            return {"kind": kind, "answer": "I could not find this in the campus documents. Please ask "
                    "the relevant office (academic section, hostel warden or TPO).",
                    "sources": passages, "backend": "local", "model": "bm25", "usage": {},
                    "redactions": {}, "language": language or self.settings.language, "found": False}
        res = self._call(prompts.qa_prompt(question, passages),
                         {"kind": kind, "question": question, "passages": passages}, language)
        return {"kind": kind, "sources": passages, "found": True, **res}

    def ask_faq(self, question: str, k: int = 4, language: str | None = None) -> dict:
        return self._qa(self.faq, question, "faq", k, language)

    def ask_notes(self, question: str, text: str | None = None, source: str = "notes",
                  k: int = 4, language: str | None = None) -> dict:
        kb = KnowledgeBase.from_text(text, source) if text is not None else self.notes
        return self._qa(kb, question, "notes_qa", k, language)

    def summarise(self, text: str, source: str = "notes", bullets: int = 6,
                  language: str | None = None) -> dict:
        if not text.strip():
            raise ValueError("notes are empty")
        text = clip(text, MAX_NOTE_CHARS)
        lang = language or self.settings.language
        res = self._call(prompts.summary_prompt(text, source, bullets, lang),
                         {"kind": "summary", "text": text, "bullets": bullets}, lang)
        return {"kind": "summary", "sources": [{"ref": source, "text": text[:400]}], **res}

    def flashcards(self, text: str, source: str = "notes", count: int = 5,
                   language: str | None = None) -> dict:
        text = clip(text, MAX_NOTE_CHARS)
        res = self._call(prompts.flashcards_prompt(text, source, count),
                         {"kind": "flashcards", "text": text, "count": count}, language)
        return {"kind": "flashcards", "sources": [{"ref": source, "text": text[:400]}], **res}

    # ---- router ---------------------------------------------------------------------
    def ask(self, question: str, language: str | None = None) -> dict:
        question = (question or "").strip()
        if not question:
            raise ValueError("question is empty")
        course_q = False
        if router.asks_when(question):
            try:
                course_q = bool(self.timetable.match(question))
            except TimetableError:
                course_q = False
        if course_q or router.is_timetable_question(question):
            try:
                return self.ask_timetable(question, language)
            except TimetableError as exc:
                return {"kind": "timetable", "answer": f"Timetable problem: {exc}", "sources": [],
                        "backend": "local", "model": "timetable-csv", "usage": {}, "redactions": {}}
        faq_hits = self.faq.search(question, k=1)
        note_hits = self.notes.search(question, k=1)
        fs = faq_hits[0].score if faq_hits else 0.0
        ns = note_hits[0].score if note_hits else 0.0
        if router.is_notes_question(question):
            ns *= 1.5
        if max(fs, ns) >= MIN_SCORE:
            return self.ask_notes(question, language=language) if ns > fs else self.ask_faq(question, language=language)
        if self.is_live:
            res = self._call(prompts.general_prompt(question), {"kind": "general"}, language)
            return {"kind": "general", "sources": [], **res}
        return {"kind": "general", "sources": [], "found": False, "backend": "local", "model": "bm25",
                "usage": {}, "redactions": {}, "language": language or self.settings.language,
                "answer": "I could not find this in your timetable, notes or campus documents. "
                          "(Offline mock mode: set GEMINI_API_KEY for general study questions.)"}

    def status(self) -> dict:
        s = self.settings
        info = {"backend": self.backend.name, "model": getattr(self.backend, "model", ""),
                "api_key": s.masked_key(), "embeddings": s.use_embeddings,
                "language": s.language, "timezone": s.timezone,
                "daily_limit": s.daily_limit, "used_today": self.usage.used(),
                "timetable": str(s.timetable), "faq_dir": str(s.faq_dir), "notes_dir": str(s.notes_dir)}
        try:
            info["classes"] = len(self.timetable.slots)
        except TimetableError as exc:
            info["classes"] = f"error: {exc}"
        info["faq_chunks"] = len(self.faq.chunks)
        info["faq_files"] = self.faq.sources
        info["notes_files"] = self.notes.sources
        return info


def _relevant(question: str, hit) -> bool:
    """BM25 scores are small for tiny documents, so also accept good word coverage."""
    if hit.score >= MIN_SCORE:
        return True
    q = set(tokenize(question))
    if not q:
        return False
    covered = q & set(tokenize(f"{hit.chunk.heading} {hit.chunk.text}"))
    return len(covered) / len(q) >= 0.6


def _human(mins: int) -> str:
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d} d {h} h"
    return f"{h} h {m} min" if m else f"{h} h"


__all__ = ["CampusAssistant", "BackendError", "QuotaExceeded", "TimetableError"]
