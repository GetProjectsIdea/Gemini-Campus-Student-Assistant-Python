"""BM25 retrieval over markdown chunks, with optional Gemini-embedding re-ranking.

BM25 runs locally and needs no API calls, so FAQ search works offline. If embeddings are
enabled, the top BM25 candidates are re-ranked by cosine similarity (hybrid search).
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .textutil import Chunk, chunk_markdown, tokenize


@dataclass
class Hit:
    chunk: Chunk
    score: float

    def as_dict(self) -> dict:
        return {"source": self.chunk.source, "heading": self.chunk.heading, "ref": self.chunk.ref,
                "score": round(self.score, 3), "text": self.chunk.text}


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        # Headings carry a lot of meaning in FAQ files, so they are indexed twice.
        self.docs = [tokenize(f"{c.heading} {c.heading} {c.text}") for c in chunks]
        self.tf = [Counter(d) for d in self.docs]
        self.len = [len(d) for d in self.docs]
        self.avgdl = (sum(self.len) / len(self.len)) if self.len else 0.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def __len__(self) -> int:
        return len(self.chunks)

    def score(self, q_tokens: list[str], i: int) -> float:
        tf, dl, s = self.tf[i], self.len[i], 0.0
        for t in q_tokens:
            f = tf.get(t, 0)
            if not f:
                continue
            idf = self.idf.get(t, 0.0)
            s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
        return s

    def search(self, query: str, k: int = 4) -> list[Hit]:
        q = tokenize(query)
        if not q or not self.chunks:
            return []
        hits = [Hit(self.chunks[i], self.score(q, i)) for i in range(len(self.chunks))]
        hits = [h for h in hits if h.score > 0]
        hits.sort(key=lambda h: (-h.score, h.chunk.source, h.chunk.idx))
        return hits[:k]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgeBase:
    """A folder of .md/.txt files -> chunks -> BM25 (+ optional embeddings cache)."""

    def __init__(self, folder: Path | str, embedder=None, cache_path: Path | None = None):
        self.folder = Path(folder)
        self.embedder = embedder        # object with .embed(list[str]) -> list[list[float]]
        self.cache_path = cache_path
        self.chunks: list[Chunk] = []
        for path in sorted(self.folder.glob("*")):
            if path.suffix.lower() in (".md", ".txt") and path.is_file():
                self.chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), path.name))
        self.index = BM25Index(self.chunks)
        self._vectors: dict[str, list[float]] | None = None

    @classmethod
    def from_text(cls, text: str, source: str = "notes") -> "KnowledgeBase":
        kb = cls.__new__(cls)
        kb.folder, kb.embedder, kb.cache_path = Path("."), None, None
        kb.chunks = chunk_markdown(text, source)
        kb.index = BM25Index(kb.chunks)
        kb._vectors = None
        return kb

    @property
    def sources(self) -> list[str]:
        return sorted({c.source for c in self.chunks})

    def _key(self, c: Chunk) -> str:
        return f"{c.source}#{c.idx}:" + hashlib.sha1(c.text.encode()).hexdigest()[:12]

    def vectors(self) -> dict[str, list[float]]:
        if self._vectors is not None:
            return self._vectors
        cache: dict[str, list[float]] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                cache = json.loads(self.cache_path.read_text())
            except (OSError, ValueError):
                cache = {}
        missing = [c for c in self.chunks if self._key(c) not in cache]
        if missing and self.embedder is not None:
            vecs = self.embedder.embed([f"{c.heading}\n{c.text}" for c in missing])
            for c, v in zip(missing, vecs):
                cache[self._key(c)] = v
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(cache))
        self._vectors = cache
        return cache

    def search(self, query: str, k: int = 4) -> list[Hit]:
        hits = self.index.search(query, k=max(k * 3, 8) if self.embedder else k)
        if not self.embedder or not hits:
            return hits[:k]
        vecs = self.vectors()
        qv = self.embedder.embed([query])[0]
        top = max(h.score for h in hits) or 1.0
        rescored = []
        for h in hits:
            v = vecs.get(self._key(h.chunk))
            sim = cosine(qv, v) if v else 0.0
            # hybrid: keep keyword evidence, add semantic similarity
            rescored.append(Hit(h.chunk, 0.5 * h.score + 0.5 * sim * top))
        rescored.sort(key=lambda h: -h.score)
        return rescored[:k]
