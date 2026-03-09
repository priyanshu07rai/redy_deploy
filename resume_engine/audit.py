"""
Audit Trail System — Append-Only Resume Activity Logging

All resume pipeline actions are logged to the resume_audit_logs table.
This module provides a single entry point: log_audit().

Logged events:
  - resume_upload
  - hash_generated
  - ai_summary_generated
  - field_edit
  - confirmation_submitted
"""

import logging
from database import get_db

logger = logging.getLogger('resume_engine.audit')


def log_audit(user_id: int, action: str, candidate_id: int = None,
              field: str = None, old_value: str = None, new_value: str = None):
    """
    Append an audit log entry. This is INSERT-only (append-only).

    Args:
        user_id:      ID of the user performing the action
        action:       Action type (e.g. 'resume_upload', 'field_edit')
        candidate_id: Optional candidate record ID
        field:        Optional field name that was modified
        old_value:    Optional previous value (truncated for safety)
        new_value:    Optional new value (truncated for safety)
    """
    try:
        # Truncate values to avoid logging sensitive full-text data
        old_trunc = _truncate(old_value) if old_value else None
        new_trunc = _truncate(new_value) if new_value else None

        db = get_db()
        db.execute(
            '''INSERT INTO resume_audit_logs
               (user_id, candidate_id, action, field_modified, old_value, new_value)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (user_id, candidate_id, action, field, old_trunc, new_trunc)
        )
        db.commit()

        logger.info(f"   📋 Audit: [{action}] user={user_id}"
                    f"{f' field={field}' if field else ''}"
                    f"{f' candidate={candidate_id}' if candidate_id else ''}")

    except Exception as e:
        # Audit logging must never crash the main pipeline
        logger.warning(f"   ⚠ Audit log failed: {e}")


def log_field_edits(user_id: int, candidate_id: int,
                    original: dict, edited: dict, fields: list[str]):
    """
    Compare original vs edited data and log each change.

    Args:
        user_id:      User ID
        candidate_id: Candidate record ID
        original:     Original parsed data dict
        edited:       User-edited data dict
        fields:       List of field names to compare
    """
    for field in fields:
        old_val = original.get(field)
        new_val = edited.get(field)

        # Normalize for comparison
        old_str = _normalize_for_compare(old_val)
        new_str = _normalize_for_compare(new_val)

        if old_str != new_str:
            log_audit(
                user_id=user_id,
                action='field_edit',
                candidate_id=candidate_id,
                field=field,
                old_value=old_str,
                new_value=new_str,
            )


def _truncate(value: str, max_len: int = 200) -> str:
    """Truncate a value for safe storage (never log full resume text)."""
    if not value:
        return ''
    s = str(value)
    return s[:max_len] + '...' if len(s) > max_len else s


def _normalize_for_compare(value) -> str:
    """Normalize a value for comparison (handles lists, None, etc.)."""
    if value is None:
        return ''
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return str(value).strip()
