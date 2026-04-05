"""Login, logout, and password reset routes."""

from __future__ import annotations

import secrets
import smtplib
from email.message import EmailMessage
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .auth_store import (
    consume_reset_token,
    fetch_user_by_email,
    store_reset_token,
)
from .db import get_db
from .login_config import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _send_mail(subject: str, to_email: str, body: str) -> bool:
    server = (current_app.config.get("MAIL_SERVER") or "").strip()
    if not server:
        return False
    port = int(current_app.config.get("MAIL_PORT") or 587)
    use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    user = (current_app.config.get("MAIL_USERNAME") or "").strip()
    password = current_app.config.get("MAIL_PASSWORD") or ""
    sender = (current_app.config.get("MAIL_DEFAULT_SENDER") or user or "noreply@localhost").strip()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)

    try:
        if use_tls:
            with smtplib.SMTP(server, port, timeout=30) as smtp:
                smtp.starttls()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(server, port, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
    except OSError as exc:
        current_app.logger.warning("Could not send email: %s", exc)
        return False
    return True


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        nxt = request.args.get("next") or request.form.get("next") or ""
        db = get_db()
        row = fetch_user_by_email(db, email)
        if row is None or not check_password_hash(row["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", next_url=nxt)
        if not row.get("active"):
            flash("That account is disabled. Ask an administrator.", "error")
            return render_template("auth/login.html", next_url=nxt)
        user = User(
            id=int(row["id"]),
            email=row["email"],
            role_id=int(row["role_id"]),
            role_code=row["role_code"],
            active=True,
        )
        login_user(user, remember=bool(request.form.get("remember")))
        db.commit()
        if nxt and nxt.startswith("/"):
            return redirect(nxt)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", next_url=request.args.get("next") or "")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        db = get_db()
        row = fetch_user_by_email(db, email)
        if row is None:
            flash(
                "If that email is registered, a reset message will be sent shortly.",
                "success",
            )
            return redirect(url_for("auth.forgot_password"))
        raw = secrets.token_urlsafe(32)
        store_reset_token(db, int(row["id"]), raw)
        db.commit()
        base = (request.url_root or "").rstrip("/")
        reset_url = f"{base}{url_for('auth.reset_password', token=raw)}"
        body = (
            "You asked to reset your Treasurer portal password.\n\n"
            f"Open this link (valid for a short time):\n{reset_url}\n\n"
            "If you did not request this, you can ignore this message."
        )
        sent = _send_mail("Reset your Treasurer portal password", email, body)
        if not sent:
            flash(
                "Email is not configured on the server, or sending failed. "
                f"Give this link to the user or open it yourself: {reset_url}",
                "error",
            )
        else:
            flash("Check your email for a reset link.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token = (request.args.get("token") or request.form.get("token") or "").strip()
    if request.method == "GET" and not token:
        flash("Missing reset token.", "error")
        return redirect(url_for("auth.forgot_password"))

    db = get_db()
    if request.method == "POST":
        token = (request.form.get("token") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password_confirm") or ""
        min_pw = int(current_app.config.get("PASSWORD_MIN_LENGTH", 10))
        if len(password) < min_pw:
            flash(f"Password must be at least {min_pw} characters.", "error")
            return render_template("auth/reset_password.html", token=token)
        if password != password2:
            flash("Passwords do not match.", "error")
            return render_template("auth/reset_password.html", token=token)
        uid = consume_reset_token(db, token)
        if uid is None:
            flash("That reset link is invalid or has expired. Request a new one.", "error")
            return redirect(url_for("auth.forgot_password"))
        from .auth_store import update_user_password

        update_user_password(db, uid, generate_password_hash(password))
        db.commit()
        flash("Your password has been updated. You can sign in now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
