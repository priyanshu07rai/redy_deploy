"""
Video Manager — Secure Upload & Streaming
──────────────────────────────────────────
Handles video file validation, storage, and authenticated streaming.
No public direct links — all access goes through secured routes.
"""

import os
import uuid
import logging
from datetime import datetime
from flask import send_file, abort

logger = logging.getLogger('interview_engine.video')

# ─── Allowed Extensions ─────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {'webm', 'mp4', 'mkv'}
MAX_VIDEO_SIZE = 200 * 1024 * 1024  # 200 MB


def validate_video(file) -> tuple:
    """
    Validate uploaded video file.

    Args:
        file: werkzeug FileStorage object

    Returns:
        (bool, str): (is_valid, error_message)
    """
    if not file or not file.filename:
        return False, 'No video file provided'

    # Check extension
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f'Invalid file type: .{ext}. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'

    # Check size (read position, check, seek back)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size > MAX_VIDEO_SIZE:
        size_mb = size / (1024 * 1024)
        return False, f'Video too large: {size_mb:.1f}MB. Maximum: {MAX_VIDEO_SIZE // (1024*1024)}MB'

    if size == 0:
        return False, 'Video file is empty'

    return True, ''


def save_video(file, candidate_id: int, upload_folder: str) -> str:
    """
    Save uploaded video to secure folder with unique filename.

    Args:
        file: werkzeug FileStorage object
        candidate_id: ID of the candidate
        upload_folder: base upload directory

    Returns:
        str: saved file path
    """
    # Create interview-specific subfolder
    interview_dir = os.path.join(upload_folder, 'interviews')
    os.makedirs(interview_dir, exist_ok=True)

    # Generate unique filename
    ext = file.filename.rsplit('.', 1)[-1].lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_id = uuid.uuid4().hex[:8]
    filename = f'interview_{candidate_id}_{timestamp}_{unique_id}.{ext}'

    filepath = os.path.join(interview_dir, filename)
    file.save(filepath)

    logger.info(f"  Video saved: {filename} ({os.path.getsize(filepath)} bytes)")
    return filepath


def stream_video(filename: str, upload_folder: str):
    """
    Stream video file for authenticated playback.

    Args:
        filename: video filename
        upload_folder: base upload directory

    Returns:
        Flask send_file response
    """
    interview_dir = os.path.join(upload_folder, 'interviews')
    filepath = os.path.join(interview_dir, filename)

    # Security: prevent directory traversal
    real_dir = os.path.realpath(interview_dir)
    real_file = os.path.realpath(filepath)

    if not real_file.startswith(real_dir):
        logger.warning(f"  Directory traversal attempt: {filename}")
        abort(403)

    if not os.path.exists(filepath):
        logger.warning(f"  Video not found: {filename}")
        abort(404)

    ext = filename.rsplit('.', 1)[-1].lower()
    mime_types = {
        'webm': 'video/webm',
        'mp4': 'video/mp4',
        'mkv': 'video/x-matroska',
    }

    return send_file(
        filepath,
        mimetype=mime_types.get(ext, 'application/octet-stream'),
        as_attachment=False,
    )
