"""
Transcript Processor
────────────────────
Parses raw interview transcript text and extracts metrics
for deterministic scoring.
"""

import re
import logging

logger = logging.getLogger('interview_engine.transcript')

# ─── Filler Words ────────────────────────────────────────────────────────────
FILLER_WORDS = {
    'um', 'uh', 'uhh', 'umm', 'like', 'you know', 'basically',
    'actually', 'literally', 'sort of', 'kind of', 'i mean',
    'right', 'okay so', 'well',
}

# ─── Technical Keywords (for relevance scoring) ─────────────────────────────
DEFAULT_KEYWORDS = [
    'python', 'java', 'javascript', 'typescript', 'react', 'angular', 'vue',
    'node', 'express', 'django', 'flask', 'fastapi', 'spring',
    'docker', 'kubernetes', 'aws', 'azure', 'gcp',
    'sql', 'nosql', 'mongodb', 'postgresql', 'redis',
    'git', 'ci/cd', 'agile', 'scrum',
    'machine learning', 'deep learning', 'data science',
    'api', 'rest', 'graphql', 'microservices',
    'testing', 'debugging', 'optimization', 'scalability',
    'algorithm', 'data structure', 'design pattern',
    'leadership', 'teamwork', 'communication', 'problem solving',
    'project management', 'deadline', 'stakeholder',
    'experience', 'years', 'developed', 'implemented', 'designed',
    'built', 'managed', 'led', 'improved', 'reduced', 'increased',
]


def process_transcript(text: str, expected_keywords: list = None) -> dict:
    """
    Process raw transcript text and extract scoring metrics.

    Args:
        text: raw transcript string
        expected_keywords: optional list of keywords to match against

    Returns:
        dict with metrics:
            - word_count: int
            - sentence_count: int
            - avg_sentence_length: float
            - filler_count: int
            - filler_ratio: float (0–1)
            - matched_keywords: list[str]
            - keyword_match_ratio: float (0–1)
            - unique_words: int
            - vocabulary_richness: float (unique/total)
    """
    if not text or not text.strip():
        return _empty_metrics()

    keywords = expected_keywords or DEFAULT_KEYWORDS

    # Normalize
    clean = text.strip()
    lower = clean.lower()

    # Word count
    words = re.findall(r'\b\w+\b', lower)
    word_count = len(words)

    if word_count == 0:
        return _empty_metrics()

    # Sentence count
    sentences = re.split(r'[.!?]+', clean)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = max(len(sentences), 1)
    avg_sentence_length = word_count / sentence_count

    # Filler word detection
    filler_count = 0
    for filler in FILLER_WORDS:
        # Count occurrences of multi-word fillers
        if ' ' in filler:
            filler_count += lower.count(filler)
        else:
            filler_count += words.count(filler)

    filler_ratio = filler_count / word_count if word_count > 0 else 0

    # Keyword matching
    matched = []
    for kw in keywords:
        if kw.lower() in lower:
            matched.append(kw)
    keyword_match_ratio = len(matched) / len(keywords) if keywords else 0

    # Vocabulary richness
    unique_words = len(set(words))
    vocabulary_richness = unique_words / word_count if word_count > 0 else 0

    metrics = {
        'word_count': word_count,
        'sentence_count': sentence_count,
        'avg_sentence_length': round(avg_sentence_length, 2),
        'filler_count': filler_count,
        'filler_ratio': round(filler_ratio, 4),
        'matched_keywords': matched,
        'keyword_match_ratio': round(keyword_match_ratio, 4),
        'unique_words': unique_words,
        'vocabulary_richness': round(vocabulary_richness, 4),
    }

    logger.info(f"  Transcript metrics: {word_count} words, "
                f"{filler_count} fillers, {len(matched)} keywords matched")

    return metrics


def _empty_metrics() -> dict:
    """Return zero-value metrics for empty transcripts."""
    return {
        'word_count': 0,
        'sentence_count': 0,
        'avg_sentence_length': 0,
        'filler_count': 0,
        'filler_ratio': 0,
        'matched_keywords': [],
        'keyword_match_ratio': 0,
        'unique_words': 0,
        'vocabulary_richness': 0,
    }
