import os
from pathlib import Path

from flask import Flask

from .db import (
    close_db,
    ensure_database_parent_path,
    ensure_financial_tables,
    default_database_path,
    get_db,
    init_app,
    init_db,
    seed_ledger_categories,
    seed_meeting_schedule,
    seed_virtual_account_balances,
    seed_virtual_accounts,
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
        DATABASE=str(os.environ.get("TREASURER_DATABASE", default_database_path())),
    )

    if test_config is not None:
        app.config.update(test_config)

    ensure_database_parent_path(Path(app.config["DATABASE"]))
    init_app(app)
    app.teardown_appcontext(close_db)

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
            if period_count > 0:
                seed_meeting_schedule(db, reporting_period_id=1)
                current_period = db.execute(
                    "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if current_period:
                    seed_virtual_account_balances(db, reporting_period_id=current_period["id"])
            db.commit()

    return app
