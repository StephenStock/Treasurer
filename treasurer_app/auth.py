from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .db import get_db


auth_bp = Blueprint("auth", __name__)

PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.logout",
    "main.dashboard",
    "main.forms",
    "static",
}


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.get("current_user") is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def _is_safe_next_url(target: str | None) -> bool:
    if not target:
        return False

    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return (
        redirect_url.scheme in {"http", "https"}
        and host_url.netloc == redirect_url.netloc
    )


@auth_bp.before_app_request
def load_current_user():
    user_id = session.get("user_id")
    if not user_id:
        g.current_user = None
        return

    user = get_db().execute(
        "SELECT id, username, full_name, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if user is None:
        session.clear()
        g.current_user = None
        return

    g.current_user = user


@auth_bp.before_app_request
def require_login_for_admin_pages():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return
    if request.endpoint is None:
        return
    if request.endpoint.startswith("static"):
        return
    if g.get("current_user") is None:
        return redirect(url_for("auth.login", next=request.path))


@auth_bp.context_processor
def inject_current_user():
    return {"current_user": g.get("current_user")}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("current_user") is not None:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            """
            SELECT id, username, full_name, password_hash, role
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome, {user['full_name']}.", "success")
            next_page = request.args.get("next")
            if _is_safe_next_url(next_page):
                return redirect(next_page)
            return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
