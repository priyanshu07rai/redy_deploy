"""
Resume upload, confirmation, and analysis routes.
Implements the 8-step intelligence pipeline with full console logging.
"""

import os
import hashlib
import json
import logging
import re as _re
from werkzeug.utils import secure_filename
from flask import (
    render_template, redirect, url_for, request,
    session, flash, current_app, send_file,
)
from auth.routes import login_required, role_required
from database import get_db
from . import resume_bp
from .extractor import extract_text, parse_resume
from .scorer import calculate_fraud_probability, calculate_scores, fraud_level
from .github_api import fetch_github_profile
from .summary_generator import generate_summary
from .audit import log_audit, log_field_edits

logger = logging.getLogger('resume_engine.routes')


def _allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_EXTENSIONS', {'pdf'})


# ─── Upload Resume (GET: form, POST: process pipeline) ──────────────────────

@resume_bp.route('/upload', methods=('GET', 'POST'))
@login_required
@role_required('employee')
def upload():
    if request.method == 'POST':
        logger.info("═" * 60)
        logger.info("📤 RESUME UPLOAD PIPELINE STARTED")
        logger.info("═" * 60)

        # ── STEP 1: File Handling ────────────────────────────────────────
        logger.info("🔐 STEP 1 — File Handling")
        file = request.files.get('resume')
        github_username = request.form.get('github_username', '').strip()
        company_code = request.form.get('company_code', '').strip()

        if not company_code:
            logger.warning("   ❌ No company code provided")
            flash('Company Code is required.')
            return redirect(url_for('resume.upload'))

        db = get_db()
        # ── Validate Company Scope ──────────────────────────────────────────
        company = db.execute(
            'SELECT id FROM companies WHERE company_code = ?', (company_code,)
        ).fetchone()

        if not company:
            logger.warning(f"   ❌ Invalid company code: {company_code}")
            flash('Invalid Company Code. Please check with your recruiter.')
            return redirect(url_for('resume.upload'))

        company_id = company['id']

        if not file or file.filename == '':
            logger.warning("   ❌ No file selected")
            flash('Please select a PDF file to upload.')
            return redirect(url_for('resume.upload'))

        if not _allowed_file(file.filename):
            logger.warning(f"   ❌ Invalid file type: {file.filename}")
            flash('Only PDF files are accepted.')
            return redirect(url_for('resume.upload'))

        # Determine version
        user_id = session['user_id']
        latest = db.execute(
            'SELECT MAX(resume_version) as max_v FROM candidates WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        version = (latest['max_v'] or 0) + 1
        logger.info(f"   User ID: {user_id}")
        logger.info(f"   Version: {version}")

        # Save file
        upload_dir = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{user_id}_v{version}.pdf"
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        logger.info(f"   Saved to: {filepath}")

        # SHA-256 hash
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        file_hash = sha256.hexdigest()
        logger.info(f"   SHA-256: {file_hash[:32]}...")

        # ── Audit: resume upload ──────────────────────────────────────────
        log_audit(user_id, 'resume_upload', field='filename', new_value=filename)
        log_audit(user_id, 'hash_generated', field='sha256', new_value=file_hash[:32] + '...')

        # ── STEP 2: Text Extraction (PyMuPDF) ───────────────────────────
        logger.info("")
        logger.info("📄 STEP 2 — Text Extraction (PyMuPDF)")
        try:
            resume_text, layout_data = extract_text(filepath)
        except Exception as e:
            logger.error(f"   ❌ PDF extraction failed: {e}")
            flash(f'Failed to read PDF: {e}')
            os.remove(filepath)
            return redirect(url_for('resume.upload'))

        if not resume_text or len(resume_text.strip()) < 20:
            logger.warning("   ❌ Insufficient text extracted")
            flash('Could not extract text from the PDF. Please upload a text-based PDF (not scanned).')
            os.remove(filepath)
            return redirect(url_for('resume.upload'))

        # ── STEP 3: Structured Data Extraction (spaCy NLP) ──────────────
        logger.info("")
        logger.info("🧠 STEP 3 — Structured Data Extraction (spaCy NLP)")
        parsed = parse_resume(resume_text, github_username, layout_data=layout_data)

        # ── STEP 3.5: AI Summary Generation ──────────────────────────────
        logger.info("")
        logger.info("🤖 STEP 3.5 — AI Summary Generation")
        ai_summary = generate_summary(parsed)
        if ai_summary:
            log_audit(user_id, 'ai_summary_generated',
                      field='ai_generated_summary', new_value=ai_summary[:100])

        # ── Compute preview scores for display on confirm page ───────────
        fraud_prob = calculate_fraud_probability(resume_text)
        preview_scores = calculate_scores(parsed, fraud_prob)

        # Store extraction data in session — includes preview scores
        session['pending_resume'] = {
            'filepath': filepath,
            'file_hash': file_hash,
            'version': version,
            'parsed': parsed,
            'resume_text': resume_text[:5000],
            'ai_summary': ai_summary,
            'preview_scores': preview_scores,
            'fraud_probability': fraud_prob,
            'company_id': company_id,
        }

        logger.info("")
        logger.info("✅ Data extraction complete — redirecting to verification")
        logger.info("═" * 60)

        return redirect(url_for('resume.confirm'))

    db = get_db()
    companies = db.execute('SELECT * FROM companies').fetchall()
    return render_template('upload_resume.html', companies=companies)


# ─── Confirmation Screen (STEP 6 — Data Verification Only) ──────────────────

@resume_bp.route('/confirm', methods=('GET', 'POST'))
@login_required
@role_required('employee')
def confirm():
    pending = session.get('pending_resume')
    if not pending:
        flash('No pending resume. Please upload first.')
        return redirect(url_for('resume.upload'))

    if request.method == 'POST':
        # ── STEP 7: Final Database Commit (with user edits) ──────────────
        logger.info("═" * 60)
        logger.info("💾 STEP 7 — Final Database Commit (user-edited)")

        db = get_db()
        user_id = session['user_id']
        resume_text = pending.get('resume_text', '')

        # ── Read user-edited form data ───────────────────────────────────
        import re as _re

        full_name = request.form.get('full_name', '').strip() or None
        email = request.form.get('email', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        location = request.form.get('location', '').strip() or None

        github_url = request.form.get('github_url', '').strip() or None
        linkedin_url = request.form.get('linkedin_url', '').strip() or None
        portfolio_url = request.form.get('portfolio_url', '').strip() or None

        summary = request.form.get('summary', '').strip() or None

        # Parse skills from comma-separated string
        skills_raw = request.form.get('skills', '')
        skills = [s.strip() for s in skills_raw.split(',') if s.strip()]

        years_exp = float(request.form.get('years_experience', 0) or 0)
        job_titles_raw = request.form.get('job_titles', '')
        job_titles = [t.strip() for t in job_titles_raw.split(',') if t.strip()]
        companies_raw = request.form.get('companies', '')
        companies = [c.strip() for c in companies_raw.split(',') if c.strip()]

        degree = request.form.get('degree', '').strip() or None
        university = request.form.get('university', '').strip() or None
        grad_year_raw = request.form.get('graduation_year', '').strip()
        graduation_year = int(grad_year_raw) if grad_year_raw and grad_year_raw.isdigit() else None
        gpa = request.form.get('gpa', '').strip() or None

        # Parse multi-line fields
        certs_raw = request.form.get('certifications', '')
        certifications = [c.strip() for c in certs_raw.split('\n') if c.strip()]
        projects_raw = request.form.get('projects', '')
        projects = [p.strip() for p in projects_raw.split('\n') if p.strip()]
        languages_raw = request.form.get('languages', '')
        languages = [l.strip() for l in languages_raw.split(',') if l.strip()]
        achievements_raw = request.form.get('achievements', '')
        achievements = [a.strip() for a in achievements_raw.split('\n') if a.strip()]
        interests_raw = request.form.get('interests', '')
        interests = [i.strip() for i in interests_raw.split(',') if i.strip()]

        # Extract github_username from URL if provided
        github_username = None
        if github_url:
            gh_match = _re.search(r'github\.com/([A-Za-z0-9_\-]+)', github_url)
            if gh_match:
                github_username = gh_match.group(1)

        logger.info(f"   ✏ User-edited: name={full_name}, email={email}, phone={phone}")
        logger.info(f"   ✏ Links: github={github_url}, linkedin={linkedin_url}")
        logger.info(f"   ✏ Skills ({len(skills)}): {skills[:8]}")
        logger.info(f"   ✏ Education: {degree} @ {university}")

        # Build parsed dict from user edits
        parsed = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'location': location,
            'skills': skills,
            'skill_count': len(skills),
            'github_username': github_username,
        }

        # ── Compute scores ───────────────────────────────────────────────
        logger.info("")
        logger.info("🧮 Computing scores on confirmation...")
        fraud_prob = calculate_fraud_probability(resume_text)

        github_data = {}
        if github_username:
            logger.info(f"   Fetching GitHub profile: {github_username}")
            github_data = fetch_github_profile(github_username)
            if github_data.get('error'):
                logger.warning(f"   ⚠ GitHub API: {github_data['error']}")
            else:
                logger.info(f"   ✅ GitHub score: {github_data.get('github_score', 0)}")

        scores = calculate_scores(parsed, fraud_prob, github_data)

        # ── Build extended data JSON ──────────────────────────────────────
        extended_data = json.dumps({
            'all_emails': pending.get('parsed', {}).get('all_emails', []),
            'all_phones': pending.get('parsed', {}).get('all_phones', []),
            'github_url': github_url,
            'linkedin_url': linkedin_url,
            'portfolio_url': portfolio_url,
            'other_links': pending.get('parsed', {}).get('other_links', []),
            'all_degrees': [degree] if degree else [],
            'graduation_year': graduation_year,
            'gpa': gpa,
            'companies': companies,
            'job_titles': job_titles,
            'certifications': certifications,
            'projects': projects,
            'languages': languages,
            'achievements': achievements,
            'summary': summary,
            'interests': interests,
        })

        # ── Handle summaries ──────────────────────────────────────────────
        ai_summary = pending.get('ai_summary', None)
        user_summary = request.form.get('ai_summary', '').strip() or ai_summary

        # Get company_id from session (stored during upload step)
        company_id = pending.get('company_id')
        if not company_id:
            logger.error("   ❌ Missing company_id in pending resume session")
            flash('Session expired or invalid company. Please upload again.')
            return redirect(url_for('resume.upload'))

        # Delete old records for this user so the page always shows fresh data
        db.execute('DELETE FROM candidates WHERE user_id = ?', (user_id,))

        db.execute('''
            INSERT INTO candidates
            (user_id, resume_path, resume_hash, resume_version,
             full_name, email_extracted, phone, location,
             skills, skill_count, years_experience,
             degree, university, github_username,
             github_score, identity_score, fraud_probability,
             resume_score, extended_data,
             ai_generated_summary, user_edited_summary, status, company_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
        ''', (
            user_id,
            pending['filepath'],
            pending['file_hash'],
            pending['version'],
            full_name,
            email,
            phone,
            location,
            json.dumps(skills),
            len(skills),
            years_exp,
            degree,
            university,
            github_username,
            scores.get('github_score', 0),
            scores.get('identity_score', 0),
            fraud_prob,
            scores.get('resume_score', 0),
            extended_data,
            ai_summary,
            user_summary,
            company_id,
        ))
        db.commit()

        # Get the candidate ID for audit logging
        candidate_id = db.execute(
            'SELECT id FROM candidates WHERE user_id = ? ORDER BY id DESC LIMIT 1',
            (user_id,)
        ).fetchone()['id']

        # ── Audit: field edits ───────────────────────────────────────────
        original_parsed = pending.get('parsed', {})
        edited = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'location': location,
            'skills': skills,
            'degree': degree,
            'university': university,
            'summary': user_summary,
        }
        log_field_edits(
            user_id, candidate_id, original_parsed, edited,
            ['full_name', 'email', 'phone', 'location', 'skills', 'degree', 'university', 'summary']
        )
        log_audit(user_id, 'confirmation_submitted', candidate_id=candidate_id)

        logger.info(f"   ✅ Record saved for user {user_id} (old records deleted)")
        logger.info(f"   Version: {pending['version']}")
        logger.info(f"   Score: {scores.get('resume_score', 0)}")
        logger.info("═" * 60)

        session.pop('pending_resume', None)

        flash('Resume submitted successfully!')
        return redirect(url_for('employee_dashboard'))

    db = get_db()
    company_name = "Unknown Company"
    company_id = pending.get('company_id')
    if company_id:
        company = db.execute('SELECT company_name FROM companies WHERE id = ?', (company_id,)).fetchone()
        if company:
            company_name = company['company_name']

    return render_template('confirm_resume.html', data=pending, company_name=company_name)


# ─── Cancel Upload ───────────────────────────────────────────────────────────

@resume_bp.route('/cancel', methods=('POST',))
@login_required
@role_required('employee')
def cancel():
    pending = session.pop('pending_resume', None)
    if pending and pending.get('filepath') and os.path.exists(pending['filepath']):
        os.remove(pending['filepath'])
        logger.info(f"🗑 Upload cancelled — deleted {pending['filepath']}")
    flash('Upload cancelled.')
    return redirect(url_for('employee_dashboard'))


# ─── Upload Supporting Document ──────────────────────────────────────────────

@resume_bp.route('/upload_document', methods=['POST'])
@login_required
@role_required('employee')
def upload_document():
    db = get_db()
    user_id = session['user_id']
    
    file = request.files.get('document')
    doc_type = request.form.get('doc_type', 'Other')
    
    if not file or file.filename == '':
        flash('No file selected.')
        return redirect(url_for('employee_dashboard'))
        
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in {'pdf', 'png', 'jpg', 'jpeg'}:
        flash('Only PDF, PNG, and JPG files are supported for supporting documents.')
        return redirect(url_for('employee_dashboard'))
        
    candidate = db.execute(
        'SELECT id, uploaded_documents FROM candidates WHERE user_id = ? ORDER BY resume_version DESC LIMIT 1',
        (user_id,)
    ).fetchone()
    
    if not candidate:
        flash('Please upload your resume first.')
        return redirect(url_for('employee_dashboard'))
        
    # Secure storage
    docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'docs')
    os.makedirs(docs_dir, exist_ok=True)
    
    # Generate unique filename
    import uuid
    uid = str(uuid.uuid4())[:8]
    safe_filename = secure_filename(file.filename)
    unique_filename = f"c{candidate['id']}_{uid}_{safe_filename}"
    filepath = os.path.join(docs_dir, unique_filename)
    
    file.save(filepath)
    
    # Update candidate record
    docs = []
    try:
        if candidate['uploaded_documents']:
            docs = json.loads(candidate['uploaded_documents'])
    except:
        pass
        
    docs.append({
        'type': doc_type,
        'filename': unique_filename,
        'original_name': safe_filename
    })
    
    db.execute('UPDATE candidates SET uploaded_documents = ? WHERE id = ?', (json.dumps(docs), candidate['id']))
    db.commit()
    
    flash(f'{doc_type} uploaded successfully.')
    return redirect(url_for('employee_dashboard'))


# ─── View Uploaded Document ──────────────────────────────────────────────────

@resume_bp.route('/view_document/<filename>')
@login_required
def view_document(filename):
    # Security: don't let people use ../ to escape dir
    safe_filename = secure_filename(filename)
    docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'docs')
    filepath = os.path.join(docs_dir, safe_filename)
    
    if not os.path.exists(filepath):
        flash('Document file not found on disk.')
        return redirect(request.referrer or url_for('recruiter_dashboard'))
        
    ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else ''
    mime_type = 'application/pdf'
    if ext == 'png':
        mime_type = 'image/png'
    elif ext in ['jpg', 'jpeg']:
        mime_type = 'image/jpeg'
        
    return send_file(filepath, mimetype=mime_type)


# ─── Resume Analysis View ───────────────────────────────────────────────────

@resume_bp.route('/analysis')
@login_required
def analysis():
    db = get_db()
    user_id = session['user_id']
    role = session.get('role')

    # Recruiters can view any candidate via ID, employees only their own
    candidate_id = request.args.get('candidate_id', type=int)

    if role == 'recruiter' and candidate_id:
        candidate = db.execute(
            'SELECT * FROM candidates WHERE id = ?', (candidate_id,)
        ).fetchone()
    else:
        candidate = db.execute(
            'SELECT * FROM candidates WHERE user_id = ? ORDER BY resume_version DESC LIMIT 1',
            (user_id,)
        ).fetchone()

    if not candidate:
        flash('No resume found. Please upload one first.')
        return redirect(url_for('employee_dashboard'))

    # Parse skills from JSON
    skills = []
    try:
        skills = json.loads(candidate['skills']) if candidate['skills'] else []
    except (json.JSONDecodeError, TypeError):
        skills = []

    # Parse extended data
    extended = {}
    try:
        extended = json.loads(candidate['extended_data']) if candidate['extended_data'] else {}
    except (json.JSONDecodeError, TypeError):
        extended = {}

    # Fetch interview data if it exists
    interview = db.execute(
        'SELECT * FROM interviews WHERE candidate_id = ? ORDER BY id DESC LIMIT 1',
        (candidate['id'],)
    ).fetchone()

    logger.info(f"📊 Viewing analysis for user {user_id}, version {candidate['resume_version']} (Role: {role})")

    return render_template('resume_analysis.html',
                           candidate=candidate,
                           skills=skills,
                           extended=extended,
                           interview=interview,
                           role=role,
                           fraud_lvl=fraud_level(candidate['fraud_probability']))


# ─── View Uploaded Resume PDF ────────────────────────────────────────────────

@resume_bp.route('/view_pdf')
@login_required
def view_pdf():
    db = get_db()
    user_id = session['user_id']
    role = session.get('role')
    
    # Recruiters can view by candidate_id, employees only their own
    candidate_id = request.args.get('candidate_id', type=int)

    if role == 'recruiter' and candidate_id:
        company_id = session.get('company_id')
        candidate = db.execute(
            'SELECT resume_path FROM candidates WHERE id = ? AND company_id = ?', 
            (candidate_id, company_id)
        ).fetchone()
        if not candidate:
            flash('Unauthorized access or candidate not found.')
            return redirect(url_for('recruiter_dashboard'))
    else:
        # Fallback for employee view (their own latest)
        candidate = db.execute(
            'SELECT resume_path FROM candidates WHERE user_id = ? ORDER BY resume_version DESC LIMIT 1',
            (user_id,)
        ).fetchone()

    if not candidate or not candidate['resume_path']:
        flash('No resume file found.')
        if role == 'recruiter':
            return redirect(url_for('recruiter_dashboard'))
        return redirect(url_for('employee_dashboard'))

    filepath = candidate['resume_path']
    if not os.path.exists(filepath):
        flash('Resume file not found on disk.')
        if role == 'recruiter':
             return redirect(url_for('recruiter_dashboard'))
        return redirect(url_for('resume.analysis'))

    return send_file(filepath, mimetype='application/pdf')
