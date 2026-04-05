import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from treasurer_app.auth_routes import auth_bp
from treasurer_app.db import (
    DatabaseHandle,
    ensure_financial_tables,
    init_db,
    meal_booking_apply_catalog_selection,
    meal_booking_create_event,
    meal_booking_get_event_by_token,
    meal_booking_list_events,
    meal_booking_replace_options,
    meal_catalog_list_by_course,
)
from treasurer_app.login_config import init_login_manager, user_can
from treasurer_app.routes import main_bp


class MealBookingsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.db = DatabaseHandle(self.connection, "sqlite")

        project_root = Path(__file__).resolve().parent.parent
        self.app = Flask(
            __name__,
            template_folder=str(project_root / "templates"),
            static_folder=str(project_root / "static"),
        )
        self.app.config.update(
            TESTING=True,
            DATABASE=":memory:",
            SECRET_KEY="test",
            LOGIN_DISABLED=True,
        )
        self.app.register_blueprint(main_bp)
        init_login_manager(self.app)
        self.app.register_blueprint(auth_bp)

        @self.app.context_processor
        def _inject_user_can():
            return {"user_can": user_can}

        self.ctx = self.app.app_context()
        self.ctx.push()

        self.patcher_db = patch("treasurer_app.db.get_db", return_value=self.db)
        self.patcher_routes_db = patch("treasurer_app.routes.get_db", return_value=self.db)
        self.patcher_db.start()
        self.patcher_routes_db.start()

        init_db()
        ensure_financial_tables(self.db)
        self.db.commit()

        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.patcher_routes_db.stop()
        self.patcher_db.stop()
        self.ctx.pop()
        self.connection.close()

    def test_public_meal_booking_without_login(self) -> None:
        event_id, _tok = meal_booking_create_event(
            self.db,
            title="Test dinner",
            meal_date="2026-05-01",
            notes=None,
        )
        meal_booking_replace_options(
            self.db,
            event_id,
            [
                ("starter", "Soup", 0, False, None),
                ("main", "Beef", 0, False, None),
                ("main", "Nut roast", 0, True, None),
                ("dessert", "Cake", 0, False, None),
            ],
        )
        self.db.commit()

        ev = meal_booking_get_event_by_token(
            self.db,
            meal_booking_list_events(self.db)[0]["public_token"],
        )
        assert ev is not None
        token = str(ev["public_token"])

        self.app.config["LOGIN_DISABLED"] = False
        try:
            r = self.client.get(f"/meal-booking/{token}")
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Test dinner", r.data)
        finally:
            self.app.config["LOGIN_DISABLED"] = True

    def test_public_submit_creates_response(self) -> None:
        event_id, _tok = meal_booking_create_event(
            self.db,
            title="Dinner",
            meal_date=None,
            notes=None,
        )
        meal_booking_replace_options(
            self.db,
            event_id,
            [
                ("starter", "A", 0, False, None),
                ("main", "B", 0, False, None),
                ("dessert", "C", 0, False, None),
            ],
        )
        self.db.commit()
        ev = meal_booking_get_event_by_token(self.db, meal_booking_list_events(self.db)[0]["public_token"])
        assert ev is not None
        token = str(ev["public_token"])
        rows = self.db.execute(
            "SELECT id FROM meal_booking_options WHERE event_id = ? ORDER BY id",
            (event_id,),
        ).fetchall()
        self.assertEqual(len(rows), 3)
        ids = [int(r["id"]) for r in rows]

        self.client.post(
            f"/meal-booking/{token}",
            data={
                "respondent_name": "Member One",
                "respondent_email": "",
                "guest_count": "0",
                "m_starter": str(ids[0]),
                "m_main": str(ids[1]),
                "m_dessert": str(ids[2]),
            },
        )
        n = self.db.execute(
            "SELECT COUNT(*) AS n FROM meal_booking_responses WHERE event_id = ?",
            (event_id,),
        ).fetchone()["n"]
        self.assertEqual(int(n), 1)

    def test_apply_catalog_to_meeting_snapshots_prices(self) -> None:
        event_id, _tok = meal_booking_create_event(
            self.db,
            title="Catalog test",
            meal_date="2026-06-01",
            notes=None,
        )
        cat = meal_catalog_list_by_course(self.db)
        starter_ids = [int(o["id"]) for o in cat["starter"][:1]]
        main_ids = [int(o["id"]) for o in cat["main"][:1]]
        dessert_ids = [int(o["id"]) for o in cat["dessert"][:1]]
        self.assertTrue(starter_ids and main_ids and dessert_ids)
        meal_booking_apply_catalog_selection(
            self.db,
            event_id,
            starter_ids + main_ids + dessert_ids,
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT price_pence FROM meal_booking_options WHERE event_id = ? AND course = 'starter' LIMIT 1",
            (event_id,),
        ).fetchone()
        self.assertIsNotNone(row)

    def test_delete_upcoming_meal_booking_from_list(self) -> None:
        event_id, _tok = meal_booking_create_event(
            self.db,
            title="Future dinner",
            meal_date="2030-06-01",
            notes=None,
        )
        self.db.commit()
        r = self.client.post(
            "/meal-bookings",
            data={"action": "delete_event", "event_id": str(event_id)},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        n = self.db.execute(
            "SELECT COUNT(*) AS n FROM meal_booking_events WHERE id = ?",
            (event_id,),
        ).fetchone()["n"]
        self.assertEqual(int(n), 0)

    def test_delete_past_meal_booking_from_list_blocked(self) -> None:
        event_id, _tok = meal_booking_create_event(
            self.db,
            title="Past dinner",
            meal_date="2010-01-01",
            notes=None,
        )
        self.db.commit()
        r = self.client.post(
            "/meal-bookings",
            data={"action": "delete_event", "event_id": str(event_id)},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        n = self.db.execute(
            "SELECT COUNT(*) AS n FROM meal_booking_events WHERE id = ?",
            (event_id,),
        ).fetchone()["n"]
        self.assertEqual(int(n), 1)


if __name__ == "__main__":
    unittest.main()
