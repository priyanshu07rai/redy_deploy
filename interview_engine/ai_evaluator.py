"""
AI Evaluator — Layer 2 Intelligence (Controlled AI)
────────────────────────────────────────────────────
Calls Groq API with strict guardrails to evaluate transcript quality.
Only evaluates: clarity, depth, technical accuracy, communication.
Does NOT invent facts or infer external knowledge.
Graceful fallback to neutral score (50) on failure.
"""

import json
import logging
import requests

logger = logging.getLogger('interview_engine.ai_evaluator')

# ─── Evaluation Prompt ───────────────────────────────────────────────────────
EVALUATION_PROMPT = """You are an interview transcript evaluator. Evaluate the following interview transcript ONLY on these criteria:

1. **Clarity** (0-100): How clear and articulate are the responses?
2. **Depth** (0-100): How deep and thorough are the answers?
3. **Technical Accuracy** (0-100): How accurate is the technical content discussed?
4. **Communication** (0-100): How well does the candidate communicate ideas?
5. **Confidence** (0-100): How confident and composed does the candidate appear in their delivery?

RULES:
- Score ONLY what is present in the transcript
- Do NOT invent facts or assume knowledge not demonstrated
- Do NOT infer external capabilities
- Base scores strictly on the text provided
- Return ONLY valid JSON, no additional text

Return this exact JSON structure:
{
  "clarity": <int>,
  "depth": <int>,
  "technical_accuracy": <int>,
  "communication": <int>,
  "confidence": <int>,
  "overall_score": <int>
}

The overall_score should be the weighted average: 25% clarity + 20% depth + 20% technical_accuracy + 20% communication + 15% confidence.

TRANSCRIPT:
"""

NEUTRAL_SCORE = {
    'clarity': 50,
    'depth': 50,
    'technical_accuracy': 50,
    'communication': 50,
    'confidence': 50,
    'overall_score': 50,
}


def evaluate_transcript(transcript: str, api_url: str, api_key: str,
                         model: str = 'llama-3.3-70b-versatile') -> dict:
    """
    Evaluate interview transcript using AI with strict guardrails.

    Args:
        transcript: the interview transcript text
        api_url: Groq API endpoint URL
        api_key: API key for authentication
        model: model name to use

    Returns:
        dict: {clarity, depth, technical_accuracy, communication, overall_score}
              Falls back to neutral scores (50) on any failure.
    """
    if not transcript or not transcript.strip():
        logger.warning("  Empty transcript → returning neutral scores")
        return NEUTRAL_SCORE.copy()

    if not api_key:
        logger.warning("  No API key configured → returning neutral scores")
        return NEUTRAL_SCORE.copy()

    try:
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': model,
            'messages': [
                {
                    'role': 'system',
                    'content': 'You are a strict interview evaluator. Return ONLY valid JSON.'
                },
                {
                    'role': 'user',
                    'content': EVALUATION_PROMPT + transcript[:3000]  # Limit transcript length
                }
            ],
            'temperature': 0.1,  # Low temperature for consistency
            'max_tokens': 200,
        }

        logger.info(f"  Calling AI evaluator ({model})...")
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        content = result['choices'][0]['message']['content'].strip()

        # Parse JSON from response (handle markdown code blocks)
        if content.startswith('```'):
            content = content.split('\n', 1)[1]  # Remove opening ```json
            content = content.rsplit('```', 1)[0]  # Remove closing ```

        scores = json.loads(content)

        # Validate and clamp all scores
        validated = {}
        for key in ['clarity', 'depth', 'technical_accuracy', 'communication', 'confidence', 'overall_score']:
            val = scores.get(key, 50)
            if not isinstance(val, (int, float)):
                val = 50
            validated[key] = max(0, min(100, int(val)))

        logger.info(f"  AI scores: {validated}")
        return validated

    except requests.exceptions.Timeout:
        logger.error("  AI evaluator timed out → returning neutral scores")
        return NEUTRAL_SCORE.copy()

    except requests.exceptions.RequestException as e:
        logger.error(f"  AI evaluator API error: {e} → returning neutral scores")
        return NEUTRAL_SCORE.copy()

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"  AI evaluator parse error: {e} → returning neutral scores")
        return NEUTRAL_SCORE.copy()

    except Exception as e:
        logger.error(f"  AI evaluator unexpected error: {e} → returning neutral scores")
        return NEUTRAL_SCORE.copy()
