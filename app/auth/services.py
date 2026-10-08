"""Account rules. Validation functions are pure; DB helpers are thin wrappers."""
import re
from functools import wraps
from urllib.parse import urlparse

from flask import abort, g, redirect, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
LOGIN_ERROR = "Invalid username or password."


def validate_registration(username, email, password, confirm):
    """Return {field: message} for every rule broken (empty dict = valid). Uniqueness is checked separately."""
    errors = {}
    if not USERNAME_RE.match(username or ""):
        errors["username"] = "Username must be 3-30 characters: letters, digits and underscore only."
    if len(email or "") > 120 or not EMAIL_RE.match(email or ""):
        errors["email"] = "Enter a valid email address."
    password = password or ""
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors["password"] = "Password must be at least 8 characters and contain a letter and a digit."
    elif password != confirm:
        errors["confirm"] = "Passwords do not match."
    return errors


def is_safe_next(target):
    """Only allow relative paths like '/my-team' (no scheme, host or '//' tricks)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc


def get_user(user_id):
    return db.query(
        "SELECT id, username, email, role, created_at FROM users WHERE id = %s", (user_id,), one=True
    )


def uniqueness_errors(username, email):
    errors = {}
    # utf8mb4_0900_ai_ci collation makes these comparisons case-insensitive
    if db.query("SELECT 1 FROM users WHERE username = %s", (username,), one=True):
        errors["username"] = "That username is already taken."
    if db.query("SELECT 1 FROM users WHERE email = %s", (email,), one=True):
        errors["email"] = "That email is already registered."
    return errors


def create_user(username, email, password, role="user"):
    return db.execute(
        "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        (username, email.lower(), generate_password_hash(password), role),
    )


def authenticate(username, password):
    row = db.query("SELECT id, password_hash FROM users WHERE username = %s", (username or "",), one=True)
    if row and check_password_hash(row["password_hash"], password or ""):
        return row["id"]
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped
