"""
Resume Intelligence Pipeline — Orchestrator

Pipeline flow:
  STEP 1 → Layout-Aware PDF Parsing (layout_parser.py)
  STEP 2 → Section Detection Engine (section_parser.py)
  STEP 3 → Hybrid Extraction Engine (hybrid_extractor.py)
  STEP 4 → Structured Data Normalization
  STEP 5 → Parsing Confidence Score

This module ties everything together and produces the final
Structured Intelligence Object.
"""

import logging
from .section_parser import extract_layout_blocks, segment_into_sections
from .hybrid_extractor import (
    extract_name, extract_skills, extract_education, extract_experience,
    extract_companies, extract_links,
    extract_emails, extract_phones, extract_location,
    extract_certifications, extract_projects, extract_languages,
    extract_achievements, extract_summary, extract_interests,
    calculate_parsing_confidence,
)
from .nlp_pipeline import get_nlp

logger = logging.getLogger('resume_engine.extractor')


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API — extract_text + parse_resume
# ═══════════════════════════════════════════════════════════════════════════

def extract_text(pdf_path: str) -> tuple[str, dict]:
    """
    STEP 1 — Layout-aware PDF text extraction.
    Returns (ordered_text, layout_data) where layout_data contains
    header_blocks, body_blocks, ordered_text.
    """
    return extract_layout_blocks(pdf_path)


def parse_resume(text: str, github_username: str | None = None,
                 layout_data: dict = None) -> dict:
    """
    Full resume intelligence pipeline.

    STEP 2 → Section segmentation
    STEP 3 → Hybrid extraction (rules + spaCy, per section)
    STEP 4 → Build Structured Intelligence Object
    STEP 5 → Compute parsing confidence

    Returns the structured intelligence object.
    """
    logger.info("═" * 60)
    logger.info("🏗  RESUME INTELLIGENCE PIPELINE v5 — HEADER-AWARE")
    logger.info("═" * 60)

    # ── Derive header text from layout data ──────────────────────────────
    header_text = None
    if layout_data and layout_data.get('header_blocks'):
        header_text = '\n'.join(layout_data['header_blocks'])
        logger.info(f"   📌 Header region: {len(layout_data['header_blocks'])} blocks")

    # ══ STEP 2 — Section Segmentation ════════════════════════════════════
    logger.info("")
    logger.info("📑 STEP 2 — Section Segmentation")
    sections = segment_into_sections(text, header_text=header_text)

    # ══ STEP 3 — Hybrid Extraction (spaCy + Rules) ══════════════════════
    logger.info("")
    logger.info("🏷  Loading spaCy NLP pipeline...")
    nlp = get_nlp()
    doc = nlp(text)

    # Log entity distribution
    entity_counts = {}
    for ent in doc.ents:
        entity_counts[ent.label_] = entity_counts.get(ent.label_, 0) + 1
    for label, count in sorted(entity_counts.items()):
        logger.info(f"   {label}: {count}")

    # ── 3A: Name (header region) ─────────────────────────────────────────
    logger.info("")
    logger.info("👤 3A — Name Extraction (header region)")
    name = extract_name(sections, doc, header_text=header_text)

    # ── 3F: Links (full text) ────────────────────────────────────────────
    logger.info("")
    logger.info("🔗 3F — Link Extraction")
    links = extract_links(text)
    if github_username and github_username.strip():
        links['github_username'] = github_username.strip()
        if not links['github_url']:
            links['github_url'] = f"https://github.com/{github_username.strip()}"
    if links['github_url']: logger.info(f"   GitHub: {links['github_url']}")
    if links['linkedin_url']: logger.info(f"   LinkedIn: {links['linkedin_url']}")
    if links['portfolio_url']: logger.info(f"   Portfolio: {links['portfolio_url']}")

    # ── Identity (email, phone, location) ────────────────────────────────
    logger.info("")
    logger.info("📧 Identity Extraction")
    emails = extract_emails(text)
    phones = extract_phones(text)
    location = extract_location(text, header_text=header_text)
    if emails: logger.info(f"   Emails: {emails}")
    if phones: logger.info(f"   Phones: {phones}")
    if location: logger.info(f"   Location: {location}")

    # ── 3B: Skills (SKILLS section + normalization) ──────────────────────
    logger.info("")
    logger.info("🛠  3B — Skill Extraction (section-based + normalization)")
    raw_skills, normalized_skills = extract_skills(sections, doc)
    logger.info(f"   Raw: {len(raw_skills)} | Normalized: {len(normalized_skills)}")
    logger.info(f"   Skills: {normalized_skills[:15]}{'...' if len(normalized_skills) > 15 else ''}")

    # ── 3C: Education (EDUCATION section) ────────────────────────────────
    logger.info("")
    logger.info("🎓 3C — Education Extraction")
    education = extract_education(sections, doc)
    logger.info(f"   Degree: {education['degree']}")
    logger.info(f"   University: {education['university']}")
    logger.info(f"   GPA: {education['gpa']} | Year: {education['graduation_year']}")

    # ── 3D: Experience (date-range calculator) ───────────────────────────
    logger.info("")
    logger.info("💼 3D — Experience Extraction (date-range calculator)")
    experience = extract_experience(sections)
    logger.info(f"   Years: {experience['years_experience']}")
    logger.info(f"   Job titles: {experience['job_titles']}")

    # ── 3E: Companies (ORG cross-check) ──────────────────────────────────
    logger.info("")
    logger.info("🏢 3E — Company Detection (ORG cross-check)")
    companies, institutions = extract_companies(sections, doc)
    logger.info(f"   Companies: {companies[:6]}")
    logger.info(f"   Institutions: {institutions[:4]}")

    # ── Other sections ───────────────────────────────────────────────────
    logger.info("")
    logger.info("📜 Section-specific extraction...")
    certifications = extract_certifications(sections)
    projects = extract_projects(sections)
    languages = extract_languages(sections)
    achievements = extract_achievements(sections)
    summary = extract_summary(sections)
    interests = extract_interests(sections)
    if certifications: logger.info(f"   Certs: {certifications}")
    if projects: logger.info(f"   Projects: {projects}")
    if languages: logger.info(f"   Languages: {languages}")
    if summary: logger.info(f"   Summary: {summary[:80]}...")

    # ══ STEP 4 — Structured Intelligence Object ═════════════════════════
    detected_sections = [s for s in sections if not s.startswith('_')]

    result = {
        # Identity
        'full_name':          name,
        'email':              emails[0] if emails else None,
        'all_emails':         emails,
        'phone':              phones[0] if phones else None,
        'all_phones':         phones,
        'location':           location,
        # Links
        'github_url':         links['github_url'],
        'github_username':    links['github_username'],
        'linkedin_url':       links['linkedin_url'],
        'portfolio_url':      links['portfolio_url'],
        'other_links':        links['other_links'],
        # Skills
        'skills':             normalized_skills,
        'raw_skills':         raw_skills,
        'normalized_skills':  normalized_skills,
        'skill_count':        len(normalized_skills),
        # Education
        'degree':             education['degree'],
        'all_degrees':        education['all_degrees'],
        'university':         education['university'],
        'graduation_year':    education['graduation_year'],
        'gpa':                education['gpa'],
        # Experience
        'years_experience':   experience['years_experience'],
        'companies':          companies,
        'institutions':       institutions,
        'job_titles':         experience['job_titles'],
        # Extra
        'certifications':     certifications,
        'projects':           projects,
        'languages':          languages,
        'achievements':       achievements,
        'summary':            summary,
        'interests':          interests,
        # Meta
        'sections_detected':  detected_sections,
    }

    # ══ STEP 5 — Parsing Confidence ═════════════════════════════════════
    confidence = calculate_parsing_confidence(sections, result)
    result['parsing_confidence'] = confidence

    populated = sum(1 for v in result.values() if v)
    logger.info("")
    logger.info(f"   ✅ Pipeline complete: {populated}/{len(result)} fields populated")
    logger.info(f"   🎯 Parsing confidence: {confidence}%")
    logger.info(f"   📑 Sections: {detected_sections}")
    logger.info("═" * 60)

    return result
