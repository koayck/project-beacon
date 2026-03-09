"""
Project Beacon — backend entry point.

Usage:
    uv run python main.py
    uv run uvicorn main:app --reload   # dev mode with auto-reload
"""
import uvicorn
from backend.app import app  # noqa: F401 (re-exported for uvicorn)

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
