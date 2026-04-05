import os
import threading
from pathlib import Path

from flask import Flask, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash

from .auth_routes import auth_bp
from .backup_mirror_health import clear_failure as _clear_backup_mirror_failure
from .backup_mirror_health import record_failure as _record_backup_mirror_failure
from .db import (
    APP_RUNTIME_LOCK_HEARTBEAT_SECONDS,
    APP_RUNTIME_LOCK_NAME,
    close_db,
    claim_runtime_lock,
    ensure_database_parent_path,
    ensure_financial_tables,
    default_database_path,
    resolve_backup_database_path,
    get_db,
    init_app,
    init_db,
    seed_ledger_categories,
    seed_meeting_schedule,
    seed_virtual_account_balances,
    seed_virtual_accounts,
    seed_bank_ledger,
    seed_cashbook_from_workbook,
    seed_member_prepayments_from_workbook,
    backup_database,
    runtime_lock_identity,
    restore_database_from_backup,
    seed_virtual_account_transfers_from_workbook,
    sync_database_files,
    consolidate_virtual_accounts,
    remove_legacy_visitor_member,
    table_exists,
)
from .login_config import init_login_manager, user_can
from .password_policy import default_portal_initial_password, min_password_length_from_environ
from .routes import main_bp

# Whole POST body limit for bank CSV uploads and Settings database upload (multipart total).
MAX_BANK_IMPORT_REQUEST_BYTES = 128 * 1024 * 1024


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    # Load repo-root .env into os.environ so local runs (not only Docker) see TREASURER_* vars.
    # override=False: real environment variables win over the file.
    try:
        from dotenv import load_dotenv

        load_dotenv(project_root / ".env", override=False)
    except ImportError:
        pass

    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "change-me"),
        DATABASE=str(default_database_path()),
        BACKUP_DATABASE=str(os.environ.get("TREASURER_BACKUP_DATABASE", "")),
        RUNTIME_LOCK_ENABLED=os.environ.get("TREASURER_RUNTIME_LOCK", "").strip().lower() in {"1", "true", "yes", "on"},
        MAX_CONTENT_LENGTH=MAX_BANK_IMPORT_REQUEST_BYTES,
        LOGIN_DISABLED=os.environ.get("TREASURER_LOGIN_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        MAIL_SERVER=os.environ.get("MAIL_SERVER", "").strip(),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", "587") or 587),
        MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"},
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME", "").strip(),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", ""),
        MAIL_DEFAULT_SENDER=os.environ.get("MAIL_DEFAULT_SENDER", "").strip(),
        PASSWORD_MIN_LENGTH=min_password_length_from_environ(),
    )

    runtime_identity = runtime_lock_identity()
    app.config.update(
        RUNTIME_LOCK_NAME=APP_RUNTIME_LOCK_NAME,
        RUNTIME_LOCK_TOKEN=runtime_identity["session_token"],
        RUNTIME_LOCK_OWNER=runtime_identity["owner_name"],
        RUNTIME_LOCK_MACHINE=runtime_identity["machine_name"],
        RUNTIME_LOCK_PROCESS_ID=runtime_identity["process_id"],
        RUNTIME_LOCK_BLOCKED=False,
        RUNTIME_LOCK_HOLDER=None,
        RUNTIME_LOCK_THREAD_STARTED=False,
        RUNTIME_LOCK_THREAD_LOCK=threading.Lock(),
        RUNTIME_LOCK_STOP_EVENT=threading.Event(),
    )

    if test_config is not None:
        app.config.update(test_config)

    app.config.setdefault("BACKUP_LAST_ERROR", None)
    app.config.setdefault("BACKUP_LAST_ERROR_AT", None)

    database_path = Path(app.config["DATABASE"])
    backup_database_path = resolve_backup_database_path(database_path)
    app.config["BACKUP_DATABASE"] = str(backup_database_path)
    ensure_database_parent_path(database_path)
    ensure_database_parent_path(backup_database_path)
    try:
        if database_path.exists():
            if not backup_database_path.exists():
                sync_database_files(database_path, backup_database_path)
        elif backup_database_path.exists():
            restore_database_from_backup(database_path, backup_database_path)
    except Exception as exc:
        _record_backup_mirror_failure(app, exc, detail="Startup database sync with backup failed.")
    init_app(app)
    app.teardown_appcontext(close_db)
    init_login_manager(app)

    @app.context_processor
    def _inject_global_template_context():
        from .db import get_db, table_exists, virtual_account_report

        try:
            db = get_db()
            nav = virtual_account_report(db) if table_exists(db, "virtual_accounts") else []
        except Exception:
            nav = []
        return {
            "balance_nav_accounts": nav,
            "backup_mirror_error": current_app.config.get("BACKUP_LAST_ERROR"),
            "backup_mirror_error_at": current_app.config.get("BACKUP_LAST_ERROR_AT"),
        }

    @app.context_processor
    def _inject_permission_helpers():
        min_pw = int(app.config.get("PASSWORD_MIN_LENGTH", 8))
        return {
            "user_can": user_can,
            "min_password_length": min_pw,
            "default_portal_initial_password": default_portal_initial_password(min_pw),
        }

    @app.before_request
    def enforce_runtime_lock():
        if not current_app.config.get("RUNTIME_LOCK_ENABLED", False):
            return None

        if request.endpoint == "static":
            return None
        if (request.path or "") == "/healthz":
            return None

        db = get_db()
        acquired, holder = claim_runtime_lock(
            db,
            lock_name=current_app.config["RUNTIME_LOCK_NAME"],
            owner_name=current_app.config["RUNTIME_LOCK_OWNER"],
            machine_name=current_app.config["RUNTIME_LOCK_MACHINE"],
            process_id=current_app.config["RUNTIME_LOCK_PROCESS_ID"],
            session_token=current_app.config["RUNTIME_LOCK_TOKEN"],
        )
        if not acquired:
            current_app.config["RUNTIME_LOCK_BLOCKED"] = True
            current_app.config["RUNTIME_LOCK_HOLDER"] = dict(holder) if holder is not None else None
            return (
                render_template(
                    "locked.html",
                    lock_holder=holder,
                ),
                423,
            )

        current_app.config["RUNTIME_LOCK_BLOCKED"] = False
        current_app.config["RUNTIME_LOCK_HOLDER"] = dict(holder) if holder is not None else None
        db.commit()

        if not current_app.config["RUNTIME_LOCK_THREAD_STARTED"]:
            with current_app.config["RUNTIME_LOCK_THREAD_LOCK"]:
                if not current_app.config["RUNTIME_LOCK_THREAD_STARTED"]:
                    current_app.config["RUNTIME_LOCK_THREAD_STARTED"] = True

                    def _runtime_lock_heartbeat() -> None:
                        while not app.config["RUNTIME_LOCK_STOP_EVENT"].wait(APP_RUNTIME_LOCK_HEARTBEAT_SECONDS):
                            try:
                                with app.app_context():
                                    heartbeat_db = get_db()
                                    heartbeat_acquired, heartbeat_holder = claim_runtime_lock(
                                        heartbeat_db,
                                        lock_name=app.config["RUNTIME_LOCK_NAME"],
                                        owner_name=app.config["RUNTIME_LOCK_OWNER"],
                                        machine_name=app.config["RUNTIME_LOCK_MACHINE"],
                                        process_id=app.config["RUNTIME_LOCK_PROCESS_ID"],
                                        session_token=app.config["RUNTIME_LOCK_TOKEN"],
                                    )
                                    app.config["RUNTIME_LOCK_BLOCKED"] = not heartbeat_acquired
                                    app.config["RUNTIME_LOCK_HOLDER"] = (
                                        dict(heartbeat_holder) if heartbeat_holder is not None else None
                                    )
                                    heartbeat_db.commit()
                            except Exception:
                                break

                    threading.Thread(target=_runtime_lock_heartbeat, name="runtime-lock-heartbeat", daemon=True).start()
        return None

    @app.before_request
    def require_login():
        if current_app.config.get("LOGIN_DISABLED"):
            return None
        if not request.endpoint:
            return None
        if request.endpoint == "static":
            return None
        if request.blueprint == "auth":
            return None
        if request.endpoint == "main.healthz":
            return None
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))
        return None

    @app.after_request
    def mirror_database(response):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
            try:
                db = get_db()
                primary_path = Path(current_app.config["DATABASE"])
                backup_path = Path(current_app.config.get("BACKUP_DATABASE") or resolve_backup_database_path(primary_path))
                backup_database(db, backup_path, primary_path=primary_path)
                _clear_backup_mirror_failure(current_app)
            except Exception as exc:
                _record_backup_mirror_failure(
                    current_app,
                    exc,
                    detail="Mirrored backup could not be written after your last save.",
                )
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def request_entity_too_large(_e):
        flash(
            f"That upload is too large (about {MAX_BANK_IMPORT_REQUEST_BYTES // (1024 * 1024)} MB max per request). "
            "Typical causes: a large bank CSV import or a full database file upload from Settings.",
            "error",
        )
        if (request.path or "").startswith("/bank"):
            return redirect(url_for("main.bank"))
        return redirect(url_for("main.dashboard"))

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)

    with app.app_context():
        db = get_db()
        if not table_exists(db, "reporting_periods"):
            init_db()
        else:
            ensure_financial_tables(db)
            seed_ledger_categories(db)
            seed_virtual_accounts(db)
            consolidate_virtual_accounts(db)
            remove_legacy_visitor_member(db)
            period_count = db.execute("SELECT COUNT(*) AS total FROM reporting_periods").fetchone()["total"]
            current_period = None
            if period_count > 0:
                seed_meeting_schedule(db, reporting_period_id=1)
                current_period = db.execute(
                    "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if current_period:
                seed_virtual_account_balances(db, reporting_period_id=current_period["id"])
                seed_bank_ledger(db, reporting_period_id=current_period["id"])
                seed_cashbook_from_workbook(db, reporting_period_id=current_period["id"])
                seed_member_prepayments_from_workbook(db, reporting_period_id=current_period["id"])
                seed_virtual_account_transfers_from_workbook(db, reporting_period_id=current_period["id"])
            db.commit()
            try:
                backup_database(db, Path(app.config["BACKUP_DATABASE"]), primary_path=database_path)
                _clear_backup_mirror_failure(app)
            except Exception as exc:
                _record_backup_mirror_failure(app, exc, detail="Initial backup after schema check failed.")

            if not app.config.get("TESTING"):
                from .auth_store import count_users, create_user_row, fetch_user_by_email

                bootstrap_email = os.environ.get("TREASURER_BOOTSTRAP_ADMIN_EMAIL", "").strip()
                bootstrap_password = os.environ.get("TREASURER_BOOTSTRAP_ADMIN_PASSWORD", "")
                min_pw = int(app.config.get("PASSWORD_MIN_LENGTH", 8))
                if bootstrap_email and "@" in bootstrap_email and len(bootstrap_password) >= min_pw and count_users(db) == 0:
                    role_row = db.execute("SELECT id FROM roles WHERE code = 'ADMIN'").fetchone()
                    if role_row and fetch_user_by_email(db, bootstrap_email) is None:
                        create_user_row(
                            db,
                            bootstrap_email,
                            generate_password_hash(bootstrap_password),
                            int(role_row["id"]),
                        )
                        db.commit()

    return app
