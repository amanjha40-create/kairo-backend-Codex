"""Placeholder structures for ML / rules-engine confidence — wire real scores later."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConfidenceScore:
    """Aggregate confidence for automated verification — values populated by extraction + scoring jobs."""

    score: float | None = None
    model_version: str | None = None
    calibrated: bool = False
    notes: str | None = "Reserved for downstream scoring pipeline."

    def to_preview_fragment(self) -> dict[str, Any]:
        """Embed under `employment.extraction_preview['confidence']`."""

        return {
            "score": self.score,
            "model_version": self.model_version,
            "calibrated": self.calibrated,
            "notes": self.notes,
        }
