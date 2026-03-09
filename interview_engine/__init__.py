from flask import Blueprint

interview_bp = Blueprint('interview', __name__)

from . import routes  # noqa: E402, F401
