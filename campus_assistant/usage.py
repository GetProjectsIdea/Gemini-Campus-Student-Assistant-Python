"""Tiny daily request counter so a student does not burn the free Gemini quota by accident."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path


class QuotaExceeded(RuntimeError):
    pass


class UsageTracker:
    def __init__(self, path: Path, limit: int, today=date.today):
        self.path = Path(path)
        self.limit = limit
        self.today = today

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def used(self) -> int:
        return int(self._load().get(self.today().isoformat(), 0))

    def remaining(self) -> int | None:
        return None if self.limit == 0 else max(0, self.limit - self.used())

    def check_and_add(self, n: int = 1) -> int:
        """Count n API requests. limit 0 means unlimited."""
        data = self._load()
        key = self.today().isoformat()
        used = int(data.get(key, 0))
        if self.limit and used + n > self.limit:
            raise QuotaExceeded(f"daily limit of {self.limit} Gemini requests reached "
                                f"(set CAMPUS_DAILY_LIMIT to change it)")
        data = {key: used + n}           # keep only today
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return used + n
