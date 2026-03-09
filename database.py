import sqlite3
from flask import g
from config import Config

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            Config.DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db

def close_db(e=None):
    db = g.pop('db', None)

    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(Config.DATABASE)
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                company_id INTEGER,
                email_verified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            );
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS email_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                otp TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                attempts INTEGER DEFAULT 0
            );
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                company_code TEXT UNIQUE NOT NULL,
                recruiter_secret TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                resume_path TEXT NOT NULL,
                resume_hash TEXT NOT NULL,
                resume_version INTEGER DEFAULT 1,
                uploaded_documents TEXT,
                full_name TEXT,
                email_extracted TEXT,
                phone TEXT,
                location TEXT,
                skills TEXT,
                skill_count INTEGER DEFAULT 0,
                years_experience REAL DEFAULT 0,
                degree TEXT,
                university TEXT,
                github_username TEXT,
                github_score REAL DEFAULT 0,
                identity_score REAL DEFAULT 0,
                fraud_probability REAL DEFAULT 0,
                resume_score REAL DEFAULT 0,
                extended_data TEXT,
                ai_generated_summary TEXT,
                user_edited_summary TEXT,
                applied_role TEXT,
                recruiter_notes TEXT,
                decision_status TEXT DEFAULT 'UNDER_REVIEW',
                status TEXT DEFAULT 'confirmed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (company_id) REFERENCES companies(id)
            );
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS resume_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                candidate_id INTEGER,
                action TEXT NOT NULL,
                field_modified TEXT,
                old_value TEXT,
                new_value TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # ── Phase 3: Interviews Table ────────────────────────────────────
        db.execute('''
            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                video_path TEXT NOT NULL,
                transcript TEXT,
                anomaly_flags TEXT,
                integrity_index REAL,
                baseline_answer_score REAL,
                ai_answer_score REAL,
                final_answer_score REAL,
                interview_hash TEXT,
                confidence_score REAL DEFAULT 0,
                questions_asked TEXT,
                transcript_stt TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            );
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS final_scores (
                candidate_id INTEGER PRIMARY KEY,
                combined_score REAL,
                rank_position INTEGER,
                verification_hash TEXT,
                is_verified INTEGER DEFAULT 0,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            );
        ''')

        # ── Safe migrations for existing databases ───────────────────────
        # Add new columns if they don't exist (SQLite-safe)
        try:
            db.execute('ALTER TABLE candidates ADD COLUMN ai_generated_summary TEXT')
        except sqlite3.OperationalError:
            pass 
        try:
            db.execute('ALTER TABLE candidates ADD COLUMN user_edited_summary TEXT')
        except sqlite3.OperationalError:
            pass 
        try:
            db.execute("ALTER TABLE candidates ADD COLUMN interview_status TEXT DEFAULT 'NOT_STARTED'")
        except sqlite3.OperationalError:
            pass 
        try:
            db.execute('ALTER TABLE candidates ADD COLUMN uploaded_documents TEXT')
        except sqlite3.OperationalError:
            pass 

        # Phase 5: Interview enhancements
        try:
            db.execute('ALTER TABLE interviews ADD COLUMN confidence_score REAL DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE interviews ADD COLUMN questions_asked TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            db.execute('ALTER TABLE interviews ADD COLUMN transcript_stt TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('ALTER TABLE users ADD COLUMN company_id INTEGER')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('ALTER TABLE candidates ADD COLUMN company_id INTEGER')
        except sqlite3.OperationalError:
            pass
            
        try:
            db.execute('ALTER TABLE candidates ADD COLUMN applied_role TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('ALTER TABLE final_scores ADD COLUMN verified_at TEXT')
        except sqlite3.OperationalError:
            pass
            
        try:
            db.execute('ALTER TABLE final_scores ADD COLUMN trust_data TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute('ALTER TABLE candidates ADD COLUMN recruiter_notes TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            db.execute("ALTER TABLE candidates ADD COLUMN decision_status TEXT DEFAULT 'UNDER_REVIEW'")
        except sqlite3.OperationalError:
            pass

        # Seed default companies
        c1 = db.execute('SELECT 1 FROM companies WHERE company_code = ?', ('C1',)).fetchone()
        if not c1:
            db.execute(
                'INSERT INTO companies (company_name, company_code, recruiter_secret) VALUES (?, ?, ?)',
                ('Company1', 'C1', '123')
            )
        else:
            # Ensure it has the correct secret if it exists but was seeded differently before
            db.execute('UPDATE companies SET recruiter_secret = ? WHERE company_code = ?', ('123', 'C1'))
        
        c_secure = db.execute('SELECT 1 FROM companies WHERE company_code = ?', ('C1-SECURE-2026',)).fetchone()
        if not c_secure:
            db.execute(
                'INSERT INTO companies (company_name, company_code, recruiter_secret) VALUES (?, ?, ?)',
                ('Global Secure', 'C1-SECURE-2026', 'abc')
            )
        else:
            db.execute('UPDATE companies SET recruiter_secret = ? WHERE company_code = ?', ('abc', 'C1-SECURE-2026'))

    db.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized with users + email_verifications + candidates + resume_audit_logs tables.")
