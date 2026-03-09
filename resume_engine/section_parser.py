"""
Section Parser — Layout-Aware PDF Parsing + Section Segmentation

STEP 1: Delegates to layout_parser for block extraction with header/body split
STEP 2: Section header detection and text segmentation

Produces a section map: {section_name: section_text}
"""

import re
import logging
from .layout_parser import extract_layout_blocks as _extract_blocks

logger = logging.getLogger('resume_engine.section_parser')


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — LAYOUT-AWARE BLOCK EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def extract_layout_blocks(pdf_path: str) -> tuple[str, dict]:
    """
    Extract text using PyMuPDF layout blocks with header/body separation.

    Returns:
        (ordered_text, layout_data)
    where layout_data = {
        'header_blocks': [...],
        'body_blocks': [...],
        'ordered_text': '...',
    }
    """
    layout = _extract_blocks(pdf_path)
    return layout['ordered_text'], layout


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — SECTION SEGMENTATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

# Section header patterns — supports many common resume header variations
SECTION_PATTERNS = {
    'CONTACT':        r'(?:contact\s*(?:info(?:rmation)?)?|personal\s*(?:info(?:rmation)?|details?))',
    'SUMMARY':        r'(?:summary|objective|profile|about\s*me|career\s*(?:objective|summary)|professional\s*(?:summary|profile)|overview)',
    'SKILLS':         r'(?:skills?|technical\s*skills?|core\s*(?:competencies|skills)|technologies|tech\s*stack|proficiencies|areas?\s*of\s*expertise)',
    'EXPERIENCE':     r'(?:(?:work\s*)?experience|employment(?:\s*history)?|professional\s*experience|work\s*history|internships?)',
    'EDUCATION':      r'(?:education|academic\s*(?:background|qualifications?)|qualifications?|academics)',
    'PROJECTS':       r'(?:projects?|personal\s*projects?|academic\s*projects?|key\s*projects?|notable\s*projects?)',
    'CERTIFICATIONS': r'(?:certifications?|certificates?|courses?\s*(?:&|and)?\s*certifications?|professional\s*development|training)',
    'ACHIEVEMENTS':   r'(?:achievements?|awards?\s*(?:&|and)?\s*achievements?|honors?|accomplishments?|recognitions?)',
    'INTERESTS':      r'(?:interests?|hobbies|hobbies?\s*(?:&|and)?\s*interests?|extracurricular(?:\s*activities)?|activities)',
    'LANGUAGES':      r'(?:languages?|linguistic\s*skills?|spoken\s*languages?)',
    'PUBLICATIONS':   r'(?:publications?|papers?|research\s*(?:papers?|publications?))',
    'REFERENCES':     r'(?:references?)',
    'VOLUNTEER':      r'(?:volunteer(?:ing)?|community\s*service|social\s*work)',
}

# Header format patterns: ALL CAPS, Title Case, with optional separators
HEADER_FORMAT = re.compile(
    r'^[\s•\-—─═]*'
    r'(?:[A-Z][A-Z\s&/]+[A-Z]'   # ALL CAPS: "WORK EXPERIENCE"
    r'|[A-Z][a-z]+(?:\s+[A-Za-z&/]+)*)'  # Title Case: "Work Experience"
    r'[\s:—\-─═]*$'
)


def segment_into_sections(text: str, header_text: str = None) -> dict:
    """
    Detect section headers and split resume into a section map.

    Returns:
        {
            '_full':    full text,
            '_top':     first 10 lines (for name/contact),
            '_header':  header region text (from layout parser),
            '_lines':   all lines,
            'SKILLS':   '...',
            'EDUCATION': '...',
            'EXPERIENCE': '...',
            ...
        }
    """
    lines = text.split('\n')
    sections = {
        '_full': text,
        '_top': '\n'.join(lines[:10]),
        '_header': header_text or '\n'.join(lines[:10]),
        '_lines': lines,
    }

    # ── Detect section header positions ──────────────────────────────────
    header_positions = []

    for i, line in enumerate(lines):
        clean = line.strip()
        if not clean or len(clean) > 60 or len(clean) < 3:
            continue

        # Check if line looks like a header (short, formatted)
        # Must match one of our section patterns
        for section_name, pattern in SECTION_PATTERNS.items():
            if re.match(rf'^[\s•\-—]*{pattern}\s*[:—\-]*\s*$', clean, re.IGNORECASE):
                header_positions.append((i, section_name))
                break

    # ── Extract text between headers ─────────────────────────────────────
    for idx, (start_line, section_name) in enumerate(header_positions):
        end_line = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(lines)
        section_text = '\n'.join(lines[start_line + 1: end_line]).strip()
        if section_text:
            sections[section_name] = section_text

    # ── Log results ──────────────────────────────────────────────────────
    detected = [s for s in sections if not s.startswith('_')]
    logger.info(f"   📑 Sections detected ({len(detected)}): {detected}")
    for name in detected:
        text_preview = sections[name][:60].replace('\n', ' ')
        logger.info(f"      {name}: {len(sections[name])} chars — \"{text_preview}...\"")

    return sections
