"""
Text sentiment scoring for filings / news headlines / earnings-call snippets.

Two backends:
  * FinBERT (ProsusAI/finbert via HuggingFace transformers) -- a BERT model
    fine-tuned specifically on financial text. This is the recommended
    backend for real use: general-purpose sentiment models routinely get
    financial language wrong (e.g. "shares tumbled" read as neutral, or
    "aggressive cost cutting" read as negative when it's often a positive
    signal for distressed-company turnarounds).
  * VADER (offline, lexicon-based, no model download) -- used automatically
    as a fallback when transformers/torch aren't installed or a model can't
    be downloaded (e.g. no internet access). Good enough to exercise the
    pipeline end-to-end, but noticeably weaker on financial jargon.

Both backends expose the same interface: score_text(text) -> float in [-1, 1],
where -1 = very negative, +1 = very positive.
"""

from functools import lru_cache

_BACKEND = None  # "finbert" or "vader", decided lazily on first use


def _try_load_finbert():
    from transformers import pipeline  # noqa: local import, optional dependency
    return pipeline("sentiment-analysis", model="ProsusAI/finbert")


@lru_cache(maxsize=1)
def _get_backend():
    global _BACKEND
    try:
        clf = _try_load_finbert()
        _BACKEND = "finbert"
        return clf
    except Exception:
        # transformers/torch not installed, or no network to fetch the model.
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _BACKEND = "vader"
        return SentimentIntensityAnalyzer()


def backend_name() -> str:
    _get_backend()
    return _BACKEND


def score_text(text: str) -> float:
    """Return a single sentiment score in [-1, 1] for a piece of text."""
    backend = _get_backend()

    if _BACKEND == "finbert":
        result = backend(text[:512])[0]  # truncate to model's max length
        label, prob = result["label"].lower(), result["score"]
        if label == "positive":
            return prob
        elif label == "negative":
            return -prob
        return 0.0

    else:  # vader
        scores = backend.polarity_scores(text)
        return scores["compound"]  # already in [-1, 1]


def score_documents(texts: list[str]) -> float:
    """Average sentiment across multiple snippets (e.g. several headlines),
    which is usually more stable than scoring a single headline alone."""
    if not texts:
        return 0.0
    return sum(score_text(t) for t in texts) / len(texts)


if __name__ == "__main__":
    samples = [
        "Company reports record quarterly revenue and raises full-year guidance.",
        "Auditor issues going concern warning amid mounting debt and cash burn.",
        "Shares halted after SEC opens investigation into accounting irregularities.",
    ]
    print(f"Using backend: {backend_name()}\n")
    for s in samples:
        print(f"{score_text(s):+.3f}  {s}")
