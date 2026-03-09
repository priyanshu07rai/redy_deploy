"""
Hybrid Extractor — Rules + spaCy NER, Section-Aware

All extraction functions receive the section map and run ONLY in their
relevant section. Cross-checks ORGs between education and experience
to separate companies from institutions.

Includes skill normalization (python3 → Python, js → JavaScript).
"""

import re
import datetime
import logging
from .nlp_pipeline import get_nlp, SKILL_PATTERNS

logger = logging.getLogger('resume_engine.hybrid_extractor')

CURRENT_YEAR = datetime.datetime.now().year


# ═══════════════════════════════════════════════════════════════════════════
# BLACKLISTS & NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════

NAME_BLACKLIST = {
    'quick learner', 'hard worker', 'team player', 'self motivated',
    'self-motivated', 'detail oriented', 'detail-oriented', 'fast learner',
    'problem solver', 'strong communicator', 'highly motivated',
    'objective', 'summary', 'profile', 'about me', 'career objective',
    'curriculum vitae', 'resume', 'cover letter',
    'work experience', 'education', 'skills', 'projects',
    'certifications', 'achievements', 'references', 'contact',
    'personal information', 'personal details',
}

NAME_NOISE_WORDS = {
    'ai', 'ml', 'api', 'sdk', 'app', 'bot', 'hub', 'lab', 'io',
    'pro', 'dev', 'tech', 'net', 'web', 'cloud', 'data', 'code',
    'smart', 'auto', 'vapi', 'lang', 'bridge', 'vosk', 'asr',
    'deep', 'open', 'chat', 'fast', 'gen', 'next', 'base',
    'llm', 'gpt', 'nlp', 'saas', 'paas', 'iaas',
}

ORG_NOISE = {
    'designed', 'analyzed', 'developed', 'implemented', 'created',
    'built', 'managed', 'led', 'improved', 'optimized', 'resolved',
    'deployed', 'integrated', 'maintained', 'tested', 'reduced',
    'increased', 'enhanced', 'launched', 'published', 'contributed',
    'utilized', 'conducted', 'performed', 'achieved', 'collaborated',
    'responsible', 'worked', 'participated', 'coordinated',
}

INSTITUTE_KEYWORDS = {
    'university', 'college', 'institute', 'school', 'academy',
    'iit', 'nit', 'iiit', 'bits', 'vit', 'srm', 'amity',
    'polytechnic', 'vidyalaya', 'vidyapeeth',
}

# ── Skill Normalization Map ──────────────────────────────────────────────
SKILL_NORMALIZATION = {
    'python3': 'Python', 'python2': 'Python', 'python programming': 'Python',
    'js': 'JavaScript', 'javascript': 'JavaScript', 'ecmascript': 'JavaScript', 'es6': 'JavaScript',
    'ts': 'TypeScript', 'typescript': 'TypeScript',
    'c++': 'C++', 'cpp': 'C++', 'c plus plus': 'C++',
    'c#': 'C#', 'csharp': 'C#', 'c sharp': 'C#',
    'c programming': 'C',
    'golang': 'Go',
    'r programming': 'R',
    'react.js': 'React', 'reactjs': 'React',
    'angular.js': 'Angular', 'angularjs': 'Angular',
    'vue.js': 'Vue', 'vuejs': 'Vue',
    'next.js': 'Next.js', 'nextjs': 'Next.js',
    'nuxt.js': 'Nuxt.js', 'nuxtjs': 'Nuxt.js',
    'node.js': 'Node.js', 'nodejs': 'Node.js', 'node': 'Node.js',
    'express.js': 'Express', 'expressjs': 'Express',
    'spring boot': 'Spring Boot', 'springboot': 'Spring Boot',
    'ruby on rails': 'Rails',
    'mongo': 'MongoDB', 'mongodb': 'MongoDB',
    'postgres': 'PostgreSQL', 'postgresql': 'PostgreSQL',
    'k8s': 'Kubernetes',
    'amazon web services': 'AWS',
    'microsoft azure': 'Azure',
    'google cloud platform': 'GCP', 'google cloud': 'GCP',
    'ci/cd': 'CI/CD', 'cicd': 'CI/CD',
    'ml': 'Machine Learning', 'machine learning': 'Machine Learning',
    'dl': 'Deep Learning', 'deep learning': 'Deep Learning',
    'ai': 'AI', 'artificial intelligence': 'AI',
    'nlp': 'NLP', 'natural language processing': 'NLP',
    'cv': 'Computer Vision', 'computer vision': 'Computer Vision',
    'sklearn': 'Scikit-learn', 'scikit-learn': 'Scikit-learn',
    'html5': 'HTML', 'html': 'HTML',
    'css3': 'CSS', 'css': 'CSS',
    'sass': 'SASS', 'scss': 'SASS',
    'tailwindcss': 'Tailwind', 'tailwind css': 'Tailwind',
    'material ui': 'Material UI', 'mui': 'Material UI',
    'rest api': 'REST API', 'restful': 'REST API', 'rest': 'REST API',
    'ui/ux': 'UI/UX', 'ui design': 'UI/UX', 'ux design': 'UI/UX',
    'oop': 'OOP', 'object oriented programming': 'OOP',
    'dsa': 'Data Structures', 'data structures': 'Data Structures',
    'tdd': 'TDD', 'bdd': 'BDD',
}


# ═══════════════════════════════════════════════════════════════════════════
# 3A — NAME EXTRACTION (top of resume, hybrid heuristic + NER)
# ═══════════════════════════════════════════════════════════════════════════

def _is_valid_person_name(text: str) -> bool:
    """Check if text looks like a real person name."""
    if not text or len(text) < 3:
        return False
    if text.lower() in NAME_BLACKLIST:
        return False
    words = text.split()
    if not (1 <= len(words) <= 4):
        return False
    if not all(re.match(r'^[A-Za-z.\'\-]+$', w) for w in words):
        return False
    if any(w.lower() in NAME_NOISE_WORDS for w in words):
        return False
    if any(bw in text.lower() for bw in ['learner', 'worker', 'player', 'solver', 'motivated', 'oriented']):
        return False
    if len(words) == 1 and len(words[0]) < 4:
        return False
    return True


def extract_name(sections: dict, doc, header_text: str = None) -> str | None:
    """
    Name extraction — header region only (top 20% of page).
    1. Primary: header_text from layout parser
    2. Fallback: _top lines from section map
    3. Remove lines with email/phone/URL/headers
    4. Pick the largest capitalized phrase
    5. spaCy PERSON as validation only
    """
    # Use header region if available, else fall back to _top
    source_text = header_text or sections.get('_header', '') or sections.get('_top', '')
    lines = source_text.strip().split('\n')
    candidates = []

    for line in lines[:7]:
        line = line.strip()
        if not line or len(line) < 2:
            continue
        # Skip lines with identifiers
        if '@' in line or 'http' in line.lower() or 'github' in line.lower():
            continue
        if re.search(r'\d{4,}', line):  # phone-like
            continue
        if re.match(r'^(resume|curriculum|cv|contact|phone|email|address|objective|summary|profile)', line, re.I):
            continue
        if _is_valid_person_name(line):
            candidates.append(line)

    if candidates:
        best = max(candidates, key=len)
        logger.info(f"   👤 Name (header-region heuristic): {best.title()}")
        return best.title()

    # Fallback: spaCy PERSON in first 300 chars of header
    first_chunk = source_text[:300]
    for ent in doc.ents:
        if ent.label_ == "PERSON" and ent.text in first_chunk:
            if _is_valid_person_name(ent.text):
                logger.info(f"   👤 Name (spaCy PERSON fallback): {ent.text.title()}")
                return ent.text.title()

    return None


# ═══════════════════════════════════════════════════════════════════════════
# 3B — SKILLS EXTRACTION (SKILLS section + normalization)
# ═══════════════════════════════════════════════════════════════════════════

def extract_skills(sections: dict, doc) -> tuple[list[str], list[str]]:
    """
    Extract skills from SKILLS section.
    Returns (raw_skills, normalized_skills).
    Normalization: python3 → Python, js → JavaScript, etc.
    """
    section_text = sections.get('SKILLS', sections.get('_full', ''))

    # ── spaCy SKILL entities ─────────────────────────────────────────────
    skills_ner = set()
    for ent in doc.ents:
        if ent.label_ == "SKILL":
            skills_ner.add(ent.text)

    # ── Word-boundary regex in SKILLS section ────────────────────────────
    skills_regex = set()
    for skill in SKILL_PATTERNS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, section_text, re.IGNORECASE):
            skills_regex.add(skill)

    raw_skills = skills_ner | skills_regex

    # ── Normalize ────────────────────────────────────────────────────────
    normalized = set()
    for s in raw_skills:
        key = s.lower().strip()
        norm = SKILL_NORMALIZATION.get(key, s.strip())
        normalized.add(norm)

    # Deduplicate case-insensitive
    seen = {}
    for s in normalized:
        k = s.lower()
        if k not in seen or (s[0].isupper() and not seen[k][0].isupper()):
            seen[k] = s
    final = sorted(seen.values(), key=str.lower)

    return list(raw_skills), final


# ═══════════════════════════════════════════════════════════════════════════
# 3C — EDUCATION EXTRACTION (EDUCATION section)
# ═══════════════════════════════════════════════════════════════════════════

def extract_education(sections: dict, doc) -> dict:
    """Extract degree, university, GPA, graduation year from EDUCATION section."""
    section_text = sections.get('EDUCATION', sections.get('_full', ''))

    # ── Degrees from spaCy ───────────────────────────────────────────────
    degrees = list(set(e.text for e in doc.ents if e.label_ == "DEGREE"))

    # ── University (improved patterns) ───────────────────────────────────
    university = None
    uni_patterns = [
        r'((?:Indian\s+)?(?:Institute|University|College)\s+of\s+[A-Za-z\s]+(?:,\s*[A-Za-z\s]+)?)',
        r'([A-Z][A-Za-z\s]+(?:University|Institute|College|Academy|School of (?:Engineering|Technology|Science)))',
        r'(I\.?I\.?T\.?\s*[A-Za-z]+)',
        r'(N\.?I\.?T\.?\s*[A-Za-z]+)',
        r'(I\.?I\.?I\.?T\.?\s*[A-Za-z]+)',
        r'(B\.?I\.?T\.?S\.?\s*[A-Za-z]+)',
    ]
    for p in uni_patterns:
        match = re.search(p, section_text)
        if match:
            uni = match.group(1).strip()
            if not re.search(r'\d+\s*%', uni) and len(uni) > 5:
                university = uni[:80]
                break

    # ── GPA / Percentage ─────────────────────────────────────────────────
    gpa = None
    cgpa = re.search(r'(?:CGPA|GPA|CPI|SGPA)[:\s]*(\d+\.?\d*)\s*/?\s*(\d+)?', section_text, re.IGNORECASE)
    if cgpa:
        gpa = cgpa.group(1) + (f"/{cgpa.group(2)}" if cgpa.group(2) else "")
    else:
        pct = re.search(r'(\d{2,3}(?:\.\d+)?)\s*%', section_text)
        if pct and 30 <= float(pct.group(1)) <= 100:
            gpa = f"{pct.group(1)}%"

    # ── Graduation year ──────────────────────────────────────────────────
    grad_year = None
    years = re.findall(r'\b(20[0-3]\d)\b', section_text)
    if years:
        grad_year = max(int(y) for y in years)

    return {
        'degree': degrees[0] if degrees else None,
        'all_degrees': degrees,
        'university': university,
        'gpa': gpa,
        'graduation_year': grad_year,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3D — EXPERIENCE EXTRACTION (EXPERIENCE section, date-range calculator)
# ═══════════════════════════════════════════════════════════════════════════

def extract_experience(sections: dict) -> dict:
    """
    Extract years of experience via date-range calculation.
    Parse "Jan 2020 – Mar 2023" or "2019 – Present" → compute years.
    """
    section_text = sections.get('EXPERIENCE', sections.get('_full', ''))

    # ── Date range patterns ──────────────────────────────────────────────
    month_pattern = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'

    date_patterns = [
        # "Jan 2020 – Mar 2023" or "January 2020 - Present"
        rf'({month_pattern}\s*\.?\s*20\d{{2}})\s*[-–—to]+\s*({month_pattern}\s*\.?\s*20\d{{2}}|[Pp]resent|[Cc]urrent|[Oo]ngoing)',
        # "2020 – 2023" or "2020 - Present"
        r'(20\d{2})\s*[-–—to]+\s*(20\d{2}|[Pp]resent|[Cc]urrent|[Oo]ngoing)',
    ]

    total_years = 0.0
    ranges_found = []

    for pattern in date_patterns:
        for match in re.finditer(pattern, section_text, re.IGNORECASE):
            start_str = match.group(1)
            end_str = match.group(2) if match.lastindex >= 2 else match.group(1)

            # Extract year from start
            start_match = re.search(r'(20\d{2})', start_str)
            if not start_match:
                continue
            start_year = int(start_match.group(1))

            # Extract year from end
            if end_str.lower() in ('present', 'current', 'ongoing'):
                end_year = CURRENT_YEAR
            else:
                end_match = re.search(r'(20\d{2})', end_str)
                if not end_match:
                    continue
                end_year = int(end_match.group(1))

            years = max(0, end_year - start_year)
            if 0 < years <= 30:
                total_years += years
                ranges_found.append(f"{start_year}–{end_year}")

    # ── Explicit mention fallback ────────────────────────────────────────
    if total_years == 0:
        exp_patterns = [
            r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s*(?:of)?\s*(?:experience|exp)',
            r'experience[:\s]*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)',
        ]
        for p in exp_patterns:
            m = re.search(p, sections.get('_full', ''), re.IGNORECASE)
            if m:
                total_years = float(m.group(1))
                break

    total_years = min(total_years, 40.0)

    if ranges_found:
        logger.info(f"   📅 Date ranges: {ranges_found} → {total_years} years")

    # ── Job titles ───────────────────────────────────────────────────────
    title_patterns = [
        r'\b((?:senior|junior|lead|principal|staff|associate|chief)\s+)?(?:software|web|mobile|frontend|front[\-\s]end|backend|back[\-\s]end|full[\-\s]?stack|data|cloud|devops|qa|ml|ai|machine\s+learning|platform|systems?|network|security|database)\s+(?:engineer|developer|architect|analyst|scientist|tester|administrator|consultant|specialist)\b',
        r'\b(product\s+manager|project\s+manager|engineering\s+manager|tech\s+lead|team\s+lead|cto|ceo|vp\s+engineering)\b',
        r'\b(ui[\s/]?ux\s+designer|graphic\s+designer|visual\s+designer)\b',
        r'\b(intern(?:ship)?|trainee|apprentice|fresher)\b',
        r'\b(solution\s+architect|technical\s+architect|enterprise\s+architect)\b',
    ]
    job_titles = []
    for p in title_patterns:
        for m in re.finditer(p, section_text, re.IGNORECASE):
            title = m.group(0).strip().title()
            if title and title not in job_titles:
                job_titles.append(title)

    return {
        'years_experience': total_years,
        'job_titles': job_titles[:6],
        'date_ranges': ranges_found,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3E — COMPANY DETECTION (ORG cross-check with education section)
# ═══════════════════════════════════════════════════════════════════════════

def extract_companies(sections: dict, doc) -> tuple[list[str], list[str]]:
    """
    Extract companies from spaCy ORG entities.
    Cross-checks: if ORG appears in EDUCATION section → institute, else → company.
    Returns (companies, institutions).
    """
    edu_text = sections.get('EDUCATION', '').lower()
    exp_text = sections.get('EXPERIENCE', '').lower()

    all_orgs = set()
    for ent in doc.ents:
        if ent.label_ == "ORG":
            org = ent.text.strip()
            if len(org) > 2 and org.lower() not in ORG_NOISE and len(org.split()) <= 6:
                all_orgs.add(org)

    companies = []
    institutions = []

    for org in all_orgs:
        org_lower = org.lower()
        # Check if it's an institution
        is_institute = (
            any(kw in org_lower for kw in INSTITUTE_KEYWORDS) or
            org_lower in edu_text
        )

        if is_institute:
            institutions.append(org)
            logger.info(f"      🏫 Institute: {org}")
        else:
            # Filter out single-word noise and verbs
            if not re.match(r'^[a-z]', org) or len(org.split()) >= 2:
                companies.append(org)
                logger.info(f"      🏢 Company: {org}")

    return companies, institutions


# ═══════════════════════════════════════════════════════════════════════════
# 3F — LINK EXTRACTION (GitHub, LinkedIn, Portfolio)
# ═══════════════════════════════════════════════════════════════════════════

def extract_links(text: str) -> dict:
    """Extract and categorize all URLs from full text."""
    links = {'github_url': None, 'github_username': None,
             'linkedin_url': None, 'portfolio_url': None, 'other_links': []}

    url_pattern = r'https?://[^\s\)\]>,;\"\']+|www\.[^\s\)\]>,;\"\']+'
    urls = re.findall(url_pattern, text, re.IGNORECASE)

    # Catch bare domain links
    bare = re.findall(r'(?:github\.com|linkedin\.com)/[^\s\)\]>,;\"\']+', text, re.IGNORECASE)
    for b in bare:
        full = 'https://' + b
        if full not in urls:
            urls.append(full)

    for url in urls:
        url_clean = url.rstrip('.,:;')
        url_lower = url_clean.lower()

        if 'github.com' in url_lower:
            links['github_url'] = url_clean
            match = re.search(r'github\.com/([A-Za-z0-9_\-]+)', url_clean, re.I)
            if match:
                uname = match.group(1)
                if uname.lower() not in ('login', 'signup', 'settings', 'explore', 'orgs', 'topics'):
                    links['github_username'] = uname
        elif 'linkedin.com' in url_lower:
            links['linkedin_url'] = url_clean
        elif any(x in url_lower for x in ['portfolio', 'personal', 'blog', 'vercel', 'netlify', 'heroku', 'github.io']):
            links['portfolio_url'] = url_clean
        else:
            links['other_links'].append(url_clean)

    return links


# ═══════════════════════════════════════════════════════════════════════════
# IDENTITY (email, phone, location)
# ═══════════════════════════════════════════════════════════════════════════

def extract_emails(text: str) -> list[str]:
    return list(set(re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)))

def extract_phones(text: str) -> list[str]:
    patterns = [
        r'(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}',
        r'\+?\d{1,3}[\s\-]\d{5}[\s\-]?\d{5}',
        r'\+?\d{10,13}',
    ]
    phones = []
    for p in patterns:
        phones.extend(m.strip() for m in re.findall(p, text))
    return list(set(phones))

def extract_location(text: str, header_text: str = None) -> str | None:
    """
    Extract location, preferring header region.
    Rejects noise words like Technology, Bachelor, Engineering, etc.
    """
    LOCATION_NOISE = [
        'experience', 'education', 'skill', 'project', 'certif', 'university',
        'institute', 'college', 'information technology', 'engineering', 'cgpa',
        'technology', 'bachelor', 'master', 'computer science', 'software',
        'science', 'commerce', 'management', 'diploma', 'degree',
        'artificial intelligence', 'machine learning', 'data science',
        'cyber', 'network', 'system', 'hardware', 'electrical',
    ]
    patterns = [
        r'(?:location|address|city|based in|residing)[:\s]+([^\n,;]{3,50})',
        r'([A-Z][a-z]+,\s*(?:India|USA|UK|Canada|Australia|Germany|France|Japan|China|Singapore|UAE|US|United States))',
        r'([A-Z][a-z]+,\s*[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)?)',
    ]
    # Search header first, then full text
    sources = []
    if header_text:
        sources.append(header_text)
    sources.append(text)

    for source in sources:
        for p in patterns:
            match = re.search(p, source)
            if match:
                loc = match.group(1).strip()
                if len(loc) > 3 and not any(x in loc.lower() for x in LOCATION_NOISE):
                    return loc
    return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION-SPECIFIC EXTRACTORS (projects, certs, achievements, etc.)
# ═══════════════════════════════════════════════════════════════════════════

def extract_certifications(sections: dict) -> list[str]:
    text = sections.get('CERTIFICATIONS', '')
    if not text:
        return []
    certs = []
    for line in text.split('\n'):
        clean = re.sub(r'^[•\-●○▪\d.)\s]+', '', line).strip()
        if clean and 5 < len(clean) < 150:
            certs.append(clean)
    return certs[:10]


def extract_projects(sections: dict) -> list[str]:
    text = sections.get('PROJECTS', '')
    if not text:
        return []
    projects = []
    for line in text.split('\n'):
        clean = re.sub(r'^[•\-●○▪\d.)\s]+', '', line).strip()
        if not clean or len(clean) > 100:
            continue
        if not re.match(r'^(?:used|using|built|developed|created|implemented|designed|worked|responsible)', clean, re.I):
            if re.match(r'^[A-Z]', clean) and len(clean.split()) <= 12:
                projects.append(clean)
    return list(set(projects))[:8]


def extract_languages(sections: dict) -> list[str]:
    text = sections.get('LANGUAGES', '')
    known = [
        'English', 'Hindi', 'Spanish', 'French', 'German', 'Chinese',
        'Mandarin', 'Japanese', 'Korean', 'Arabic', 'Portuguese',
        'Russian', 'Italian', 'Dutch', 'Bengali', 'Tamil', 'Telugu',
        'Marathi', 'Gujarati', 'Kannada', 'Malayalam', 'Punjabi',
        'Urdu', 'Odia', 'Sanskrit', 'Thai', 'Vietnamese',
    ]
    search_text = text if text else sections.get('_full', '')
    return [lang for lang in known if re.search(r'\b' + lang + r'\b', search_text, re.IGNORECASE)]


def extract_achievements(sections: dict) -> list[str]:
    text = sections.get('ACHIEVEMENTS', '')
    if not text:
        return []
    achievements = []
    for line in text.split('\n'):
        clean = re.sub(r'^[•\-●○▪\d.)\s]+', '', line).strip()
        if clean and 5 < len(clean) < 200:
            achievements.append(clean)
    return achievements[:6]


def extract_summary(sections: dict) -> str | None:
    text = sections.get('SUMMARY', '')
    if text:
        return re.sub(r'\s+', ' ', text).strip()[:300] or None
    match = re.search(
        r'(?:summary|objective|profile|about\s*me)[:\s]*\n?([^\n]{20,300})',
        sections.get('_full', ''), re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def extract_interests(sections: dict) -> list[str]:
    text = sections.get('INTERESTS', '')
    if not text:
        return []
    parts = re.split(r'[,;|•●○▪\-\n]', text)
    return [p.strip() for p in parts if p.strip() and 2 < len(p.strip()) < 50][:8]


# ═══════════════════════════════════════════════════════════════════════════
# PARSING CONFIDENCE METRIC
# ═══════════════════════════════════════════════════════════════════════════

def calculate_parsing_confidence(sections: dict, data: dict) -> float:
    """
    Deterministic confidence score for parsing quality (0–100).
    Based on section detection, field population, and extraction depth.
    """
    score = 0.0

    # Section detection success (30 pts max)
    detected = [s for s in sections if not s.startswith('_')]
    section_score = min(len(detected) / 5 * 30, 30)
    score += section_score

    # Core fields populated (40 pts max)
    core = ['full_name', 'email', 'phone']
    for field in core:
        if data.get(field):
            score += 10

    if data.get('location'):
        score += 5
    if data.get('degree'):
        score += 5

    # Skill count (15 pts max)
    skill_count = len(data.get('normalized_skills', []))
    score += min(skill_count / 5 * 15, 15)

    # Experience data (10 pts max)
    if data.get('years_experience', 0) > 0:
        score += 5
    if data.get('companies'):
        score += 5

    # GitHub (5 pts)
    if data.get('github_username'):
        score += 5

    return round(min(score, 100), 1)
