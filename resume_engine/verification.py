import os
import re
import json
import logging
import requests
from difflib import SequenceMatcher
from urllib.parse import urlparse
import google.generativeai as genai
from flask import current_app

logger = logging.getLogger('resume_engine')

def compute_name_similarity(name1, name2):
    if not name1 or not name2:
        return 0
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()

def verify_identity(resume_name, github_data, linkedin_url):
    """
    Identity Confidence Score (0-100)
    Based on name similarity across platforms and presence of links.
    """
    score = 50 # Base score for just having a resume name
    
    if not resume_name:
        return 0
        
    match_details = []
    
    # Check GitHub match
    if github_data and github_data.get('username'):
        gh_name = github_data.get('username')
        sim = compute_name_similarity(resume_name, gh_name)
        if sim > 0.6:
            score += 25
            match_details.append(f"GitHub: High similarity ({gh_name})")
        else:
            score += 10
            match_details.append(f"GitHub: Present but low similarity ({gh_name})")
    
    # Check LinkedIn format (No scraping)
    if linkedin_url:
        parsed = urlparse(linkedin_url)
        if 'linkedin.com/in/' in parsed.path.lower():
            # Try to extract name from url
            li_username = parsed.path.strip('/').split('/')[-1]
            sim = compute_name_similarity(resume_name.replace(" ", ""), li_username)
            if sim > 0.5:
                score += 25
                match_details.append(f"LinkedIn: Format valid, high URL similarity ({li_username})")
            else:
                score += 15
                match_details.append(f"LinkedIn: Format valid ({li_username})")
    
    score = min(round(score), 100)
    return {
        'score': score,
        'details': match_details
    }

def verify_certificates(cert_claims, uploaded_docs):
    """
    Certificate Validity (0-100)
    """
    if not cert_claims and not uploaded_docs:
        return {'score': 0, 'details': ["No certificates claimed or uploaded."]}
        
    score = 0
    details = []
    
    # If they uploaded documents that look like certificates
    cert_docs = [d for d in uploaded_docs if 'cert' in d.get('type', '').lower() or 'cert' in d.get('original_name', '').lower()]
    
    if cert_docs:
        score += 60
        details.append(f"Uploaded {len(cert_docs)} certificate documents.")
    elif cert_claims:
        score += 30
        details.append(f"Claimed {len(cert_claims)} certificates but uploaded none.")
        
    # Pattern matching for common issuers in text (basic network valid check)
    has_aws = any('aws' in str(c).lower() for c in cert_claims)
    has_gcp = any('google' in str(c).lower() for c in cert_claims)
    has_azure = any('azure' in str(c).lower() for c in cert_claims)
    
    if has_aws or has_gcp or has_azure:
        score += 40
        details.append("Major cloud provider certifications identified (Awaiting Badge API connection).")
        
    if score == 0 and cert_claims:
        score = 20 # Minimum credit for claiming something
        
    score = min(score, 100)
    
    return {
        'score': score,
        'status': 'Verified' if score >= 80 else 'Partial' if score >= 40 else 'Unverified',
        'details': details
    }

def verify_portfolio(portfolio_url):
    """
    Portfolio Validation (0-100)
    """
    if not portfolio_url:
        return {'score': 0, 'status': 'Not Provided', 'details': "No portfolio link found."}
        
    score = 20
    status = 'Unverified'
    details = f"URL: {portfolio_url}"
    
    try:
        # Check if domain reachable (fast HEAD request)
        if not portfolio_url.startswith('http'):
            portfolio_url = 'https://' + portfolio_url
            
        resp = requests.head(portfolio_url, timeout=5, allow_redirects=True)
        if resp.status_code < 400:
            score += 80
            status = 'Active'
            details = "Domain is reachable and active."
        else:
            score += 30
            status = 'Broken'
            details = f"URL returned HTTP {resp.status_code}."
    except Exception as e:
        status = 'Broken'
        details = "URL could not be resolved or timed out."
        
    return {
        'score': score,
        'status': status,
        'details': details
    }

def behavior_skill_alignment(resume_skills, transcript_text):
    """
    Behavioral Skill Alignment (0-100) using Gemini.
    Compares resume claims vs interview transcript.
    """
    if not resume_skills:
        return {'score': 0, 'details': "No skills found on resume."}
        
    if not transcript_text or len(transcript_text.strip()) < 50:
        return {'score': 0, 'details': "Transcript too short to evaluate."}
        
    gemini_key = current_app.config.get('GEMINI_API_KEY')
    if not gemini_key:
        # Fallback keyword matching
        matched = 0
        transcript_lower = transcript_text.lower()
        for skill in resume_skills:
            if skill.lower() in transcript_lower:
                matched += 1
        pct = (matched / len(resume_skills)) * 100 if resume_skills else 0
        return {
            'score': round(pct),
            'details': f"Basic keyword match: {matched} of {len(resume_skills)} skills mentioned."
        }

    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        You are an expert technical interviewer evaluating a candidate's consistency.
        The candidate claims the following skills on their resume:
        {', '.join(resume_skills[:15])}
        
        Below is the transcript of their technical interview:
        "{transcript_text[:3000]}"
        
        Analyze the skill depth demonstrated in the interview compared to their resume claims.
        Return ONLY a JSON object with this exact format:
        {{
            "score": <integer 0-100>,
            "depth_analysis": {{
                "skill_1": "Level demonstrated (e.g., Deep, Surface level, Not discussed)",
                "skill_2": "..."
            }}
        }}
        """
        
        response = model.generate_content(prompt)
        text = response.text
        
        # Clean JSON blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].strip()
            
        data = json.loads(text)
        return {
            'score': min(max(int(data.get('score', 0)), 0), 100),
            'details': data.get('depth_analysis', {})
        }
        
    except Exception as e:
        logger.error(f"Gemini Skill Alignment Error: {e}")
        return {'score': 50, 'details': "Failed to analyze transcript via AI. Used neutral score."}

def compute_trust_report(parsed_data, github_data, interview_transcript, uploaded_docs):
    """
    Master function to compute the entire Verification & Trust module data.
    """
    # 1. Identity
    identity_res = verify_identity(
        parsed_data.get('name'), 
        github_data, 
        parsed_data.get('links', {}).get('linkedin_url')
    )
    
    # 2. GitHub Authenticity
    github_score = github_data.get('github_score', 0) if github_data else 0
    
    # 3. Certificates
    cert_res = verify_certificates(parsed_data.get('certifications', []), uploaded_docs)
    
    # 4. Portfolio
    port_url = parsed_data.get('links', {}).get('portfolio_url')
    # fallback to any unknown link
    if not port_url:
        for link in parsed_data.get('links', {}).values():
            if link and 'github' not in link and 'linkedin' not in link:
                port_url = link
                break
                
    port_res = verify_portfolio(port_url)
    
    # 5. Behavioral Alignment
    behavior_res = behavior_skill_alignment(parsed_data.get('skills', []), interview_transcript)
    
    # Formula: 0.25 ID + 0.25 GH + 0.20 Certs + 0.20 Port + 0.10 Skills
    trust_score = (
        (0.25 * identity_res['score']) +
        (0.25 * github_score) +
        (0.20 * cert_res['score']) +
        (0.20 * port_res['score']) +
        (0.10 * behavior_res['score'])
    )
    
    overall_score = round(trust_score)
    trust_level = "🟢 High Trust" if overall_score >= 80 else "🟡 Moderate Trust" if overall_score >= 60 else "🔴 Low Trust"
    
    return {
        'overall_score': overall_score,
        'trust_level': trust_level,
        'identity': identity_res,
        'github_authenticity': github_score,
        'github_details': github_data,
        'certificates': cert_res,
        'portfolio': port_res,
        'behavioral_alignment': behavior_res
    }
