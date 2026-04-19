"""
user_auth.py — Lightweight user authentication and persistence for ScorPred.

Implements optional login, signup, and session management.
User data is stored under SCORPRED_DATA_ROOT/user_data/.
"""


import hashlib
import secrets
from datetime import datetime
from flask import Blueprint, request, session, redirect, url_for, render_template, flash, current_app
from db_models import db, User

user_auth_bp = Blueprint("user_auth", __name__)

USER_SESSION_KEY = "user_email"





def _hash_password(password: str, salt: str = None) -> str:
    if not salt:
        salt = secrets.token_hex(16)
    hash_ = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${hash_.hex()}"


def _verify_password(password: str, hashed: str) -> bool:
    try:
        salt, hashval = hashed.split("$")
        return _hash_password(password, salt) == hashed
    except Exception:
        return False


def _load_user(email: str) -> dict | None:
    user = User.query.filter_by(email=email).first()
    if user:
        return user.to_dict()
    return None


def _save_user(user: dict) -> None:
    db_user = User.query.filter_by(email=user["email"]).first()
    if not db_user:
        db_user = User(
            email=user["email"],
            password_hash=user["password_hash"],
            created_at=datetime.fromisoformat(user["created_at"].replace("Z", "")),
            saved_picks=user.get("saved_picks", []),
            history=user.get("history", []),
        )
        db.session.add(db_user)
    else:
        db_user.password_hash = user["password_hash"]
        db_user.saved_picks = user.get("saved_picks", [])
        db_user.history = user.get("history", [])
    db.session.commit()


def current_user() -> dict | None:
    email = session.get(USER_SESSION_KEY)
    if email:
        return _load_user(email)
    return None


def login_required(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Login required to access this page.", "warning")
            return redirect(url_for("user_auth.login", next=request.url))
        return view_func(*args, **kwargs)
    return wrapped


@user_auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))
        user = _load_user(email)
        if user and _verify_password(password, user["password_hash"]):
            session[USER_SESSION_KEY] = email
            session.permanent = remember or True  # Always keep session permanent for now
            flash("Logged in successfully!", "success")
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        flash("Invalid email or password.", "danger")
    return render_template("login.html", user=current_user())


@user_auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Email and password required.", "danger")
            return render_template("signup.html", user=current_user())
        if _load_user(email):
            flash("Account already exists.", "danger")
            return render_template("signup.html", user=current_user())
        user = {
            "email": email,
            "password_hash": _hash_password(password),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "saved_picks": [],
            "history": [],
        }
        _save_user(user)
        session[USER_SESSION_KEY] = email
        flash("Account created and logged in!", "success")
        return redirect(url_for("index"))
    return render_template("signup.html", user=current_user())


@user_auth_bp.route("/logout")
def logout():
    session.pop(USER_SESSION_KEY, None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))


def save_user_pick(pick: dict) -> None:
    user = current_user()
    if not user:
        return
    user.setdefault("saved_picks", []).append(pick)
    user["history"] = user.get("history", [])
    _save_user(user)


def get_user_picks() -> list:
    user = current_user()
    if user:
        return user.get("saved_picks", [])
    return []


def get_user_history() -> list:
    user = current_user()
    if user:
        return user.get("history", [])
    return []
