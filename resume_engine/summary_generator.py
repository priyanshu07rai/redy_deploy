"""
AI Summary Generator — Controlled Layer

Accepts a structured intelligence object and generates a 3–4 line
professional summary using a configurable AI API.

Rules:
  - Must only use provided structured data
  - Must not hallucinate or add unverified claims
  - Prompt is strict: "use only the supplied fields"
  - Graceful fallback: returns None if API unavailable
"""

import logging
import json

logger = logging.getLogger('resume_engine.summary_generator')


def generate_summary(structured_data: dict) -> str | None:
    """
    Generate a 3–4 sentence professional summary from structured data.

    Uses the configured AI API (Groq/OpenAI compatible endpoint).
    Returns None if AI is disabled, no API key, or API fails.
    """
    try:
        from config import Config
    except ImportError:
        logger.warning("   ⚠ Config not available — skipping AI summary")
        return None

    if not getattr(Config, 'AI_SUMMARY_ENABLED', False):
        logger.info("   ℹ AI summary disabled in config")
        return None

    api_key = getattr(Config, 'AI_SUMMARY_API_KEY', '')
    if not api_key:
        logger.info("   ℹ No AI API key configured — skipping summary generation")
        return None

    api_url = getattr(Config, 'AI_SUMMARY_API_URL', '')
    model = getattr(Config, 'AI_SUMMARY_MODEL', 'llama-3.3-70b-versatile')

    # ── Build the data context (sanitized) ───────────────────────────────
    context = _build_context(structured_data)

    # ── Strict prompt ────────────────────────────────────────────────────
    system_prompt = (
        "You are a professional resume summary writer. "
        "You MUST only use the data provided below to write the summary. "
        "Do NOT add any claims, skills, achievements, or experiences not present in the data. "
        "Do NOT hallucinate or infer information. "
        "Write exactly 3-4 sentences in a professional tone. "
        "Focus on: name, skills, experience level, education, and key projects if available."
    )

    user_prompt = (
        f"Write a professional summary for the following candidate data. "
        f"Use ONLY the information provided:\n\n{context}\n\n"
        f"Write 3-4 sentences. Do not add anything not in the data above."
    )

    # ── API call ─────────────────────────────────────────────────────────
    try:
        import requests
        logger.info(f"   🤖 Generating AI summary via {model}...")

        response = requests.post(
            api_url,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'temperature': 0.3,
                'max_tokens': 200,
            },
            timeout=15,
        )

        if response.status_code == 200:
            data = response.json()
            summary = data['choices'][0]['message']['content'].strip()
            logger.info(f"   ✅ AI summary generated: {summary[:80]}...")
            return summary
        else:
            logger.warning(f"   ⚠ AI API returned {response.status_code}: {response.text[:200]}")
            return None

    except ImportError:
        logger.warning("   ⚠ 'requests' library not installed — skipping AI summary")
        return None
    except Exception as e:
        logger.warning(f"   ⚠ AI summary generation failed: {e}")
        return None


def _build_context(data: dict) -> str:
    """Build a sanitized context string from structured data."""
    parts = []

    if data.get('full_name'):
        parts.append(f"Name: {data['full_name']}")
    if data.get('location'):
        parts.append(f"Location: {data['location']}")
    if data.get('degree'):
        parts.append(f"Degree: {data['degree']}")
    if data.get('university'):
        parts.append(f"University: {data['university']}")
    if data.get('graduation_year'):
        parts.append(f"Graduation Year: {data['graduation_year']}")

    exp = data.get('years_experience', 0)
    if exp and exp > 0:
        parts.append(f"Years of Experience: {exp}")

    titles = data.get('job_titles', [])
    if titles:
        parts.append(f"Job Titles: {', '.join(titles[:5])}")

    companies = data.get('companies', [])
    if companies:
        parts.append(f"Companies: {', '.join(companies[:5])}")

    skills = data.get('normalized_skills', data.get('skills', []))
    if skills:
        parts.append(f"Skills: {', '.join(skills[:20])}")

    projects = data.get('projects', [])
    if projects:
        parts.append(f"Projects: {', '.join(projects[:5])}")

    certs = data.get('certifications', [])
    if certs:
        parts.append(f"Certifications: {', '.join(certs[:5])}")

    return '\n'.join(parts)
