"""Model backends.

* ``GeminiBackend`` calls the Gemini API over HTTPS (REST, standard library only).
* ``MockBackend`` is fully offline and deterministic: it answers by extracting the best
  sentences from the retrieved passages. It powers the demo and the test-suite.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field

from .config import FALLBACK_MODEL, Settings
from .textutil import sentences, tokenize

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class BackendError(RuntimeError):
    def __init__(self, message: str, hint: str = "", status: int | None = None):
        super().__init__(message)
        self.hint = hint
        self.status = status


@dataclass
class Reply:
    text: str
    backend: str
    model: str
    usage: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------------------
# Mock backend
# ----------------------------------------------------------------------------------------
class MockBackend:
    name = "mock"
    model = "mock-extractive"

    def generate(self, prompt: str, system: str = "", task: dict | None = None) -> Reply:
        task = task or {}
        kind = task.get("kind", "general")
        if kind in ("faq", "notes_qa"):
            text = self._answer(task.get("question", ""), task.get("passages", []))
        elif kind == "summary":
            text = self._summary(task.get("text", ""), task.get("bullets", 6))
        elif kind == "flashcards":
            text = self._flashcards(task.get("text", ""), task.get("count", 5))
        elif kind == "timetable":
            text = task.get("facts", "")
        else:
            text = ("I am running in offline mock mode, so I can only answer from your timetable, "
                    "notes and campus documents. Set GEMINI_API_KEY to ask open questions.")
        words = len(prompt.split())
        return Reply(text, self.name, self.model, {"promptWords": words})

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Hashed bag-of-words vectors (256 dims). Not semantic, but deterministic and offline."""
        out = []
        for t in texts:
            v = [0.0] * 256
            for tok in tokenize(t):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % 256] += 1.0 if (h >> 8) % 2 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    # -- helpers --
    @staticmethod
    def _answer(question: str, passages: list[dict]) -> str:
        if not passages:
            return "I could not find this in the documents you gave me."
        q = set(tokenize(question))
        scored = []
        for n, p in enumerate(passages, start=1):
            for pos, s in enumerate(sentences(p["text"])):
                overlap = len(q & set(tokenize(s)))
                if overlap:
                    scored.append((overlap, -n, -pos, s, n))
        if not scored:
            return "I could not find this in the documents you gave me."
        scored.sort(reverse=True)
        best = scored[0][0]
        picked, seen = [], set()
        for overlap, _, _, s, n in scored:
            if overlap < (best if best <= 2 else best - 1) or len(picked) >= 3 or s in seen:
                continue
            seen.add(s)
            picked.append(f"{s} [{n}]")
        return " ".join(picked)

    @staticmethod
    def _summary(text: str, bullets: int = 6) -> str:
        body = re.sub(r"^#+\s.*$", "", text, flags=re.M)
        sents = sentences(body)
        if not sents:
            return "Nothing to summarise."
        freq = Counter(tokenize(body))
        def score(s):
            toks = tokenize(s)
            return sum(freq[t] for t in toks) / (len(toks) ** 0.7 or 1)
        ranked = sorted(range(len(sents)), key=lambda i: -score(sents[i]))[:bullets]
        heads = re.findall(r"^#{2,6}\s+(.*)$", text, flags=re.M)
        raw = Counter(tokenize(body, stemmed=False))
        terms = [t for t, _ in raw.most_common(30) if len(t) > 3][:8]
        out = ["**Summary**"] + [f"- {sents[i]}" for i in sorted(ranked)]
        out += ["", "**Key terms:** " + ", ".join(terms)]
        if heads:
            out += ["", "**Likely exam questions**"]
            out += [f"{n}. Explain {h.split(':')[0].strip()} with an example." for n, h in enumerate(heads[:4], 1)]
        return "\n".join(out)

    @staticmethod
    def _flashcards(text: str, count: int = 5) -> str:
        cards = []
        for m in re.finditer(r"^#{2,6}[ \t]+([^\n]*)\n+(.+?)(?=\n#|\Z)", text, flags=re.M | re.S):
            first = sentences(m.group(2))
            if first:
                head = m.group(1).strip().rstrip("?")
                q = f"{head}?" if head.split()[0].lower() in ("why", "how", "what", "when", "which") else f"What is {head}?"
                cards.append(f"Q: {q}\nA: {first[0]}")
            if len(cards) >= count:
                break
        return "\n\n".join(cards) or "No headings found to build flashcards from."


# ----------------------------------------------------------------------------------------
# Gemini backend (REST)
# ----------------------------------------------------------------------------------------
def _urllib_post(url: str, body: dict, headers: dict, timeout: int) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read() or b"{}")
        except ValueError:
            data = {}
        return exc.code, data, dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BackendError(f"cannot reach the Gemini API: {exc}",
                           "Check your internet connection, or run with --backend mock.") from None


class GeminiBackend:
    name = "gemini"

    def __init__(self, settings: Settings, transport=None, sleep=time.sleep, max_retries: int = 2):
        if not settings.api_key:
            raise BackendError("GEMINI_API_KEY is not set",
                               "Create a free key in Google AI Studio and export GEMINI_API_KEY, "
                               "or use --backend mock.")
        self.settings = settings
        self.model = settings.model
        self.transport = transport or _urllib_post
        self.sleep = sleep
        self.max_retries = max_retries

    def _post(self, path: str, body: dict) -> dict:
        url = f"{API_ROOT}/{path}"
        # The key goes in a header, never in the URL (URLs end up in logs and browser history).
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.settings.api_key}
        for attempt in range(self.max_retries + 1):
            status, data, resp_headers = self.transport(url, body, headers, self.settings.timeout)
            if status == 200:
                return data
            retryable = status == 429 or status >= 500
            if retryable and attempt < self.max_retries:
                wait = _retry_after(resp_headers, data) or (2 ** attempt) * 2
                self.sleep(min(wait, 30))
                continue
            raise _error_for(status, data, self.model)
        raise BackendError("unreachable")  # pragma: no cover

    def generate(self, prompt: str, system: str = "", task: dict | None = None) -> Reply:
        body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._post(f"models/{self.model}:generateContent", body)
        fb = data.get("promptFeedback", {})
        if fb.get("blockReason"):
            raise BackendError(f"Gemini blocked the prompt ({fb['blockReason']})",
                               "Rephrase the question or remove sensitive text.")
        cands = data.get("candidates") or []
        if not cands:
            raise BackendError("Gemini returned no answer", "Try again in a minute.")
        c = cands[0]
        parts = (c.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            reason = c.get("finishReason", "UNKNOWN")
            raise BackendError(f"Gemini returned an empty answer (finishReason={reason})",
                               "Ask a shorter question or try again.")
        return Reply(text.strip(), self.name, data.get("modelVersion", self.model),
                     data.get("usageMetadata", {}))

    def embed(self, texts: list[str]) -> list[list[float]]:
        m = self.settings.embed_model
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):       # batch limit
            batch = texts[i:i + 100]
            body = {"requests": [{"model": f"models/{m}", "content": {"parts": [{"text": t}]},
                                  "outputDimensionality": 768} for t in batch]}
            data = self._post(f"models/{m}:batchEmbedContents", body)
            out.extend(e.get("values", []) for e in data.get("embeddings", []))
        if len(out) != len(texts):
            raise BackendError("embedding count mismatch from Gemini")
        return out


def _retry_after(headers: dict, data: dict) -> float | None:
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            try:
                return float(v)
            except ValueError:
                pass
    for d in (data.get("error") or {}).get("details", []) or []:
        delay = d.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                pass
    return None


def _error_for(status: int, data: dict, model: str) -> BackendError:
    err = data.get("error") or {}
    msg = err.get("message", "") or f"HTTP {status}"
    reason = " ".join(str(d.get("reason", "")) for d in err.get("details", []) or [])
    if status in (401, 403) or "API_KEY_INVALID" in reason or "API key not valid" in msg:
        return BackendError(f"Gemini rejected the API key: {msg}",
                            "Check GEMINI_API_KEY (create one in Google AI Studio).", status)
    if status == 404:
        return BackendError(f"model {model!r} not found: {msg}",
                            f"Set GEMINI_MODEL to a current model, e.g. {FALLBACK_MODEL}.", status)
    if status == 429:
        return BackendError(f"Gemini rate limit or daily quota reached: {msg}",
                            f"Wait a minute, or switch to {FALLBACK_MODEL}, which has a larger free "
                            "daily limit. Free-tier quotas reset at midnight Pacific time.", status)
    if status == 400:
        return BackendError(f"Gemini rejected the request: {msg}", "", status)
    return BackendError(f"Gemini API error {status}: {msg}", "Try again later.", status)


def make_backend(settings: Settings, transport=None):
    if settings.resolved_backend == "gemini":
        return GeminiBackend(settings, transport=transport)
    return MockBackend()
