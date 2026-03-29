import os
from pathlib import Path

from flask import Flask, current_app, request

from .db import (
    close_db,
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
    seed_virtual_account_transfers_from_workbook,
    sync_database_files,
    consolidate_virtual_accounts,
    table_exists,
)
from .routes import main_bp


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY="change-me",
        DATABASE=str(default_database_path()),
        BACKUP_DATABASE=str(os.environ.get("TREASURER_BACKUP_DATABASE", "")),
    )

    if test_config is not None:
        app.config.update(test_config)

    database_path = Path(app.config["DATABASE"])
    backup_database_path = resolve_backup_database_path(database_path)
    app.config["BACKUP_DATABASE"] = str(backup_database_path)
    ensure_database_parent_path(database_path)
    ensure_database_parent_path(backup_database_path)
    try:
        sync_database_files(database_path, backup_database_path)
    except Exception:
        pass
    init_app(app)
    app.teardown_appcontext(close_db)

    @app.after_request
    def mirror_database(response):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
            try:
                db = get_db()
                backup_path = Path(current_app.config.get("BACKUP_DATABASE") or resolve_backup_database_path(Path(current_app.config["DATABASE"])))
                backup_database(db, backup_path)
            except Exception:
                pass
        return response

    app.register_blueprint(main_bp)

    with app.app_context():
        db = get_db()
        if not table_exists(db, "reporting_periods"):
            init_db()
        else:
            ensure_financial_tables(db)
            seed_ledger_categories(db)
            seed_virtual_accounts(db)
            consolidate_virtual_accounts(db)
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
                backup_database(db, Path(app.config["BACKUP_DATABASE"]))
            except Exception:
                pass

    return app
