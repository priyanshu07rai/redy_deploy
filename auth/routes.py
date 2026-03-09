import functools
import bcrypt
import sqlite3
import secrets
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, request, session, flash, g, current_app
from . import auth_bp
from database import get_db


# ─── Decorators ──────────────────────────────────────────────────────────────

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if session.get('user_id') is None:
            return redirect(url_for('auth.login'))
        return view(**kwargs)
    return wrapped_view

def role_required(role):
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            if session.get('role') != role:
                flash(f"Access denied: {role} role required.")
                if session.get('role') == 'employee':
                    return redirect(url_for('employee_dashboard'))
                elif session.get('role') == 'recruiter':
                    return redirect(url_for('recruiter_dashboard'))
                return redirect(url_for('auth.login'))
            return view(**kwargs)
        return wrapped_view
    return decorator


# ─── Email Helper ────────────────────────────────────────────────────────────

def send_otp_email(to_email, otp):
    """Send OTP verification email via SMTP."""
    cfg = current_app.config
    server = cfg.get('MAIL_SERVER', 'smtp.gmail.com')
    port = cfg.get('MAIL_PORT', 587)
    username = cfg.get('MAIL_USERNAME')
    password = cfg.get('MAIL_PASSWORD')
    use_tls = cfg.get('MAIL_USE_TLS', True)

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'AI Hiring Platform — Email Verification'
    msg['From'] = username
    msg['To'] = to_email

    html_body = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#f8fafc;border-radius:12px;">
        <div style="text-align:center;margin-bottom:24px;">
            <h2 style="color:#1e293b;margin:0;">AI Hiring Platform</h2>
            <p style="color:#64748b;margin:8px 0 0;">Email Verification</p>
        </div>
        <div style="background:white;border-radius:8px;padding:32px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
            <p style="color:#334155;font-size:16px;margin:0 0 16px;">Your verification code is:</p>
            <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;font-size:32px;font-weight:700;letter-spacing:8px;padding:16px 24px;border-radius:8px;display:inline-block;">{otp}</div>
            <p style="color:#94a3b8;font-size:14px;margin:24px 0 0;">This code expires in <strong>5 minutes</strong>.</p>
        </div>
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin:24px 0 0;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """
    msg.attach(MIMEText(html_body, 'html'))

    def _send_async():
        try:
            with smtplib.SMTP(server, port, timeout=5) as smtp:
                if use_tls:
                    smtp.starttls()
                smtp.login(username, password)
                smtp.sendmail(username, to_email, msg.as_string())
        except Exception as e:
            pass # Logger might not be available in async thread context safely

    # Run in background to prevent Gunicorn worker timeout on Render
    threading.Thread(target=_send_async).start()
    return True


# ─── Registration (Step 1: Collect data + send OTP) ─────────────────────────

@auth_bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form.get('confirm_password')
        role = 'employee'  # Fixed role for employee signup flow
        
        db = get_db()
        error = None

        if not email:
            error = 'Email is required.'
        elif not password:
            error = 'Password is required.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'

        if error is None:
            existing = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if existing:
                error = f'Email {email} is already registered.'

        if error is None:
            # Generate OTP
            otp = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            expires_at = (datetime.now() + timedelta(minutes=current_app.config.get('OTP_EXPIRY_MINUTES', 5))).isoformat()

            # Clear any previous OTPs for this email
            db.execute('DELETE FROM email_verifications WHERE email = ?', (email,))
            db.execute(
                'INSERT INTO email_verifications (email, otp, expires_at, attempts) VALUES (?, ?, ?, 0)',
                (email, otp, expires_at)
            )
            db.commit()

            # Store pending registration in session
            session['pending_email'] = email
            session['pending_password'] = password
            session['pending_role'] = role
            session['pending_company_id'] = None # Employees select company later

            # Send OTP
            if send_otp_email(email, otp):
                flash('Verification code sent to email.')
                return redirect(url_for('auth.verify_email'))
            else:
                flash('Verification email failed.')

        if error:
            flash(error)

    db = get_db()
    companies = db.execute('SELECT * FROM companies').fetchall()
    return render_template('register.html', companies=companies)


@auth_bp.route('/recruiter/login', methods=('POST',))
def recruiter_login():
    company_code = request.form.get('company_id')
    secret = request.form.get('secret')
    
    db = get_db()
    company = db.execute('SELECT * FROM companies WHERE company_code = ?', (company_code,)).fetchone()
    
    if company and company['recruiter_secret'] == secret:
        session.clear()
        # Use a virtual session ID for fixed recruiter accounts if needed, 
        # or just set the essential session data.
        session['user_id'] = f"recruiter_{company['id']}" 
        session['role'] = 'recruiter'
        session['company_id'] = company['id']
        session['company_name'] = company['company_name']
        
        flash(f"Welcome, recruiter for {company['company_name']}!")
        return redirect(url_for('recruiter_dashboard'))
    
    flash('Invalid Company ID or Secret Password.')
    return redirect(url_for('auth.register'))


# ─── OTP Verification (Step 2: Verify code + create account) ────────────────

@auth_bp.route('/verify-email', methods=('GET', 'POST'))
def verify_email():
    pending_email = session.get('pending_email')
    if not pending_email:
        flash('No pending registration found. Please register first.')
        return redirect(url_for('auth.register'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        db = get_db()

        record = db.execute(
            'SELECT * FROM email_verifications WHERE email = ? ORDER BY id DESC LIMIT 1',
            (pending_email,)
        ).fetchone()

        if not record:
            flash('No verification record found. Please register again.')
            return redirect(url_for('auth.register'))

        max_attempts = current_app.config.get('OTP_MAX_ATTEMPTS', 3)

        # Check attempts
        if record['attempts'] >= max_attempts:
            db.execute('DELETE FROM email_verifications WHERE email = ?', (pending_email,))
            db.commit()
            session.pop('pending_email', None)
            flash('Too many failed attempts. Please register again.')
            return redirect(url_for('auth.register'))

        # Check expiry
        expires_at = datetime.fromisoformat(record['expires_at'])
        if datetime.now() > expires_at:
            db.execute('DELETE FROM email_verifications WHERE email = ?', (pending_email,))
            db.commit()
            flash('OTP has expired. Please request a new one.')
            return render_template('verify_email.html', email=pending_email)

        # Check OTP
        if entered_otp != record['otp']:
            db.execute(
                'UPDATE email_verifications SET attempts = attempts + 1 WHERE id = ?',
                (record['id'],)
            )
            db.commit()
            remaining = max_attempts - record['attempts'] - 1
            flash(f'Invalid OTP. {remaining} attempt(s) remaining.')
            return render_template('verify_email.html', email=pending_email)

        # ── OTP is correct → create the user ─────────────────────────────
        password = session.get('pending_password')
        role = session.get('pending_role')
        company_id = session.get('pending_company_id')

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        try:
            db.execute(
                "INSERT INTO users (email, password_hash, role, company_id, email_verified) VALUES (?, ?, ?, ?, 1)",
                (pending_email, hashed_password, role, company_id)
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash(f'Email {pending_email} is already registered.')
            return redirect(url_for('auth.register'))

        # Clean up
        db.execute('DELETE FROM email_verifications WHERE email = ?', (pending_email,))
        db.commit()

        # Get the new user and log them in
        user = db.execute('SELECT * FROM users WHERE email = ?', (pending_email,)).fetchone()
        session.clear()
        session['user_id'] = user['id']
        session['role'] = user['role']
        session['company_id'] = user['company_id']

        flash('Email verified! Account created successfully.')
        if user['role'] == 'employee':
            return redirect(url_for('employee_dashboard'))
        return redirect(url_for('recruiter_dashboard'))

    return render_template('verify_email.html', email=pending_email)


# ─── Resend OTP (registration flow only) ─────────────────────────────────────

@auth_bp.route('/resend-otp', methods=('POST',))
def resend_otp():
    pending_email = session.get('pending_email')

    if not pending_email:
        flash('No pending verification. Please try again.')
        return redirect(url_for('auth.register'))

    db = get_db()
    otp = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
    expires_at = (datetime.now() + timedelta(minutes=current_app.config.get('OTP_EXPIRY_MINUTES', 5))).isoformat()

    db.execute('DELETE FROM email_verifications WHERE email = ?', (pending_email,))
    db.execute(
        'INSERT INTO email_verifications (email, otp, expires_at, attempts) VALUES (?, ?, ?, 0)',
        (pending_email, otp, expires_at)
    )
    db.commit()

    if send_otp_email(pending_email, otp):
        flash('A new verification code has been sent.')
    else:
        flash('Failed to send email. Please check SMTP settings.')

    return redirect(url_for('auth.verify_email'))


# ─── Login (direct sign-in, no OTP) ──────────────────────────────────────────

@auth_bp.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']
        db = get_db()
        error = None
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

        if user is None:
            error = 'Incorrect email.'
        elif not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            error = 'Incorrect password.'
        elif not user['email_verified']:
            error = 'Email not verified. Please register again.'

        if error is None:
            # Password correct → log in directly
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['company_id'] = user['company_id']

            flash('Login successful!')
            if user['role'] == 'employee':
                return redirect(url_for('employee_dashboard'))
            return redirect(url_for('recruiter_dashboard'))

        if error:
            flash(error)

    return render_template('login.html')


# ─── Logout ──────────────────────────────────────────────────────────────────

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
