from __future__ import annotations

from pathlib import Path

import pdfplumber


def extract_text(path: Path) -> str:
    """Extract all text from a PDF, pages joined with newlines.

    Some invoice PDFs (e.g. Dagster's and Hex's Stripe-generated statements)
    use a font whose "(" and minus-sign glyphs pdfplumber can't map to a real
    codepoint, so it emits a literal NUL byte in their place. A NUL directly
    before a "$" is consistently a minus sign on a credit/refund line (e.g.
    "Unused time ... 1 \x00$2.67" is really "-$2.67"); normalize it to "$-"
    to match the "$-X.XX" negative-amount convention _LINE_AMOUNT_RE already
    parses. Every other NUL is a dropped "(" or date-range separator (e.g.
    "Feb 1\x00Feb 28, 2026"), so it becomes a plain space. NUL has no
    legitimate meaning in extracted text, so normalize both cases rather
    than let them silently corrupt amounts or break period regexes.
    """
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return text.replace("\x00$", "$-").replace("\x00", " ")
