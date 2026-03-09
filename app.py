import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from config import Config
from database import close_db, init_db, get_db
from auth import auth_bp
from auth.routes import login_required, role_required
from resume_engine import resume_bp
from interview_engine import interview_bp

# ─── Configure Console Logging for Resume Engine ────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(name)s | %(message)s')
resume_logger = logging.getLogger('resume_engine')
resume_logger.setLevel(logging.INFO)


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # Load SMTP/mail config explicitly
    app.config['MAIL_SERVER'] = Config.MAIL_SERVER
    app.config['MAIL_PORT'] = Config.MAIL_PORT
    app.config['MAIL_USE_TLS'] = Config.MAIL_USE_TLS
    app.config['MAIL_USERNAME'] = Config.MAIL_USERNAME
    app.config['MAIL_PASSWORD'] = Config.MAIL_PASSWORD
    app.config['OTP_EXPIRY_MINUTES'] = Config.OTP_EXPIRY_MINUTES
    app.config['OTP_MAX_ATTEMPTS'] = Config.OTP_MAX_ATTEMPTS
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
    app.config['ALLOWED_EXTENSIONS'] = Config.ALLOWED_EXTENSIONS
    app.config['GITHUB_TOKEN'] = Config.GITHUB_TOKEN
    app.config['GEMINI_API_KEY'] = Config.GEMINI_API_KEY

    if test_config:
        app.config.from_mapping(test_config)

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Register Jinja filters
    @app.template_filter('pad_zero')
    def pad_zero_filter(value, width=4):
        return str(value).zfill(width)

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(resume_bp, url_prefix='/resume')
    app.register_blueprint(interview_bp, url_prefix='/interview')

    # Ensure interview uploads directory exists
    os.makedirs(app.config.get('INTERVIEW_UPLOAD_FOLDER',
        os.path.join(os.path.dirname(__file__), 'uploads', 'interviews')), exist_ok=True)

    @app.route('/')
    def index():
        if 'user_id' in session:
            if session.get('role') == 'employee':
                return redirect(url_for('employee_dashboard'))
            elif session.get('role') == 'recruiter':
                return redirect(url_for('recruiter_dashboard'))
        return redirect(url_for('auth.login'))

    @app.route('/employee_dashboard')
    @login_required
    @role_required('employee')
    def employee_dashboard():
        db = get_db()
        user_id = session['user_id']

        # Fetch user email for greeting
        user = db.execute('SELECT email FROM users WHERE id = ?', (user_id,)).fetchone()

        # Fetch latest candidate record
        candidate = db.execute(
            'SELECT * FROM candidates WHERE user_id = ? ORDER BY resume_version DESC LIMIT 1',
            (user_id,)
        ).fetchone()

        # Fetch latest interview record if candidate exists
        interview = None
        if candidate:
            interview = db.execute(
                'SELECT * FROM interviews WHERE candidate_id = ? ORDER BY created_at DESC LIMIT 1',
                (candidate['id'],)
            ).fetchone()

        # Parse skills JSON for template
        skills = []
        if candidate and candidate['skills']:
            try:
                skills = json.loads(candidate['skills'])
            except (json.JSONDecodeError, TypeError):
                skills = []

        # Parse uploaded documents
        uploaded_documents = []
        if candidate and candidate['uploaded_documents']:
            try:
                uploaded_documents = json.loads(candidate['uploaded_documents'])
            except (json.JSONDecodeError, TypeError):
                uploaded_documents = []

        return render_template('employee_dashboard.html',
                               user=user,
                               candidate=candidate,
                               interview=interview,
                               skills=skills,
                               uploaded_documents=uploaded_documents)

    @app.route('/recruiter_dashboard')
    @login_required
    @role_required('recruiter')
    def recruiter_dashboard():
        db = get_db()
        user_id = session['user_id']
        
        # 1. Get recruiter's company from session (handles both real and virtual recruiters)
        company_id = session.get('company_id')
        
        company = None
        if company_id:
            company = db.execute('SELECT * FROM companies WHERE id = ?', (company_id,)).fetchone()

        # 2. Fetch scoped candidates with their scores and interviews
        query = '''
            SELECT 
                c.id, c.full_name, c.resume_score, c.fraud_probability, c.status as resume_status, c.created_at,
                i.integrity_index, i.final_answer_score, i.id as interview_id,
                fs.combined_score, fs.rank_position, fs.is_verified, fs.verification_hash
            FROM candidates c
            LEFT JOIN interviews i ON i.candidate_id = c.id
            LEFT JOIN final_scores fs ON fs.candidate_id = c.id
            WHERE c.company_id = ?
        '''
        
        # If no company_id is set (legacy admin or error state), we shouldn't show candidates, or show all if we want to default to that?
        # The prompt says strictly scoped: "sees only their company candidates"
        if not company_id:
            raw_candidates = []
        else:
            raw_candidates = db.execute(query, (company_id,)).fetchall()

        computed_candidates = []
        stats = {'total': 0, 'verified': 0, 'pending': 0}
        
        for rc in raw_candidates:
            stats['total'] += 1
            if rc['is_verified']:
                stats['verified'] += 1
            else:
                stats['pending'] += 1
                
            res_score = rc['resume_score'] or 0
            int_idx = rc['integrity_index'] or 0
            ans_score = rc['final_answer_score'] or 0
            
            # Phase 6 Feature: Setup Document Penalty
            penalty = 0
            
            # Parse Candidate Extracted vs Uploaded Documents
            uploaded_types = []
            try:
                candidate = db.execute('SELECT uploaded_documents, extended_data FROM candidates WHERE id = ?', (rc['id'],)).fetchone()
                if candidate and candidate['uploaded_documents']:
                    docs = json.loads(candidate['uploaded_documents'])
                    uploaded_types = [doc['type'].lower() for doc in docs]
                    
                extended_data = {}
                if candidate and candidate['extended_data']:
                    extended_data = json.loads(candidate['extended_data'])
                    
            except (json.JSONDecodeError, TypeError):
                pass

            # Core Documents missing penalty
            if not any('10th' in t for t in uploaded_types):
                penalty += 2
            if not any('12th' in t for t in uploaded_types):
                penalty += 2
                
            # If the resume claims a degree but no degree uploaded
            claimed_degrees = extended_data.get('all_degrees', [])
            if any(d for d in claimed_degrees if d) and not any('degree certificate' in t for t in uploaded_types):
                penalty += 5

            # Compute Combined Score & Apply Penalty
            combined = (0.40 * res_score) + (0.35 * int_idx) + (0.25 * ans_score)
            combined = max(0, combined - penalty)
            
            # Update Final Scores table if not verified
            if not rc['is_verified']:
                db.execute('''
                    INSERT INTO final_scores (candidate_id, combined_score)
                    VALUES (?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET combined_score = excluded.combined_score
                ''', (rc['id'], combined))
            
            c_dict = dict(rc)
            c_dict['computed_combined_score'] = rc['combined_score'] if rc['is_verified'] else combined
            computed_candidates.append(c_dict)

        db.commit()

        # Sort dynamically and assign ranks
        computed_candidates.sort(key=lambda x: x['computed_combined_score'], reverse=True)
        
        for rank, c in enumerate(computed_candidates, start=1):
            c['rank'] = rank
            if not c['is_verified']:
                db.execute('UPDATE final_scores SET rank_position = ? WHERE candidate_id = ?', (rank, c['id']))
        
        db.commit()

        return render_template('recruiter_dashboard.html', 
                               company=company,
                               candidates=computed_candidates, 
                               stats=stats)

    @app.route('/candidate/<int:candidate_id>/profile')
    @login_required
    @role_required('recruiter')
    def candidate_profile(candidate_id):
        db = get_db()
        user_id = session['user_id']
        recruiter_company_id = session.get('company_id')
        
        # Strictly scope query by company
        candidate = db.execute('SELECT * FROM candidates WHERE id = ? AND company_id = ?', 
                               (candidate_id, recruiter_company_id)).fetchone()
        
        if not candidate:
            flash("Unauthorized access: Candidate not found in your company.")
            return redirect(url_for('recruiter_dashboard'))
            
        interview = db.execute('SELECT * FROM interviews WHERE candidate_id = ? ORDER BY id DESC LIMIT 1', (candidate_id,)).fetchone()
        final_score = db.execute('SELECT * FROM final_scores WHERE candidate_id = ?', (candidate_id,)).fetchone()
        
        # Parse skills and extended data
        skills = []
        try:
            skills = json.loads(candidate['skills']) if candidate['skills'] else []
        except:
            skills = []
            
        extended = {}
        try:
            extended = json.loads(candidate['extended_data']) if candidate['extended_data'] else {}
        except:
            extended = {}
            
        # 1. Rank Calculation
        all_candidates = db.execute('''
            SELECT c.id, f.combined_score 
            FROM candidates c
            LEFT JOIN final_scores f ON c.id = f.candidate_id 
            WHERE c.company_id = ? 
            ORDER BY COALESCE(f.combined_score, 0) DESC
        ''', (recruiter_company_id,)).fetchall()
        
        total_batch = len(all_candidates)
        rank_pos = 0
        for i, cand in enumerate(all_candidates):
            if cand['id'] == candidate_id:
                rank_pos = i + 1
                break
        
        percentile = round((1 - (rank_pos - 1) / total_batch) * 100) if total_batch > 0 else 0
        
        # 2. Company Benchmarks (Average of all candidates in this company)
        benchmarks = db.execute('''
            SELECT 
                AVG(resume_score) as avg_resume,
                AVG(i.integrity_index) as avg_integrity,
                AVG(i.final_answer_score) as avg_answer,
                AVG(f.combined_score) as avg_combined
            FROM candidates c
            LEFT JOIN interviews i ON c.id = i.candidate_id
            LEFT JOIN final_scores f ON c.id = f.candidate_id
            WHERE c.company_id = ?
        ''', (recruiter_company_id,)).fetchone()
        
        # 3. Behavioral Observations (Human-readable)
        behavior_obs = []
        if interview and interview['anomaly_flags']:
            try:
                flags = json.loads(interview['anomaly_flags'])
                for k, v in flags.items():
                    if k == 'fullscreen_exits' and v > 0:
                        behavior_obs.append(f"{v} fullscreen exit(s) detected")
                    elif k == 'no_face_detected' and v > 0:
                        behavior_obs.append(f"Face not detected for {v}s")
                    elif k == 'multiple_faces_detected' and v > 0:
                        behavior_obs.append(f"Multiple faces detected {v} time(s)")
                    elif k == 'silence_detected' and v > 0:
                        behavior_obs.append(f"Silence detected for {v}s")
            except:
                pass

        # Parse uploaded documents for the view
        uploaded_docs = []
        if candidate and candidate['uploaded_documents']:
            try:
                uploaded_docs = json.loads(candidate['uploaded_documents'])
            except (json.JSONDecodeError, TypeError):
                pass
        # 4. Verification & Trust Computation
        trust_report = {}
        if final_score:
            fs_dict = dict(final_score)
            if fs_dict.get('trust_data'):
                try:
                    trust_report = json.loads(fs_dict['trust_data'])
                except:
                    pass
            elif interview: # Only compute if interview exists (meaning transcript is ready)
                from resume_engine.verification import compute_trust_report
                from resume_engine.github_api import fetch_github_profile
                cand_dict = dict(candidate)
                parsed_data = {
                    'name': cand_dict.get('full_name', ''),
                    'skills': skills,
                    'certifications': extended.get('certifications', []),
                    'links': extended.get('links', {})
                }
                # Fetch real GitHub data using stored username
                gh_username = cand_dict.get('github_username', '') or extended.get('github_username', '')
                gh_data = fetch_github_profile(gh_username) if gh_username else {}
                int_dict = dict(interview)
                stt = int_dict.get('transcript_stt', '')
                try:
                    trust_report = compute_trust_report(parsed_data, gh_data, stt, uploaded_docs)
                    db.execute('UPDATE final_scores SET trust_data = ? WHERE candidate_id = ?',
                               (json.dumps(trust_report), candidate_id))
                    db.commit()
                except Exception as e:
                    import logging
                    logging.getLogger('resume_engine').error(f"Trust computation failed: {e}")
                    trust_report = {}

                
        return render_template('candidate_profile.html', 
                               candidate=candidate, 
                               interview=interview, 
                               final_score=final_score,
                               skills=skills,
                               extended=extended,
                               rank_pos=rank_pos,
                               total_batch=total_batch,
                               percentile=percentile,
                               benchmarks=benchmarks,
                               behavior_obs=behavior_obs,
                               uploaded_docs=uploaded_docs,
                               trust_report=trust_report)

    @app.route('/candidate/<int:candidate_id>/verify', methods=['POST'])
    @login_required
    @role_required('recruiter')
    def verify_candidate(candidate_id):
        import hashlib
        db = get_db()
        user_id = session['user_id']
        recruiter_company_id = session.get('company_id')
        
        candidate = db.execute('SELECT resume_hash, id FROM candidates WHERE id = ? AND company_id = ?', 
                               (candidate_id, recruiter_company_id)).fetchone()
                               
        if not candidate:
            flash("Unauthorized access.")
            return redirect(url_for('recruiter_dashboard'))
            
        interview = db.execute('SELECT interview_hash FROM interviews WHERE candidate_id = ?', (candidate_id,)).fetchone()
        final_score = db.execute('SELECT combined_score FROM final_scores WHERE candidate_id = ?', (candidate_id,)).fetchone()
        
        if not final_score:
            return redirect(url_for('candidate_profile', candidate_id=candidate_id))
            
        import datetime
        timestamp = datetime.datetime.utcnow().isoformat()
        res_hash = candidate['resume_hash'] or ''
        int_hash = interview['interview_hash'] if interview else ''
        trust_score = "82" # Placeholder until deterministic formula is live
        
        raw_string = f"{res_hash}{int_hash}{trust_score}{timestamp}".encode('utf-8')
        verification_hash = hashlib.sha256(raw_string).hexdigest()
        
        db.execute('''
            UPDATE final_scores 
            SET verification_hash = ?, is_verified = 1, verified_at = ? 
            WHERE candidate_id = ?
        ''', (verification_hash, timestamp, candidate_id))
        db.commit()
        
        return redirect(url_for('candidate_profile', candidate_id=candidate_id))

    @app.route('/candidate/<int:candidate_id>/notes', methods=['POST'])
    @login_required
    @role_required('recruiter')
    def candidate_notes(candidate_id):
        db = get_db()
        notes = request.form.get('notes', '').strip()
        db.execute('UPDATE candidates SET recruiter_notes = ? WHERE id = ?', (notes, candidate_id))
        db.commit()
        flash("Private recruiter notes updated.")
        return redirect(url_for('candidate_profile', candidate_id=candidate_id))

    @app.route('/candidate/<int:candidate_id>/decision', methods=['POST'])
    @login_required
    @role_required('recruiter')
    def candidate_decision(candidate_id):
        db = get_db()
        decision = request.form.get('decision', 'UNDER_REVIEW') # SHORTLIST, REJECT, UNDER_REVIEW
        db.execute('UPDATE candidates SET decision_status = ? WHERE id = ?', (decision, candidate_id))
        db.commit()
        
        status_label = decision.replace('_', ' ').title()
        flash(f"Decision updated: Candidate moved to {status_label}.")
        return redirect(url_for('candidate_profile', candidate_id=candidate_id))

    @app.route('/recruiter/compare/<int:id1>/<int:id2>')
    @login_required
    @role_required('recruiter')
    def compare_candidates(id1, id2):
        db = get_db()
        recruiter_company = session.get('company_id')

        def load_candidate_data(cid):
            cand = db.execute(
                'SELECT * FROM candidates WHERE id = ? AND company_id = ?',
                (cid, recruiter_company)
            ).fetchone()
            if not cand:
                return None, None, None, None
            cand = dict(cand)

            interview = db.execute(
                'SELECT * FROM interviews WHERE candidate_id = ? ORDER BY id DESC LIMIT 1', (cid,)
            ).fetchone()
            interview = dict(interview) if interview else {}

            fs = db.execute('SELECT * FROM final_scores WHERE candidate_id = ?', (cid,)).fetchone()
            fs = dict(fs) if fs else {}

            trust_report = {}
            if fs.get('trust_data'):
                try:
                    trust_report = json.loads(fs['trust_data'])
                except Exception:
                    pass

            skills = []
            extended = {}
            if cand.get('extended_data'):
                try:
                    extended = json.loads(cand['extended_data'])
                    skills = extended.get('skills', [])
                except Exception:
                    pass

            return cand, interview, fs, trust_report, skills, extended

        data1 = load_candidate_data(id1)
        data2 = load_candidate_data(id2)

        if not data1[0] or not data2[0]:
            flash("One or both candidates not found.")
            return redirect(url_for('recruiter_dashboard'))

        cand1, int1, fs1, tr1, skills1, ext1 = data1
        cand2, int2, fs2, tr2, skills2, ext2 = data2

        # AI Executive Recommendation via Gemini
        ai_comparison = None
        gemini_key = app.config.get('GEMINI_API_KEY')
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                prompt = f"""You are an expert technical recruiter AI evaluating two candidates objectively.

Candidate A: {cand1.get('full_name', 'Candidate A')}
- Resume Score: {cand1.get('resume_score', 0)}%
- Skills: {', '.join(skills1[:10])}
- Experience: {cand1.get('years_experience', 0)} years
- GitHub Score: {tr1.get('github_authenticity', 0)}
- Trust Score: {tr1.get('overall_score', 0)}
- Interview Score: {fs1.get('combined_score', 0)}

Candidate B: {cand2.get('full_name', 'Candidate B')}
- Resume Score: {cand2.get('resume_score', 0)}%
- Skills: {', '.join(skills2[:10])}
- Experience: {cand2.get('years_experience', 0)} years
- GitHub Score: {tr2.get('github_authenticity', 0)}
- Trust Score: {tr2.get('overall_score', 0)}
- Interview Score: {fs2.get('combined_score', 0)}

Compare these two candidates objectively. Return ONLY a JSON object:
{{
  "stronger_technical": "A or B",
  "stronger_communication": "A or B",
  "lower_risk": "A or B",
  "recommended_hire": "A or B",
  "recommendation_reason": "one sentence explanation",
  "a_strengths": ["strength 1", "strength 2"],
  "b_strengths": ["strength 1", "strength 2"],
  "a_risks": ["risk 1"],
  "b_risks": ["risk 1"]
}}"""
                resp = model.generate_content(prompt)
                text = resp.text
                if '```json' in text:
                    text = text.split('```json')[1].split('```')[0].strip()
                elif '```' in text:
                    text = text.split('```')[1].strip()
                ai_comparison = json.loads(text)
            except Exception as e:
                logging.getLogger('resume_engine').error(f"AI Comparison failed: {e}")

        # Hiring Confidence Score  = Resume(40%) + Interview(35%) + Trust(25%)
        def hiring_confidence(fs, tr):
            r_score = float(fs.get('combined_score', 0) or 0)
            i_score = float(tr.get('behavioral_alignment', {}).get('score', 0) if isinstance(tr.get('behavioral_alignment'), dict) else 0)
            t_score = float(tr.get('overall_score', 0) or 0)
            return round(r_score * 0.40 + i_score * 0.35 + t_score * 0.25)

        hc1 = hiring_confidence(fs1, tr1)
        hc2 = hiring_confidence(fs2, tr2)

        def hire_label(score):
            if score >= 75: return ('🟢 Strong Hire', '#00ff9d')
            if score >= 50: return ('🟡 Consider', '#f7c32e')
            return ('🔴 Risky Hire', '#ff4d4d')

        return render_template('compare_candidates.html',
                               cand1=cand1, cand2=cand2,
                               int1=int1, int2=int2,
                               fs1=fs1, fs2=fs2,
                               tr1=tr1, tr2=tr2,
                               skills1=skills1, skills2=skills2,
                               ai_comparison=ai_comparison,
                               hc1=hc1, hc2=hc2,
                               hire1=hire_label(hc1), hire2=hire_label(hc2))

    app.teardown_appcontext(close_db)


    return app
 
if __name__ == '__main__':
    # Always run init_db to ensure migrations are applied
    init_db()
    
    app = create_app()
    app.run(debug=True)

