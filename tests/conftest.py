"""Root conftest: load .env before any test module is imported."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env so SUPABASE_DB_URL (and other secrets) are
# available when backend.db.repository is first imported by test modules.
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_ROOT / ".env", override=False)
