from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


@dataclass(frozen=True)
class ToneScore:
    sentiment: float  # -1..1 compound
    pos: float
    neu: float
    neg: float
    subjectivity_hint: str


def analyze_tone(text: str) -> Optional[ToneScore]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    scores = _analyzer.polarity_scores(cleaned)
    compound = float(scores.get("compound", 0.0))
    pos = float(scores.get("pos", 0.0))
    neu = float(scores.get("neu", 0.0))
    neg = float(scores.get("neg", 0.0))

    # Rough heuristic: highly polar sentiment often correlates with opinionated tone.
    if abs(compound) < 0.1:
        hint = "Mostly neutral language"
    elif abs(compound) < 0.35:
        hint = "Mildly opinionated tone"
    else:
        hint = "Strongly opinionated tone"

    return ToneScore(
        sentiment=compound,
        pos=pos,
        neu=neu,
        neg=neg,
        subjectivity_hint=hint,
    )
