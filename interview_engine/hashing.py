"""
Interview Hashing — Tamper Detection
─────────────────────────────────────
SHA-256 hash generation and verification for interview records.
Prevents post-hoc tampering with video, transcript, or scores.
"""

import hashlib
import logging
import os

logger = logging.getLogger('interview_engine.hashing')


def generate_interview_hash(video_path: str, transcript: str,
                             integrity_index: float,
                             final_answer_score: float) -> str:
    """
    Generate SHA-256 hash of interview data for tamper detection.

    Args:
        video_path: path to the video file
        transcript: interview transcript text
        integrity_index: computed integrity score
        final_answer_score: computed final answer score

    Returns:
        str: hex-encoded SHA-256 hash
    """
    hasher = hashlib.sha256()

    # Hash video file contents
    if video_path and os.path.exists(video_path):
        with open(video_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
    else:
        hasher.update(b'NO_VIDEO')
        logger.warning("  Video file not found for hashing")

    # Hash transcript
    transcript_bytes = (transcript or '').encode('utf-8')
    hasher.update(transcript_bytes)

    # Hash scores (as string representations for determinism)
    hasher.update(str(integrity_index).encode('utf-8'))
    hasher.update(str(final_answer_score).encode('utf-8'))

    hex_hash = hasher.hexdigest()
    logger.info(f"  Interview hash: {hex_hash[:16]}...")

    return hex_hash


def verify_hash(video_path: str, transcript: str,
                integrity_index: float, final_answer_score: float,
                stored_hash: str) -> bool:
    """
    Verify stored hash matches recomputed hash.

    Returns:
        bool: True if hash matches (no tampering), False otherwise
    """
    recomputed = generate_interview_hash(
        video_path, transcript, integrity_index, final_answer_score
    )
    match = recomputed == stored_hash

    if not match:
        logger.warning("  ⚠ Hash mismatch — possible tampering detected!")
    else:
        logger.info("  ✓ Hash verified — record integrity confirmed")

    return match
