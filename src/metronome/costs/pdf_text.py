from __future__ import annotations

from pathlib import Path

import pdfplumber


def extract_text(path: Path) -> str:
    """Extract all text from a PDF, pages joined with newlines."""
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)
