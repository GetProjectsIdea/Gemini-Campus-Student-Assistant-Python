"""Guard rails: no API keys or secrets are ever committed."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{35}")


def repo_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not any(part in {".git", ".venv", "__pycache__", ".pytest_cache"} for part in p.parts):
            if p.suffix.lower() not in {".png", ".webp", ".jpg", ".ico"}:
                yield p


def test_no_google_api_keys_in_repo():
    offenders = [str(p.relative_to(ROOT)) for p in repo_files() if KEY_RE.search(p.read_text(errors="ignore"))]
    assert offenders == []


def test_no_env_files_committed():
    assert not (ROOT / ".env").exists()


def test_gitignore_covers_env():
    gi = (ROOT / ".gitignore").read_text()
    assert ".env" in gi and ".campus-assistant/" in gi
