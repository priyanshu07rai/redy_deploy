"""
Interview Engine Routes
───────────────────────
Handles interview flow: start page, video submission, processing pipeline,
results viewing, and secure video streaming.
"""

import os
import json
import logging
from flask import (
    render_template, request, redirect, url_for,
    session, flash, jsonify, current_app
)
from . import interview_bp
from database import get_db
from auth.routes import login_required, role_required

from .integrity_monitor import compute_integrity_index, get_anomaly_breakdown
from .transcript_processor import process_transcript
from .deterministic_scorer import compute_baseline_score, compute_final_answer_score
from .ai_evaluator import evaluate_transcript
from .hashing import generate_interview_hash, verify_hash
from .video_manager import validate_video, save_video, stream_video

logger = logging.getLogger('interview_engine.routes')


# ─── Interview Start Page ────────────────────────────────────────────────────

@interview_bp.route('/start')
@login_required
@role_required('employee')
def start():
    """Render the interview page with webcam, mic, and integrity monitors."""
    return render_template('interview.html')


# ─── Interview Submission ────────────────────────────────────────────────────

@interview_bp.route('/submit', methods=['POST'])
@login_required
@role_required('employee')
def submit():
    """
    Receive recorded video + anomaly flags and run the full processing pipeline.

    Expected form data:
        - video: video file (webm/mp4)
        - anomaly_flags: JSON string of anomaly counters
        - transcript: optional transcript text
    """
    db = get_db()
    user_id = session['user_id']

    # ── Step 1: Get candidate record ─────────────────────────────────────
    candidate = db.execute(
        'SELECT id FROM candidates WHERE user_id = ? ORDER BY id DESC LIMIT 1',
        (user_id,)
    ).fetchone()

    if not candidate:
        return jsonify({'error': 'No candidate profile found. Please upload your resume first.'}), 400

    candidate_id = candidate['id']

    # ── Step 2: Validate and save video ──────────────────────────────────
    video_file = request.files.get('video')
    if not video_file:
        return jsonify({'error': 'No video file received'}), 400

    is_valid, error_msg = validate_video(video_file)
    if not is_valid:
        return jsonify({'error': error_msg}), 400

    upload_folder = current_app.config.get('UPLOAD_FOLDER',
        os.path.join(os.path.dirname(__file__), '..', 'uploads'))
    video_path = save_video(video_file, candidate_id, upload_folder)

    logger.info(f"[Pipeline] Video saved for candidate {candidate_id}")

    # ── Step 3: Parse anomaly flags ──────────────────────────────────────
    anomaly_json = request.form.get('anomaly_flags', '{}')
    try:
        anomaly_flags = json.loads(anomaly_json)
    except json.JSONDecodeError:
        anomaly_flags = {}

    # Ensure all expected keys exist
    default_flags = {
        'tab_switches': 0, 'window_blur': 0, 'no_face_seconds': 0,
        'multiple_faces': 0, 'copy_attempts': 0, 'fullscreen_exits': 0,
    }
    for key, default in default_flags.items():
        anomaly_flags.setdefault(key, default)

    # ── Step 4: Get transcript ───────────────────────────────────────────
    transcript = request.form.get('transcript', '')

    # ── Step 5: Compute Integrity Index (Layer 1 — Deterministic) ────────
    integrity_index = compute_integrity_index(anomaly_flags)
    logger.info(f"[Pipeline] Integrity index: {integrity_index}")

    # ── Step 6: Process transcript metrics ───────────────────────────────
    transcript_metrics = process_transcript(transcript)

    # ── Step 7: Compute deterministic baseline score ─────────────────────
    baseline_answer_score = compute_baseline_score(transcript_metrics)
    logger.info(f"[Pipeline] Baseline answer score: {baseline_answer_score}")

    # ── Step 8: AI Evaluation (Layer 2 — Controlled AI) ──────────────────
    api_url = current_app.config.get('AI_SUMMARY_API_URL', '')
    api_key = current_app.config.get('AI_SUMMARY_API_KEY', '')
    model = current_app.config.get('AI_SUMMARY_MODEL', 'llama-3.3-70b-versatile')

    ai_scores = evaluate_transcript(transcript, api_url, api_key, model)
    ai_answer_score = ai_scores.get('overall_score', 50)
    logger.info(f"[Pipeline] AI answer score: {ai_answer_score}")

    # ── Step 9: Compute final answer score ───────────────────────────────
    final_answer_score = compute_final_answer_score(baseline_answer_score, ai_answer_score)
    logger.info(f"[Pipeline] Final answer score: {final_answer_score}")

    # ── Step 10: Generate tamper-detection hash ──────────────────────────
    interview_hash = generate_interview_hash(
        video_path, transcript, integrity_index, final_answer_score
    )

    # ── Step 11: Store in database ───────────────────────────────────────
    db.execute('''
        INSERT INTO interviews (
            candidate_id, video_path, transcript, anomaly_flags,
            integrity_index, baseline_answer_score, ai_answer_score,
            final_answer_score, interview_hash, confidence_score,
            questions_asked, transcript_stt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        candidate_id, video_path, transcript, json.dumps(anomaly_flags),
        integrity_index, baseline_answer_score, ai_answer_score,
        final_answer_score, interview_hash, ai_scores.get('confidence', 50),
        request.form.get('questions', '[]'), transcript
    ))
    db.commit()

    # Update candidate interview status
    db.execute(
        "UPDATE candidates SET interview_status = 'COMPLETED' WHERE id = ?",
        (candidate_id,)
    )
    db.commit()

    # Get the interview ID
    interview_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

    logger.info(f"[Pipeline] ✓ Interview {interview_id} processed and stored")

    # ── Step 12: Update Final Scores (Combined Intelligence) ─────────────
    # Fetch resume score to compute composite
    res_data = db.execute('SELECT resume_score FROM candidates WHERE id = ?', (candidate_id,)).fetchone()
    resume_score = res_data['resume_score'] or 0
    
    # Combined = 40% Resume + 35% Integrity + 25% Answer Quality
    combined_score = (0.40 * resume_score) + (0.35 * integrity_index) + (0.25 * final_answer_score)
    
    db.execute('''
        INSERT INTO final_scores (candidate_id, combined_score, is_verified)
        VALUES (?, ?, 0)
        ON CONFLICT(candidate_id) DO UPDATE SET combined_score = excluded.combined_score
    ''', (candidate_id, round(combined_score, 2)))
    db.commit()

    return jsonify({
        'success': True,
        'interview_id': interview_id,
        'redirect': url_for('interview.results', interview_id=interview_id),
    })


# ─── Interview Results ───────────────────────────────────────────────────────

@interview_bp.route('/<int:interview_id>/results')
@login_required
def results(interview_id):
    """Render the interview results page with all scores."""
    db = get_db()
    user_id = session['user_id']
    role = session.get('role')

    interview = db.execute(
        'SELECT * FROM interviews WHERE id = ?', (interview_id,)
    ).fetchone()

    if not interview:
        flash('Interview not found.')
        return redirect(url_for('employee_dashboard'))

    # Security: employees can only see their own, recruiters can see all
    if role == 'employee':
        candidate = db.execute(
            'SELECT id FROM candidates WHERE id = ? AND user_id = ?',
            (interview['candidate_id'], user_id)
        ).fetchone()
        if not candidate:
            flash('Access denied.')
            return redirect(url_for('employee_dashboard'))

    # Parse anomaly flags
    anomaly_flags = {}
    if interview['anomaly_flags']:
        try:
            anomaly_flags = json.loads(interview['anomaly_flags'])
        except json.JSONDecodeError:
            anomaly_flags = {}

    anomaly_breakdown = get_anomaly_breakdown(anomaly_flags)

    # Extract video filename for streaming
    video_filename = os.path.basename(interview['video_path']) if interview['video_path'] else None

    # Verify hash integrity
    hash_valid = verify_hash(
        interview['video_path'],
        interview['transcript'],
        interview['integrity_index'],
        interview['final_answer_score'],
        interview['interview_hash']
    ) if interview['interview_hash'] else None

    # Parse questions asked (Defensive for Phase 5 migration)
    questions_asked = []
    try:
        if 'questions_asked' in interview.keys() and interview['questions_asked']:
            questions_asked = json.loads(interview['questions_asked'])
    except (json.JSONDecodeError, AttributeError, IndexError):
        questions_asked = []

    return render_template('interview_results.html',
                           interview=interview,
                           anomaly_flags=anomaly_flags,
                           anomaly_breakdown=anomaly_breakdown,
                           video_filename=video_filename,
                           hash_valid=hash_valid,
                           role=role,
                           questions_asked=questions_asked)


# ─── Secure Video Streaming ──────────────────────────────────────────────────

@interview_bp.route('/stream/<filename>')
@login_required
def stream(filename):
    """Stream interview video through authenticated route."""
    upload_folder = current_app.config.get('UPLOAD_FOLDER',
        os.path.join(os.path.dirname(__file__), '..', 'uploads'))
    return stream_video(filename, upload_folder)


# ─── Interview List (for dashboard) ──────────────────────────────────────────

@interview_bp.route('/list')
@login_required
def interview_list():
    """Return list of interviews for the current user (JSON)."""
    db = get_db()
    user_id = session['user_id']
    role = session.get('role')

    if role == 'recruiter':
        # Recruiters see all interviews
        interviews = db.execute('''
            SELECT i.*, c.full_name as candidate_name
            FROM interviews i
            JOIN candidates c ON i.candidate_id = c.id
            ORDER BY i.created_at DESC
        ''').fetchall()
    else:
        # Employees see only their own
        interviews = db.execute('''
            SELECT i.*, c.full_name as candidate_name
            FROM interviews i
            JOIN candidates c ON i.candidate_id = c.id
            WHERE c.user_id = ?
            ORDER BY i.created_at DESC
        ''', (user_id,)).fetchall()

    result = []
    for iv in interviews:
        result.append({
            'id': iv['id'],
            'candidate_name': iv['candidate_name'] or 'Unknown',
            'integrity_index': iv['integrity_index'],
            'final_answer_score': iv['final_answer_score'],
            'created_at': iv['created_at'],
        })

    return jsonify(result)
