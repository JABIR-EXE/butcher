import csv
import hashlib
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import core


class CutPilotCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = core.DB_PATH
        core.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        core.init_db()

    def tearDown(self):
        core.DB_PATH = self.old_path
        self.temp.cleanup()

    def product(self, **overrides):
        payload = {
            "name": "Chicken Breast", "sku": "CHK-TEST", "category": "Poultry",
            "stock_unit": "kg", "purchase_unit": "carton", "conversion_factor": 10,
            "min_stock": 5, "pack_size": 1, "shelf_life_days": 3,
            "unit_cost": 4.5, "unit_price": 12, "opening_stock": 25,
        }
        payload.update(overrides)
        return core.create_product(payload)

    def test_create_product_and_stock_ledger(self):
        p = self.product()
        self.assertEqual(p["on_hand"], 25)
        with core.connect() as con:
            batch = con.execute("SELECT expiry_date FROM stock_batches WHERE product_id=? ORDER BY id LIMIT 1", (p["id"],)).fetchone()
        self.assertEqual(batch["expiry_date"], (core.today()+timedelta(days=3)).isoformat())
        moves = core.get_movements()
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["movement_type"], "opening_stock")
        core.adjust_stock({"product_id": p["id"], "quantity": 5, "action": "receive", "note": "Delivery"})
        updated = next(x for x in core.list_products() if x["id"] == p["id"])
        self.assertEqual(updated["on_hand"], 30)

    def test_csv_preview_and_import(self):
        self.product(opening_stock=0)
        content = b"date,product,sku,quantity,unit,unit_price,total,sale_id\n2026-10-01,Chicken Breast,CHK-TEST,2.5,kg,12,30,S-100\n"
        preview = core.parse_sales_file("sales.csv", content)
        self.assertEqual(preview["row_count"], 1)
        result = core.import_sales("sales.csv", hashlib.sha256(content).hexdigest(), preview["rows"], False)
        self.assertEqual(result["imported"], 1)
        analytics = core.get_analytics()
        # The test date is outside the current 7-day window, but the all-time sales table has the row.
        with core.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "already been imported"):
            core.import_sales("sales.csv", hashlib.sha256(content).hexdigest(), preview["rows"], False)

    def test_excel_preview(self):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Date", "Product", "SKU", "Quantity", "Unit", "Unit Price"])
        ws.append([date(2026, 10, 1), "Chicken Breast", "CHK-TEST", 1.25, "kg", 11.5])
        buff = io.BytesIO(); wb.save(buff)
        parsed = core.parse_sales_file("sales.xlsx", buff.getvalue())
        self.assertEqual(parsed["rows"][0]["date"], "2026-10-01")
        self.assertAlmostEqual(parsed["rows"][0]["total"], 14.375)

    def test_import_stock_deduction_is_atomic_on_insufficient_stock(self):
        p = self.product(opening_stock=1)
        rows = [{"date": "2026-10-01", "product": p["name"], "sku": p["sku"], "quantity": 2, "unit": "kg", "unit_price": 12, "total": 24, "sale_id": "SALE-X", "source_row": 2}]
        result = core.import_sales("recent.csv", "hash-stock-test", rows, True)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(len(result["errors"]), 1)
        with core.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        updated = next(x for x in core.list_products() if x["id"] == p["id"])
        self.assertEqual(updated["on_hand"], 1)

    def test_forecast_recommendation_pack_rounding_and_order_receipt(self):
        p = self.product(opening_stock=5, pack_size=10, min_stock=5)
        supplier = core.create_supplier({"name": "Farm Supply", "lead_time_days": 2})
        core.link_supplier_product({"supplier_id": supplier["id"], "product_id": p["id"], "unit_cost": 4.5, "lead_time_days": 2})
        # Add 56 days of known demand, with non-zero sales every day.
        end = core.today() - timedelta(days=1)
        with core.connect() as con:
            for offset in range(55, -1, -1):
                d = end - timedelta(days=offset)
                sale_key = hashlib.sha256(f"forecast-{d}-{offset}".encode()).hexdigest()
                con.execute("INSERT INTO sales(product_id,sold_at,quantity,unit_price,total,row_key) VALUES (?,?,?,?,?,?)", (p["id"], d.isoformat(), 3.0, 12.0, 36.0, sale_key))
        run = core.run_forecasts(14)
        self.assertTrue(run["forecasts"][0]["forecast_total"] > 0)
        recs = core.get_recommendations()
        rec = next(x for x in recs if x["product_id"] == p["id"])
        self.assertGreater(rec["recommended_quantity"], 0)
        self.assertAlmostEqual(rec["recommended_quantity"] % 10, 0, places=6)
        self.assertAlmostEqual(rec["purchase_quantity"] * 10, rec["recommended_quantity"], places=6)
        order = core.create_purchase_order({"supplier_id": supplier["id"], "items": [{"product_id": p["id"], "quantity": 20, "unit_cost": 4.5}]})
        approved = core.update_purchase_order_status(order["id"], "approve")
        self.assertEqual(approved["status"], "approved")
        received = core.update_purchase_order_status(order["id"], "receive", {"expiry_date": (core.today()+timedelta(days=5)).isoformat()})
        self.assertEqual(received["status"], "received")
        self.assertTrue(received["expected_delivery"])
        exported = core.export_purchase_order_csv(order["id"])
        self.assertIn("purchase_quantity", exported.splitlines()[0])
        self.assertIn(",2.0,carton,20.0,kg,", exported)
        updated = next(x for x in core.list_products() if x["id"] == p["id"])
        self.assertEqual(updated["on_hand"], 25)

    def test_partial_purchase_order_receipt_tracks_remaining_incoming(self):
        p = self.product(opening_stock=5)
        supplier = core.create_supplier({"name": "Partial Supply", "lead_time_days": 4})
        order = core.create_purchase_order({"supplier_id": supplier["id"], "items": [{"product_id": p["id"], "quantity": 20, "unit_cost": 4.5}]})
        item = order["items"][0]
        approved = core.update_purchase_order_status(order["id"], "approve")
        partial = core.update_purchase_order_status(order["id"], "receive", {"received_quantities": {str(item["id"]): 5}})
        self.assertEqual(partial["status"], "partially_received")
        updated = next(x for x in core.list_products() if x["id"] == p["id"])
        self.assertEqual(updated["on_hand"], 10)
        rec = next(x for x in core.get_recommendations() if x["product_id"] == p["id"])
        self.assertEqual(rec["incoming"], 15)
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            core.update_purchase_order_status(order["id"], "receive", {"received_quantities": {str(item["id"]): 0}})

    def test_settings_validate_timezone_and_forecast_ranges(self):
        updated = core.update_settings({"business_name": "North Market Butchers", "currency": "GBP", "business_timezone": "Europe/London", "review_period_days": 5, "forecast_horizon_days": 21})
        self.assertEqual(updated["business_timezone"], "Europe/London")
        self.assertEqual(updated["currency"], "GBP")
        with self.assertRaisesRegex(ValueError, "timezone"):
            core.update_settings({"business_timezone": "Not/A_Real_Zone"})
        with self.assertRaisesRegex(ValueError, "between 1 and 30"):
            core.update_settings({"review_period_days": 0})

    def test_waste_reduces_stock_and_is_recorded(self):
        p = self.product(opening_stock=10)
        record = core.record_waste({"product_id": p["id"], "quantity": 2.5, "reason": "Expired"})
        self.assertEqual(record["quantity"], 2.5)
        updated = next(x for x in core.list_products() if x["id"] == p["id"])
        self.assertEqual(updated["on_hand"], 7.5)
        self.assertEqual(len(core.get_waste()), 1)

    def test_product_csv_preview_import_and_preserve_existing_stock(self):
        product_csv = b"Product Description,Item Code,Department,Unit,Cost Price,Retail Price,Current Stock,Reorder Level\nChicken Breast,CHK-NEW,Poultry,kg,7.2,12.5,24,8\n"
        preview = core.parse_product_file("catalog.csv", product_csv)
        self.assertEqual(preview["row_count"], 1)
        self.assertEqual(preview["mapping"]["name"], "Product Description")
        result = core.import_products(preview["rows"])
        self.assertEqual(result["created"], 1)
        created = next(p for p in core.list_products() if p["sku"] == "CHK-NEW")
        self.assertEqual(created["on_hand"], 24)
        self.assertAlmostEqual(created["unit_cost"], 7.2)
        # A catalog refresh updates commercial fields but does not reset live inventory.
        update_csv = b"name,sku,category,stock_unit,unit_cost,unit_price,opening_stock\nChicken Breast,CHK-NEW,Poultry,kg,8,14,100\n"
        update_preview = core.parse_product_file("catalog-update.csv", update_csv)
        updated = core.import_products(update_preview["rows"])
        self.assertEqual(updated["updated"], 1)
        created = next(p for p in core.list_products() if p["sku"] == "CHK-NEW")
        self.assertEqual(created["on_hand"], 24)
        self.assertAlmostEqual(created["unit_cost"], 8.0)

    def test_product_xml_preview(self):
        xml = b"""<?xml version='1.0'?><products><product><name>Ground Beef</name><sku>BEEF-X</sku><category>Beef</category><stock_unit>kg</stock_unit><unit_cost>8.4</unit_cost><unit_price>15</unit_price><opening_stock>10</opening_stock></product></products>"""
        preview = core.parse_product_file("products.xml", xml)
        self.assertEqual(preview["row_count"], 1)
        self.assertEqual(preview["rows"][0]["sku"], "BEEF-X")
        self.assertEqual(preview["rows"][0]["opening_stock"], 10)

    def test_sales_mapping_can_be_corrected_and_xml_read(self):
        custom = b"Sold On,Item Text,Weight Sold,Unit Cost,Receipt Ref\n2026-11-17,Chicken Breast,2.5,12.5,TX-1\n"
        initial = core.parse_sales_file("pos-export.csv", custom)
        self.assertEqual(initial["row_count"], 0)
        self.assertTrue(initial["mapping_issue"])
        corrected = core.parse_sales_file("pos-export.csv", custom, {"date": "Sold On", "product": "Item Text", "quantity": "Weight Sold", "unit_price": "Unit Cost", "sale_id": "Receipt Ref"})
        self.assertEqual(corrected["row_count"], 1)
        self.assertEqual(corrected["rows"][0]["product"], "Chicken Breast")
        xml = b"""<?xml version='1.0'?><sales><sale><date>2026-11-17</date><product>Chicken Breast</product><sku>CHK-XML</sku><quantity>1.5</quantity><unit>kg</unit><unit_price>12</unit_price><line_total>18</line_total></sale></sales>"""
        xml_preview = core.parse_sales_file("sales.xml", xml)
        self.assertEqual(xml_preview["row_count"], 1)
        self.assertEqual(xml_preview["rows"][0]["total"], 18)

    def test_assistant_answers_from_records(self):
        p = self.product(opening_stock=20)
        with core.connect() as con:
            con.execute("INSERT INTO sales(product_id,sold_at,quantity,unit_price,total,row_key) VALUES (?,?,?,?,?,?)", (p["id"], core.today().isoformat(), 4, 12, 48, "assistant-test-row"))
        answer = core.assistant_answer("What are my best sellers?")
        self.assertIn("Chicken Breast", answer["answer"])
        revenue = core.assistant_answer("What are my sales revenue?")
        self.assertIn("48.00", revenue["answer"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
