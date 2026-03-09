"""
Deterministic Answer Scorer
────────────────────────────
Computes a baseline answer score (0–100) from transcript metrics.
Fully deterministic — no AI. Auditable and reproducible.
"""

import logging

logger = logging.getLogger('interview_engine.scorer')

# ─── Score Weights ───────────────────────────────────────────────────────────
WEIGHTS = {
    'length':      0.25,   # Did they speak enough?
    'clarity':     0.25,   # Low filler word ratio?
    'relevance':   0.30,   # Technical keyword coverage?
    'vocabulary':  0.20,   # Vocabulary richness?
}

# ─── Thresholds ──────────────────────────────────────────────────────────────
MIN_WORD_COUNT = 150          # Target minimum words for full length score
MAX_FILLER_RATIO = 0.15      # Above this → clarity tanks
MIN_VOCABULARY_RICHNESS = 0.3 # Below this → limited vocabulary


def compute_baseline_score(transcript_metrics: dict) -> float:
    """
    Compute deterministic baseline answer score from transcript metrics.

    Args:
        transcript_metrics: dict from transcript_processor.process_transcript()

    Returns:
        float: baseline score clamped to [0, 100]
    """
    wc = transcript_metrics.get('word_count', 0)

    if wc == 0:
        logger.info("  Empty transcript → baseline = 0")
        return 0.0

    # ── Length Score (0–100) ──────────────────────────────────────────────
    length_score = min(wc / MIN_WORD_COUNT, 1.0) * 100

    # ── Clarity Score (0–100) ────────────────────────────────────────────
    filler_ratio = transcript_metrics.get('filler_ratio', 0)
    if filler_ratio >= MAX_FILLER_RATIO:
        clarity_score = max(0, (1 - filler_ratio) * 60)  # Harsh penalty
    else:
        clarity_score = (1 - filler_ratio / MAX_FILLER_RATIO * 0.4) * 100

    # ── Relevance Score (0–100) ──────────────────────────────────────────
    keyword_ratio = transcript_metrics.get('keyword_match_ratio', 0)
    relevance_score = min(keyword_ratio / 0.15, 1.0) * 100  # 15% coverage = full marks

    # ── Vocabulary Score (0–100) ─────────────────────────────────────────
    vocab_richness = transcript_metrics.get('vocabulary_richness', 0)
    vocabulary_score = min(vocab_richness / 0.5, 1.0) * 100  # 50% unique = full marks

    # ── Weighted Combination ─────────────────────────────────────────────
    baseline = (
        WEIGHTS['length']     * length_score +
        WEIGHTS['clarity']    * clarity_score +
        WEIGHTS['relevance']  * relevance_score +
        WEIGHTS['vocabulary'] * vocabulary_score
    )

    baseline = max(0.0, min(100.0, baseline))

    logger.info(
        f"  Baseline breakdown: "
        f"length={length_score:.1f} clarity={clarity_score:.1f} "
        f"relevance={relevance_score:.1f} vocabulary={vocabulary_score:.1f} "
        f"→ weighted={baseline:.1f}"
    )

    return round(baseline, 2)


def compute_final_answer_score(baseline: float, ai_score: float) -> float:
    """
    Compute final answer score: 70% baseline + 30% AI.

    Args:
        baseline: deterministic baseline score (0–100)
        ai_score: AI evaluation score (0–100)

    Returns:
        float: final answer score (0–100)
    """
    final = (0.70 * baseline) + (0.30 * ai_score)
    final = max(0.0, min(100.0, final))
    logger.info(f"  Final answer score: 70%×{baseline:.1f} + 30%×{ai_score:.1f} = {final:.1f}")
    return round(final, 2)
