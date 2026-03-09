"""
Resume scoring and fraud detection.
All calculations are deterministic — no AI, no randomness.
"""

import re
import logging
from collections import Counter

logger = logging.getLogger('resume_engine.scorer')


# ─── Fraud Detection ─────────────────────────────────────────────────────────

BUZZWORDS = [
    'synergy', 'paradigm', 'leverage', 'innovative', 'revolutionary',
    'disruptive', 'world-class', 'cutting-edge', 'best-in-class',
    'game-changing', 'next-generation', 'thought leader', 'guru',
    'rockstar', 'ninja', 'wizard', 'unicorn', 'visionary',
    'unparalleled', 'groundbreaking', 'transformative',
]

SUPERLATIVES = [
    'best', 'top', 'leading', 'greatest', 'most talented',
    'number one', '#1', 'first-ever', 'only person',
    'single-handedly', 'unmatched', 'unrivaled',
]


def calculate_fraud_probability(text: str) -> float:
    """
    Deterministic fraud signal analysis.
    Returns a probability between 0.0 (clean) and 1.0 (highly suspicious).
    """
    logger.info("🚨 Running fraud detection...")

    if not text or len(text) < 50:
        logger.info("   ⚠ Text too short — skipping fraud check")
        return 0.0

    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)
    word_count = len(words)
    logger.info(f"   📝 Word count: {word_count}")

    if word_count == 0:
        return 0.0

    signals = []

    # Signal 1: Buzzword density (weight: 0.30)
    buzz_count = sum(1 for b in BUZZWORDS if b in text_lower)
    buzz_density = buzz_count / max(word_count / 100, 1)
    sig1 = min(buzz_density / 3.0, 1.0) * 0.30
    signals.append(sig1)
    logger.info(f"   Signal 1 — Buzzwords: {buzz_count} found, density={buzz_density:.3f}, signal={sig1:.4f}")

    # Signal 2: Superlative frequency (weight: 0.25)
    super_count = sum(1 for s in SUPERLATIVES if s in text_lower)
    super_ratio = super_count / max(word_count / 200, 1)
    sig2 = min(super_ratio / 2.0, 1.0) * 0.25
    signals.append(sig2)
    logger.info(f"   Signal 2 — Superlatives: {super_count} found, ratio={super_ratio:.3f}, signal={sig2:.4f}")

    # Signal 3: Duplicate phrase detection (weight: 0.20)
    if word_count >= 6:
        trigrams = [' '.join(words[i:i+3]) for i in range(len(words) - 2)]
        trigram_counts = Counter(trigrams)
        duplicates = sum(1 for _, c in trigram_counts.items() if c > 2)
        dup_ratio = duplicates / max(len(trigrams), 1)
        sig3 = min(dup_ratio * 10, 1.0) * 0.20
        signals.append(sig3)
        logger.info(f"   Signal 3 — Duplicates: {duplicates} repeated trigrams, signal={sig3:.4f}")
    else:
        signals.append(0)

    # Signal 4: Unrealistic experience claims (weight: 0.25)
    unrealistic = 0
    exp_matches = re.findall(r'(\d+)\+?\s*(?:years?|yrs?)', text_lower)
    for exp in exp_matches:
        if int(exp) > 30:
            unrealistic += 1
    leadership = len(re.findall(r'\b(ceo|cto|cfo|founder|co-founder|vp|director)\b', text_lower))
    if leadership > 3:
        unrealistic += 1
    sig4 = min(unrealistic / 2.0, 1.0) * 0.25
    signals.append(sig4)
    logger.info(f"   Signal 4 — Unrealistic claims: {unrealistic}, leadership={leadership}, signal={sig4:.4f}")

    fraud_prob = round(min(sum(signals), 1.0), 3)
    logger.info(f"   ✅ Fraud probability: {fraud_prob} ({fraud_level(fraud_prob)})")
    return fraud_prob


# ─── Score Calculation ────────────────────────────────────────────────────────

def calculate_scores(parsed_data: dict, fraud_probability: float, github_data: dict = None) -> dict:
    """
    Compute the locked resume intelligence score.

    Formula:
        resume_intelligence_score =
            (50% × skill_score)
          + (20% × identity_score)
          + (30% × github_score)
          - fraud_penalty

    All scores are 0–100. Final score is clamped to 0–100.
    """
    logger.info("🧮 Computing resume intelligence score...")

    # Skill score
    skill_count = parsed_data.get('skill_count', 0)
    skill_score = min((skill_count / 10) * 100, 100)
    logger.info(f"   Skill score:    {skill_score:.1f}  ({skill_count} skills / 10 × 100)")

    # Identity score
    identity_fields = ['full_name', 'email', 'phone', 'location']
    identity_hits = sum(1 for f in identity_fields if parsed_data.get(f))
    identity_score = identity_hits * 25
    logger.info(f"   Identity score: {identity_score:.1f}  ({identity_hits}/4 fields × 25)")

    # GitHub score
    github_score = 0
    if github_data:
        github_score = github_data.get('github_score', 0)
    logger.info(f"   GitHub score:   {github_score:.1f}")

    # Fraud penalty
    fraud_penalty = fraud_probability * 30
    logger.info(f"   Fraud penalty:  -{fraud_penalty:.1f}  ({fraud_probability} × 30)")

    # Final calculation
    resume_score = (
        0.50 * skill_score +
        0.20 * identity_score +
        0.30 * github_score -
        fraud_penalty
    )
    resume_score = round(max(0, min(resume_score, 100)), 1)
    logger.info(f"   ═══════════════════════════════")
    logger.info(f"   🎯 RESUME INTELLIGENCE SCORE: {resume_score}")
    logger.info(f"   ═══════════════════════════════")

    return {
        'skill_score': round(skill_score, 1),
        'identity_score': round(identity_score, 1),
        'github_score': round(github_score, 1),
        'fraud_penalty': round(fraud_penalty, 1),
        'resume_score': resume_score,
    }


def fraud_level(probability: float) -> str:
    """Return human-readable fraud level."""
    if probability < 0.2:
        return 'Low'
    elif probability < 0.5:
        return 'Medium'
    else:
        return 'High'
