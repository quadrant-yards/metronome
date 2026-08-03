from __future__ import annotations

from metronome.costs.models import CostRow
from metronome.costs.vendors import _stripe_invoice


def detect(text: str) -> bool:
    return "hex.tech" in text.lower()


def parse(text: str, source_file: str) -> list[CostRow]:
    return _stripe_invoice.parse(text, source_file, metric_name="Hex")
