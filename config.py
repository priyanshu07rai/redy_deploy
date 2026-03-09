import os
from dotenv import load_dotenv

load_dotenv()  # loads .env file

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    DATABASE = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'database.sqlite')

    # ─── SMTP / Email Settings ───────────────────────────────────────────
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or 'q2494301@gmail.com'
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or 'ohbjxpesgxfmwpfa'

    # ─── OTP Settings ────────────────────────────────────────────────────
    OTP_EXPIRY_MINUTES = 5
    OTP_MAX_ATTEMPTS = 3

    # ─── Resume Upload Settings ──────────────────────────────────────────
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads', 'resumes')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024   # 16 MB
    ALLOWED_EXTENSIONS = {'pdf'}

    # ─── Interview Engine Settings ───────────────────────────────────────
    INTERVIEW_UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads', 'interviews')
    MAX_VIDEO_SIZE = 200 * 1024 * 1024  # 200 MB
    ALLOWED_VIDEO_EXTENSIONS = {'webm', 'mp4', 'mkv'}

    # ─── Skill Keywords (for deterministic extraction) ───────────────────
    SKILL_KEYWORDS = [
        'python', 'java', 'javascript', 'typescript', 'c++', 'c#', 'c',
        'go', 'rust', 'ruby', 'php', 'swift', 'kotlin', 'scala', 'r',
        'sql', 'nosql', 'mongodb', 'postgresql', 'mysql', 'sqlite', 'redis',
        'html', 'css', 'react', 'angular', 'vue', 'next.js', 'node.js',
        'express', 'django', 'flask', 'fastapi', 'spring', 'spring boot',
        'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'terraform',
        'git', 'github', 'gitlab', 'ci/cd', 'jenkins',
        'machine learning', 'deep learning', 'nlp', 'computer vision',
        'tensorflow', 'pytorch', 'scikit-learn', 'pandas', 'numpy',
        'data science', 'data analysis', 'data engineering',
        'rest api', 'graphql', 'microservices', 'agile', 'scrum',
        'linux', 'bash', 'powershell', 'selenium', 'pytest',
        'figma', 'adobe', 'photoshop', 'illustrator',
        'blockchain', 'solidity', 'web3',
    ]

    # ─── AI Summary Settings ─────────────────────────────────────────────
    AI_SUMMARY_ENABLED = True
    AI_SUMMARY_API_URL = os.environ.get('AI_SUMMARY_API_URL') or 'https://api.groq.com/openai/v1/chat/completions'
    AI_SUMMARY_API_KEY = os.environ.get('GROQ_API_KEY') or ''
    AI_SUMMARY_MODEL = os.environ.get('AI_SUMMARY_MODEL') or 'llama-3.3-70b-versatile'

    # ─── Verification & Trust Settings ───────────────────────────────────
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN') or ''
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or ''
