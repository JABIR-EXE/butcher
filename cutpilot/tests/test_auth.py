import tempfile
import unittest
from pathlib import Path

import auth
import core


class AccountIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = (auth.DATA_DIR, auth.TENANT_DIR, auth.AUTH_DB)
        auth.DATA_DIR = Path(self.temp.name)
        auth.TENANT_DIR = auth.DATA_DIR / "tenants"
        auth.AUTH_DB = auth.DATA_DIR / "auth.sqlite3"
        auth.init_db()

    def tearDown(self):
        core.clear_active_db_path()
        auth.DATA_DIR, auth.TENANT_DIR, auth.AUTH_DB = self.old
        self.temp.cleanup()

    def create(self, name, email):
        account = auth.create_account(full_name=name, email=email, password="a-strong-test-password-123",
                                      business_name=f"{name}'s Butcher", country="GB", currency="GBP", plan="starter")
        core.set_active_db_path(account["db_path"])
        core.init_db()
        core.update_settings({"business_name": account["business_name"], "currency": "GBP"})
        core.clear_active_db_path()
        auth.mark_email_verified(account["user_id"])
        return account

    def test_password_is_hashed_and_login_works(self):
        account = self.create("Test Owner", "owner@example.test")
        with auth.connect() as con:
            row = con.execute("SELECT password_hash FROM users WHERE id=?", (account["user_id"],)).fetchone()
        self.assertNotIn("a-strong-test-password-123", row["password_hash"])
        self.assertTrue(auth.verify_password("a-strong-test-password-123", row["password_hash"]))
        user = auth.authenticate("OWNER@example.test", "a-strong-test-password-123")
        self.assertEqual(user["organization_id"], account["organization_id"])

    def test_each_business_has_a_separate_database(self):
        first = self.create("First Owner", "first@example.test")
        second = self.create("Second Owner", "second@example.test")
        self.assertNotEqual(first["db_path"], second["db_path"])
        core.set_active_db_path(first["db_path"])
        core.create_product({"name":"Chicken Breast", "sku":"CHK-1", "category":"Chicken", "stock_unit":"kg", "unit_cost":5, "unit_price":9, "opening_stock":10})
        core.clear_active_db_path()
        core.set_active_db_path(second["db_path"])
        self.assertEqual(core.list_products(), [])
        core.create_product({"name":"Beef Steak", "sku":"BEEF-1", "category":"Beef", "stock_unit":"kg", "unit_cost":8, "unit_price":14, "opening_stock":7})
        self.assertEqual([p["name"] for p in core.list_products()], ["Beef Steak"])
        core.clear_active_db_path()
        core.set_active_db_path(first["db_path"])
        self.assertEqual([p["name"] for p in core.list_products()], ["Chicken Breast"])

    def test_sessions_are_opaque_and_expire_by_lookup(self):
        account = self.create("Session Owner", "session@example.test")
        token, _ = auth.create_session(account["user_id"], account["organization_id"])
        session = auth.get_session(token)
        self.assertEqual(session["business_name"], account["business_name"])
        self.assertNotIn(token, str(session))
        auth.delete_session(token)
        self.assertIsNone(auth.get_session(token))

    def test_signup_validation(self):
        with self.assertRaises(ValueError):
            auth.create_account(full_name="A", email="bad", password="short", business_name="Shop")


if __name__ == "__main__":
    unittest.main()
