import os
from pathlib import Path

from flask import Flask

from .db import (
    close_db,
    ensure_database_parent_path,
    ensure_financial_tables,
    get_db,
    init_app,
    seed_auth_users,
    seed_ledger_categories,
    seed_meeting_schedule,
    seed_virtual_account_balances,
    seed_virtual_accounts,
    seed_virtual_account_category_map,
    _is_postgres_dsn,
    table_exists,
)
from .auth import auth_bp
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
        DATABASE=os.environ.get(
            "TREASURER_DATABASE_URL",
            "postgresql://treasurer:lodge@192.168.1.201:5432/treasurer",
        ),
    )

    if test_config is not None:
        app.config.update(test_config)

    if not _is_postgres_dsn(app.config["DATABASE"]):
        ensure_database_parent_path(Path(app.config["DATABASE"]))
    init_app(app)
    app.teardown_appcontext(close_db)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db = get_db()
        if table_exists(db, "users"):
            seed_auth_users(db)
            ensure_financial_tables(db)
            seed_ledger_categories(db)
            seed_virtual_accounts(db)
            seed_virtual_account_category_map(db)
            if table_exists(db, "reporting_periods"):
                period_count = db.execute("SELECT COUNT(*) AS total FROM reporting_periods").fetchone()["total"]
                if period_count > 0:
                    seed_meeting_schedule(db, reporting_period_id=1)
                    current_period = db.execute(
                        "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if current_period:
                        seed_virtual_account_balances(db, reporting_period_id=current_period["id"])
            db.commit()

    return app
