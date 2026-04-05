"""Flask-Login setup and user model."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING

from flask import current_app, flash, redirect, request, url_for
from flask_login import LoginManager, UserMixin, current_user

from .db import get_db

if TYPE_CHECKING:
    from flask import Response

login_manager = LoginManager()


class User(UserMixin):
    __slots__ = ("id", "email", "role_id", "role_code", "_active")

    def __init__(self, id: int, email: str, role_id: int, role_code: str, active: bool) -> None:
        self.id = id
        self.email = email
        self.role_id = role_id
        self.role_code = role_code
        self._active = bool(active)

    @property
    def is_active(self) -> bool:  # noqa: F401 — Flask-Login
        return self._active


def init_login_manager(app) -> None:
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        from .db import get_db
        from .auth_store import fetch_user_for_login

        db = get_db()
        row = fetch_user_for_login(db, int(user_id))
        if row is None or not row.get("active"):
            return None
        return User(
            id=int(row["id"]),
            email=row["email"],
            role_id=int(row["role_id"]),
            role_code=row["role_code"],
            active=bool(row["active"]),
        )


def user_can(permission_code: str) -> bool:
    """Whether the current user may access this permission (templates and checks)."""
    if current_app.config.get("LOGIN_DISABLED"):
        return True
    if not current_user.is_authenticated:
        return False
    db = get_db()
    from .auth_store import role_has_permission

    return role_has_permission(db, int(current_user.role_id), permission_code)


def permission_required(permission_code: str):
    """Require the signed-in user's role to have this permission (see auth_store.PERMISSION_DEFINITIONS)."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if current_app.config.get("LOGIN_DISABLED"):
                return view_func(*args, **kwargs)
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.url))
            if not user_can(permission_code):
                flash("You don't have access to that area.", "error")
                return redirect(url_for("main.portal"))
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def login_required_unless_disabled(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs) -> Response:
        if current_app.config.get("LOGIN_DISABLED"):
            return view_func(*args, **kwargs)
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))
        return view_func(*args, **kwargs)

    return wrapped
