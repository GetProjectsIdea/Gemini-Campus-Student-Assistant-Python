"""Small text helpers: tokenising (English + Hindi), sentences, chunking and PII redaction."""
from __future__ import annotations

import re
from dataclasses import dataclass

STOPWORDS = set("""a an the and or but if then else of to in on at by for with from is are was were be been
being it its this that these those as do does did can could should would will shall may might must
i me my we our you your he she they them their what which who whom when where why how there here
about into over under than too very not no yes so such only own same just also any all each other
some more most few both up down out off again further once per vs via am has have had having
hai ka ki ke ko se me mein kya kab kaha kahan kaun kyun kaise aur ya bhi tha thi the ho hota hoti
batao bata please plz tell give""".split())

_TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*|[\u0900-\u097F]+", re.I)


def tokenize(text: str, keep_stopwords: bool = False, stemmed: bool = True) -> list[str]:
    toks = [t.lower() for t in _TOKEN.findall(text or "")]
    out = []
    for t in toks:
        if not keep_stopwords and t in STOPWORDS:
            continue
        out.append(stem(t) if stemmed else t)
    return out


def stem(t: str) -> str:
    """Very light English stemmer: enough for 'timings' ~ 'timing', 'books' ~ 'book'."""
    if not t.isascii() or len(t) <= 3:
        return t
    if t.endswith("ly") and len(t) > 6:
        t = t[:-2]
    if t.endswith("ency") and len(t) > 6:
        return t[:-4] + "ent"
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith(("sses", "xes", "ches", "shes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


_SENT = re.compile(r"(?<=[.!?।])\s+(?=[A-Z0-9\u0900-\u097F\"'(])")


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in _SENT.split(text) if s.strip()]


@dataclass
class Chunk:
    source: str      # file name
    heading: str     # nearest markdown heading
    text: str
    idx: int = 0

    @property
    def ref(self) -> str:
        return f"{self.source} › {self.heading}" if self.heading else self.source


def chunk_markdown(text: str, source: str, max_words: int = 160) -> list[Chunk]:
    """Split markdown by headings, then by paragraphs so a chunk stays under max_words."""
    chunks: list[Chunk] = []
    heading, buf = "", []
    title = ""

    def flush():
        para_text = "\n".join(buf).strip()
        if not para_text:
            return
        words, cur = 0, []
        for para in re.split(r"\n\s*\n", para_text):
            n = len(para.split())
            if cur and words + n > max_words:
                chunks.append(Chunk(source, heading or title, "\n\n".join(cur)))
                cur, words = [], 0
            cur.append(para.strip())
            words += n
        if cur:
            chunks.append(Chunk(source, heading or title, "\n\n".join(cur)))

    for line in (text or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            buf = []
            if len(m.group(1)) == 1 and not title:
                title = m.group(2).strip()
                heading = ""
            else:
                heading = m.group(2).strip()
            continue
        buf.append(line)
    flush()
    for i, c in enumerate(chunks):
        c.idx = i
    return chunks


# --- privacy: redact before anything leaves the laptop -------------------------------------
_REDACTIONS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PHONE", re.compile(r"(?<![\w-])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Mask emails, Aadhaar-like 12-digit numbers, Indian mobile numbers and PAN numbers."""
    counts: dict[str, int] = {}
    for label, rx in _REDACTIONS:
        text, n = rx.subn(f"[{label}]", text)
        if n:
            counts[label] = n
    return text, counts


def clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.7)]
    tail = text[-int(max_chars * 0.25):]
    return head + "\n\n[... trimmed ...]\n\n" + tail
