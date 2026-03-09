"""
Integrity Monitor — Layer 1 (Behavioral Trust)
───────────────────────────────────────────────
Computes a fully deterministic integrity index from client-side anomaly flags.
AI NEVER touches this layer.
"""

import logging

logger = logging.getLogger('interview_engine.integrity')

# ─── Penalty Weights ────────────────────────────────────────────────────────
PENALTIES = {
    'tab_switches':     5,      # per occurrence
    'window_blur':      5,      # per occurrence
    'no_face_seconds':  0.4,    # per second
    'multiple_faces':   15,     # per detection event
    'copy_attempts':    10,     # per attempt
    'fullscreen_exits': 8,      # per exit
}


def compute_integrity_index(anomaly_flags: dict) -> float:
    """
    Compute integrity index from anomaly flags.

    Args:
        anomaly_flags: dict with keys matching PENALTIES + optional extras

    Returns:
        float: integrity index clamped to [0, 100]
    """
    score = 100.0

    for flag, weight in PENALTIES.items():
        value = anomaly_flags.get(flag, 0)
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (ValueError, TypeError):
                value = 0
        penalty = value * weight
        if penalty > 0:
            logger.info(f"  Penalty: {flag} = {value} × {weight} = -{penalty}")
        score -= penalty

    # Clamp to [0, 100]
    score = max(0.0, min(100.0, score))

    logger.info(f"  Integrity Index = {score:.1f}")
    return round(score, 2)


def get_anomaly_breakdown(anomaly_flags: dict) -> list:
    """
    Return a human-readable breakdown of anomalies for display.

    Returns:
        list of dicts: [{name, count, penalty, description}, ...]
    """
    DESCRIPTIONS = {
        'tab_switches':     'Tab or window switches detected',
        'window_blur':      'Browser window lost focus',
        'no_face_seconds':  'Seconds with no face visible',
        'multiple_faces':   'Multiple faces detected',
        'copy_attempts':    'Copy/paste attempts blocked',
        'fullscreen_exits': 'Exited fullscreen mode',
    }

    breakdown = []
    for flag, weight in PENALTIES.items():
        value = anomaly_flags.get(flag, 0)
        if value > 0:
            breakdown.append({
                'name': flag,
                'count': value,
                'penalty': round(value * weight, 2),
                'description': DESCRIPTIONS.get(flag, flag),
            })



    return breakdown
