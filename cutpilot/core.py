"""CutPilot business logic: SQLite storage, imports, forecasting and operations."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import statistics
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("CUTPILOT_DB", DATA_DIR / "cutpilot.sqlite3"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_CONTEXT = threading.local()

def set_active_db_path(path: str | Path | None) -> None:
    """Select a workspace database for the current request thread."""
    if path is None:
        clear_active_db_path()
        return
    _DB_CONTEXT.path = Path(path).resolve()
    Path(_DB_CONTEXT.path).parent.mkdir(parents=True, exist_ok=True)

def clear_active_db_path() -> None:
    if hasattr(_DB_CONTEXT, "path"):
        delattr(_DB_CONTEXT, "path")

def active_db_path() -> Path:
    return getattr(_DB_CONTEXT, "path", DB_PATH)

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sku TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    stock_unit TEXT NOT NULL DEFAULT 'kg',
    purchase_unit TEXT NOT NULL DEFAULT 'kg',
    conversion_factor REAL NOT NULL DEFAULT 1,
    min_stock REAL NOT NULL DEFAULT 0,
    pack_size REAL NOT NULL DEFAULT 1,
    shelf_life_days INTEGER NOT NULL DEFAULT 3,
    unit_cost REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0,
    on_hand REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_name TEXT DEFAULT '',
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    lead_time_days INTEGER NOT NULL DEFAULT 2,
    minimum_order_value REAL NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supplier_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_sku TEXT DEFAULT '',
    unit_cost REAL NOT NULL DEFAULT 0,
    lead_time_days INTEGER,
    minimum_quantity REAL NOT NULL DEFAULT 0,
    UNIQUE(supplier_id, product_id)
);
CREATE TABLE IF NOT EXISTS stock_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    supplier_id INTEGER REFERENCES suppliers(id),
    batch_code TEXT DEFAULT '',
    received_at TEXT NOT NULL,
    expiry_date TEXT,
    quantity_received REAL NOT NULL,
    quantity_remaining REAL NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    movement_type TEXT NOT NULL,
    quantity_delta REAL NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0,
    reference_type TEXT DEFAULT '',
    reference_id INTEGER,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    sold_at TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    external_sale_id TEXT DEFAULT '',
    row_key TEXT NOT NULL UNIQUE,
    source_import_id INTEGER,
    stock_deducted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sales_product_date ON sales(product_id, sold_at);
CREATE TABLE IF NOT EXISTS sales_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    row_count INTEGER NOT NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    apply_to_stock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS waste_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity REAL NOT NULL,
    reason TEXT NOT NULL,
    estimated_cost REAL NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT NOT NULL UNIQUE,
    supplier_id INTEGER REFERENCES suppliers(id),
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    expected_delivery TEXT,
    approved_at TEXT,
    received_at TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    notes TEXT DEFAULT '',
    total_estimate REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity REAL NOT NULL,
    received_quantity REAL NOT NULL DEFAULT 0,
    unit_cost REAL NOT NULL DEFAULT 0,
    line_total REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS forecast_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    method TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demand_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_run_id INTEGER NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    forecast_date TEXT NOT NULL,
    predicted_quantity REAL NOT NULL,
    confidence TEXT NOT NULL,
    UNIQUE(forecast_run_id, product_id, forecast_date)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> date:
    """Current calendar date in the shop's configured timezone."""
    try:
        con = connect()
        row = con.execute("SELECT value FROM settings WHERE key='business_timezone'").fetchone()
        con.close()
        tz_name = row[0] if row else "UTC"
        return datetime.now(ZoneInfo(tz_name)).date()
    except (sqlite3.Error, ZoneInfoNotFoundError, ValueError):
        return datetime.now().date()


class ClosingConnection(sqlite3.Connection):
    """SQLite context manager that commits/rolls back and always closes."""
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    db_path = active_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=20, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        defaults = {
            "business_name": "My Butcher Shop",
            "currency": "USD",
            "review_period_days": "7",
            "forecast_horizon_days": "14",
            "business_timezone": "UTC",
            "low_stock_threshold_days": "3",
        }
        for key, value in defaults.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_settings(con: sqlite3.Connection | None = None) -> dict[str, str]:
    own = con is None
    con = con or connect()
    try:
        return {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM settings")}
    finally:
        if own:
            con.close()


def update_settings(payload: dict[str, Any]) -> dict[str, str]:
    allowed = {"business_name", "currency", "review_period_days", "forecast_horizon_days", "business_timezone"}
    clean = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        value = str(value).strip()
        if key == "business_name" and (not value or len(value) > 100):
            raise ValueError("Business name must contain between 1 and 100 characters")
        if key == "currency":
            value = value.upper()
            if not re.fullmatch(r"[A-Z]{3}", value):
                raise ValueError("Currency must be a three-letter currency code")
        if key == "review_period_days":
            if not value.isdigit() or not 1 <= int(value) <= 30:
                raise ValueError("Review period must be between 1 and 30 days")
        if key == "forecast_horizon_days":
            if not value.isdigit() or not 1 <= int(value) <= 90:
                raise ValueError("Forecast horizon must be between 1 and 90 days")
        if key == "business_timezone":
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError:
                raise ValueError("Enter a valid IANA timezone, such as Europe/London or Asia/Dubai")
        clean[key] = value
    with connect() as con:
        for key, value in clean.items():
            con.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        con.execute("INSERT INTO audit_events(event_type,description,created_at) VALUES (?,?,?)", ("settings_updated", "Business settings updated", utc_now()))
        return get_settings(con)


def audit(con: sqlite3.Connection, event_type: str, description: str) -> None:
    con.execute("INSERT INTO audit_events(event_type,description,created_at) VALUES (?,?,?)", (event_type, description, utc_now()))


def _positive(value: Any, label: str, allow_zero: bool = True) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(num) or (num < 0 if allow_zero else num <= 0):
        raise ValueError(f"{label} must be {'zero or greater' if allow_zero else 'greater than zero'}")
    return num


def _consume_batches(con: sqlite3.Connection, product_id: int, quantity: float) -> None:
    remaining = quantity
    batches = con.execute(
        "SELECT id,quantity_remaining FROM stock_batches WHERE product_id=? AND quantity_remaining>0 ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END, expiry_date ASC, received_at ASC",
        (product_id,),
    ).fetchall()
    for batch in batches:
        if remaining <= 1e-9:
            break
        take = min(float(batch["quantity_remaining"]), remaining)
        con.execute("UPDATE stock_batches SET quantity_remaining=quantity_remaining-? WHERE id=?", (take, batch["id"]))
        remaining -= take
    # Any remaining amount can come from legacy/manual opening stock without a batch.


def add_stock_movement(
    con: sqlite3.Connection,
    product_id: int,
    quantity_delta: float,
    movement_type: str,
    note: str = "",
    unit_cost: float | None = None,
    supplier_id: int | None = None,
    expiry_date: str | None = None,
    reference_type: str = "",
    reference_id: int | None = None,
) -> None:
    product = con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if product is None:
        raise ValueError("Product not found")
    current = float(product["on_hand"])
    delta = float(quantity_delta)
    if current + delta < -1e-8:
        raise ValueError(f"Insufficient stock for {product['name']}: {current:g} {product['stock_unit']} available")
    cost = float(product["unit_cost"] if unit_cost is None else unit_cost)
    if delta < 0:
        _consume_batches(con, product_id, -delta)
    elif delta > 0:
        if not expiry_date and int(product["shelf_life_days"] or 0) > 0:
            expiry_date = (today() + timedelta(days=int(product["shelf_life_days"]))).isoformat()
        if expiry_date:
            try:
                date.fromisoformat(str(expiry_date))
            except ValueError:
                raise ValueError("Expiry date must use YYYY-MM-DD")
        con.execute(
            "INSERT INTO stock_batches(product_id,supplier_id,received_at,expiry_date,quantity_received,quantity_remaining,unit_cost) VALUES (?,?,?,?,?,?,?)",
            (product_id, supplier_id, utc_now(), expiry_date, delta, delta, cost),
        )
    con.execute("UPDATE products SET on_hand=? WHERE id=?", (max(0, current + delta), product_id))
    con.execute(
        "INSERT INTO stock_movements(product_id,movement_type,quantity_delta,unit_cost,reference_type,reference_id,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (product_id, movement_type, delta, cost, reference_type, reference_id, note, utc_now()),
    )


def list_products() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT * FROM products WHERE active=1 ORDER BY category,name").fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["stock_value"] = round(item["on_hand"] * item["unit_cost"], 2)
            result.append(item)
        return result


def create_product(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("Product name is required")
    sku = str(payload.get("sku") or re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")).strip()
    if not sku:
        raise ValueError("SKU is required")
    stock_unit = str(payload.get("stock_unit") or "kg").strip().lower()
    purchase_unit = str(payload.get("purchase_unit") or stock_unit).strip().lower()
    conversion = _positive(payload.get("conversion_factor", 1), "Conversion factor", False)
    min_stock = _positive(payload.get("min_stock", 0), "Minimum stock")
    pack_size = _positive(payload.get("pack_size", 1), "Pack size", False)
    shelf_life = int(payload.get("shelf_life_days", 3))
    if shelf_life < 1 or shelf_life > 3650:
        raise ValueError("Shelf life must be between 1 and 3650 days")
    unit_cost = _positive(payload.get("unit_cost", 0), "Unit cost")
    unit_price = _positive(payload.get("unit_price", 0), "Unit price")
    opening = _positive(payload.get("opening_stock", 0), "Opening stock")
    with connect() as con:
        try:
            cur = con.execute(
                "INSERT INTO products(name,sku,category,stock_unit,purchase_unit,conversion_factor,min_stock,pack_size,shelf_life_days,unit_cost,unit_price,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, sku, payload.get("category", "Uncategorized"), stock_unit, purchase_unit, conversion, min_stock, pack_size, shelf_life, unit_cost, unit_price, utc_now()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("That SKU already exists. Choose a unique SKU.")
        product_id = cur.lastrowid
        if opening:
            add_stock_movement(con, product_id, opening, "opening_stock", "Opening stock balance", unit_cost)
        audit(con, "product_created", f"Created product {name} ({sku})")
        return dict(con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())


def update_product(product_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    fields = ["name", "sku", "category", "stock_unit", "purchase_unit", "conversion_factor", "min_stock", "pack_size", "shelf_life_days", "unit_cost", "unit_price"]
    updates = {k: payload[k] for k in fields if k in payload}
    if not updates:
        raise ValueError("No editable product fields were provided")
    for key in ["conversion_factor", "pack_size"]:
        if key in updates:
            updates[key] = _positive(updates[key], key.replace("_", " "), False)
    for key in ["min_stock", "unit_cost", "unit_price"]:
        if key in updates:
            updates[key] = _positive(updates[key], key.replace("_", " "))
    if "shelf_life_days" in updates:
        updates["shelf_life_days"] = int(updates["shelf_life_days"])
        if not 1 <= updates["shelf_life_days"] <= 3650:
            raise ValueError("Shelf life must be between 1 and 3650 days")
    with connect() as con:
        current = con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if current is None:
            raise ValueError("Product not found")
        if "stock_unit" in updates and str(updates["stock_unit"]).lower() != str(current["stock_unit"]).lower():
            has_history = con.execute("SELECT (SELECT COUNT(*) FROM sales WHERE product_id=?)+(SELECT COUNT(*) FROM stock_movements WHERE product_id=?)+(SELECT COUNT(*) FROM stock_batches WHERE product_id=?)", (product_id, product_id, product_id)).fetchone()[0]
            if has_history or float(current["on_hand"]) > 0:
                raise ValueError("Stock unit cannot be changed after inventory or sales history exists. Create a new product instead.")
        set_sql = ",".join(f"{k}=?" for k in updates)
        try:
            con.execute(f"UPDATE products SET {set_sql} WHERE id=?", (*updates.values(), product_id))
        except sqlite3.IntegrityError:
            raise ValueError("That SKU already exists")
        audit(con, "product_updated", f"Updated product ID {product_id}")
        return dict(con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())


def adjust_stock(payload: dict[str, Any]) -> dict[str, Any]:
    product_id = int(payload.get("product_id", 0))
    quantity = _positive(payload.get("quantity", 0), "Quantity", False)
    action = str(payload.get("action", "receive"))
    if action not in {"receive", "remove", "set"}:
        raise ValueError("Stock action must be receive, remove or set")
    with connect() as con:
        product = con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if product is None:
            raise ValueError("Product not found")
        if action == "receive":
            delta, movement = quantity, "stock_received"
        elif action == "remove":
            delta, movement = -quantity, "manual_adjustment_out"
        else:
            delta, movement = quantity - float(product["on_hand"]), "stock_count_adjustment"
        add_stock_movement(con, product_id, delta, movement, str(payload.get("note") or "Manual stock update"), payload.get("unit_cost"), expiry_date=payload.get("expiry_date"))
        audit(con, "stock_updated", f"Stock updated for {product['name']}: {delta:+g} {product['stock_unit']}")
        return dict(con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())


def create_supplier(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("Supplier name is required")
    lead = int(payload.get("lead_time_days", 2))
    if lead < 0 or lead > 365:
        raise ValueError("Lead time must be between 0 and 365 days")
    with connect() as con:
        cur = con.execute(
            "INSERT INTO suppliers(name,contact_name,email,phone,lead_time_days,minimum_order_value,notes,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (name, payload.get("contact_name", ""), payload.get("email", ""), payload.get("phone", ""), lead, _positive(payload.get("minimum_order_value", 0), "Minimum order value"), payload.get("notes", ""), utc_now()),
        )
        audit(con, "supplier_created", f"Created supplier {name}")
        return dict(con.execute("SELECT * FROM suppliers WHERE id=?", (cur.lastrowid,)).fetchone())


def list_suppliers() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT s.*, COUNT(sp.id) AS product_count FROM suppliers s LEFT JOIN supplier_products sp ON sp.supplier_id=s.id WHERE s.active=1 GROUP BY s.id ORDER BY s.name").fetchall()
        return [dict(r) for r in rows]


def link_supplier_product(payload: dict[str, Any]) -> dict[str, Any]:
    supplier_id = int(payload.get("supplier_id", 0))
    product_id = int(payload.get("product_id", 0))
    unit_cost = _positive(payload.get("unit_cost", 0), "Unit cost")
    with connect() as con:
        if not con.execute("SELECT 1 FROM suppliers WHERE id=?", (supplier_id,)).fetchone():
            raise ValueError("Supplier not found")
        if not con.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("Product not found")
        con.execute("INSERT INTO supplier_products(supplier_id,product_id,supplier_sku,unit_cost,lead_time_days,minimum_quantity) VALUES (?,?,?,?,?,?) ON CONFLICT(supplier_id,product_id) DO UPDATE SET supplier_sku=excluded.supplier_sku,unit_cost=excluded.unit_cost,lead_time_days=excluded.lead_time_days,minimum_quantity=excluded.minimum_quantity",
                    (supplier_id, product_id, payload.get("supplier_sku", ""), unit_cost, payload.get("lead_time_days"), _positive(payload.get("minimum_quantity", 0), "Minimum quantity")))
        return dict(con.execute("SELECT * FROM supplier_products WHERE supplier_id=? AND product_id=?", (supplier_id, product_id)).fetchone())


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Missing sale date")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot understand date: {raw}")


def _number(value: Any, label: str, required: bool = True) -> float:
    raw = str(value if value is not None else "").strip().replace("\u00a0", "").replace(" ", "")
    if "," in raw and "." in raw:
        # Support both 1,234.56 (US) and 1.234,56 (many European locales).
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[-1]
        # A one/two digit suffix is usually a decimal comma; three digits usually a thousands group.
        if len(tail) in (1, 2):
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    if not raw and not required:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        if required:
            raise ValueError(f"Missing or invalid {label}")
        return 0.0
    num = float(match.group())
    if not math.isfinite(num):
        raise ValueError(f"Invalid {label}")
    return num


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())

HEADER_ALIASES = {
    "date": {"date", "soldat", "saleDate", "datetime", "transactiondate", "timestamp", "day"},
    "product": {"product", "productname", "item", "itemname", "description", "name"},
    "sku": {"sku", "productsku", "itemsku", "productcode", "code", "barcode"},
    "quantity": {"quantity", "qty", "units", "soldqty", "amountsold", "weight", "netweight"},
    "unit": {"unit", "uom", "measure", "unitofmeasure"},
    "unit_price": {"unitprice", "price", "priceperunit", "sellprice", "rate"},
    "total": {"total", "linetotal", "amount", "salesamount", "netamount"},
    "sale_id": {"saleid", "transactionid", "receipt", "receiptid", "ticketnumber", "orderid"},
}


def _read_tabular_upload(filename: str, content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Read CSV, XLSX/XLSM or simple row-based XML into header/record pairs."""
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Files must be smaller than 10 MB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = content.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = [str(h or "").strip() for h in (reader.fieldnames or [])]
        rows = [{str(k or "").strip(): v for k, v in row.items()} for row in reader]
    elif suffix in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("Excel support requires openpyxl. Run: py -m pip install -r requirements.txt")
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        iterator = ws.iter_rows(values_only=True)
        first = next(iterator, None)
        if not first:
            wb.close()
            raise ValueError("The Excel sheet is empty")
        headers = [str(v).strip() if v is not None else "" for v in first]
        rows = []
        for values in iterator:
            rows.append({headers[i]: values[i] if i < len(values) else None for i in range(len(headers)) if headers[i]})
        wb.close()
    elif suffix == ".xml":
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"Could not read XML: {exc}")
        candidates = []
        for element in root.iter():
            children = list(element)
            if children and all(not list(child) for child in children):
                record = {str(k): v for k, v in element.attrib.items()}
                record.update({child.tag.split('}')[-1]: child.text for child in children})
                if record:
                    candidates.append(record)
        if not candidates:
            raise ValueError("No simple row records found. Use the CutPilot XML template: a <products> or <sales> root with repeated <product> or <sale> elements and simple child fields.")
        # Prefer the most frequent record shape; ignore container nodes.
        shapes: dict[tuple[str, ...], int] = {}
        for row in candidates:
            key = tuple(row.keys())
            shapes[key] = shapes.get(key, 0) + 1
        headers = list(max(shapes, key=shapes.get))
        rows = [{h: row.get(h) for h in headers} for row in candidates if len(set(row).intersection(headers)) >= max(1, len(headers)//2)]
    else:
        raise ValueError("Choose a CSV, Excel .xlsx/.xlsm or row-based XML file")
    headers = [h for h in headers if h]
    if not headers:
        raise ValueError("No column headers found. The first CSV/Excel row must contain column names.")
    return headers, rows


def _guess_mapping(headers: list[str], aliases_by_field: dict[str, set[str]], supplied: dict[str, Any] | None = None) -> dict[str, str | None]:
    supplied = supplied or {}
    by_norm = {_norm_header(h): h for h in headers}
    mapping: dict[str, str | None] = {}
    for field, aliases in aliases_by_field.items():
        if field in supplied:
            chosen = supplied.get(field)
            mapping[field] = chosen if chosen in headers else None
            continue
        mapping[field] = None
        for alias in aliases:
            key = _norm_header(alias)
            if key in by_norm:
                mapping[field] = by_norm[key]
                break
    return mapping


PRODUCT_HEADER_ALIASES = {
    "name": {"name", "product", "productname", "item", "itemname", "description", "productdescription"},
    "sku": {"sku", "productsku", "itemsku", "productcode", "itemcode", "code", "barcode", "plu"},
    "category": {"category", "type", "department", "group"},
    "stock_unit": {"stockunit", "unit", "uom", "unitofmeasure", "sellunit"},
    "purchase_unit": {"purchaseunit", "buyunit", "supplierunit"},
    "conversion_factor": {"conversionfactor", "purchasetostockfactor", "unitconversion", "unitsperpack"},
    "unit_cost": {"unitcost", "cost", "purchasecost", "costperunit", "buyprice", "costprice"},
    "unit_price": {"unitprice", "price", "sellingprice", "saleprice", "retailprice", "sellprice"},
    "opening_stock": {"openingstock", "onhand", "stock", "currentstock", "quantityonhand", "initialquantity"},
    "min_stock": {"minstock", "minimumstock", "reorderlevel", "minimumlevel", "parlevel"},
    "pack_size": {"packsize", "ordermultiple", "supplierpacksize", "minimumorderquantity"},
    "shelf_life_days": {"shelflifedays", "shelflife", "expirywindowdays"},
}

HEADER_ALIASES = {
    "date": {"date", "soldat", "saleDate", "datetime", "transactiondate", "timestamp", "day"},
    "product": {"product", "productname", "item", "itemname", "description", "name"},
    "sku": {"sku", "productsku", "itemsku", "productcode", "code", "barcode", "plu"},
    "quantity": {"quantity", "qty", "units", "soldqty", "amountsold", "weight", "netweight"},
    "unit": {"unit", "uom", "measure", "unitofmeasure"},
    "unit_price": {"unitprice", "price", "priceperunit", "sellprice", "rate"},
    "total": {"total", "linetotal", "amount", "salesamount", "netamount", "extendedprice"},
    "sale_id": {"saleid", "transactionid", "receipt", "receiptid", "ticketnumber", "orderid"},
}


def parse_product_file(filename: str, content: bytes, supplied_mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    headers, raw_rows = _read_tabular_upload(filename, content)
    mapping = _guess_mapping(headers, PRODUCT_HEADER_ALIASES, supplied_mapping)
    mapping_issue = None if mapping.get("name") else "Map a Product name column before importing. Every product row needs a product name."
    normalized_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    numeric_fields = {"conversion_factor": (1.0, True), "unit_cost": (0.0, False), "unit_price": (0.0, False), "opening_stock": (0.0, False), "min_stock": (0.0, False), "pack_size": (1.0, True), "shelf_life_days": (3, True)}
    for index, raw in enumerate(raw_rows, start=2):
        if mapping_issue:
            break
        if not any(v not in (None, "") for v in raw.values()):
            continue
        try:
            def value(field: str, default: Any = "") -> Any:
                col = mapping.get(field)
                return raw.get(col, default) if col else default
            name = str(value("name", "") or "").strip()
            if not name:
                raise ValueError("Product name is required")
            stock_unit = str(value("stock_unit", "kg") or "kg").strip().lower()
            purchase_unit = str(value("purchase_unit", stock_unit) or stock_unit).strip().lower()
            if not stock_unit or not purchase_unit:
                raise ValueError("Stock unit and purchase unit cannot be empty")
            item: dict[str, Any] = {
                "name": name, "sku": str(value("sku", "") or "").strip(),
                "category": str(value("category", "Uncategorized") or "Uncategorized").strip(),
                "stock_unit": stock_unit, "purchase_unit": purchase_unit,
            }
            for field, (default, must_positive) in numeric_fields.items():
                raw_value = value(field, default)
                parsed = _number(raw_value, field.replace("_", " "), required=False) if raw_value not in (None, "") else float(default)
                if parsed < 0 or (must_positive and parsed <= 0):
                    qualifier = "greater than zero" if must_positive else "zero or greater"
                    raise ValueError(f"{field.replace('_', ' ').title()} must be {qualifier}")
                item[field] = int(parsed) if field == "shelf_life_days" else parsed
            if item["shelf_life_days"] < 1 or item["shelf_life_days"] > 3650:
                raise ValueError("Shelf life must be between 1 and 3650 days")
            normalized_rows.append({**item, "source_row": index})
        except Exception as exc:
            errors.append({"row": index, "error": str(exc)})
    if mapping_issue:
        errors.insert(0, {"row": "Columns", "error": mapping_issue})
    return {"headers": headers, "mapping": mapping, "rows": normalized_rows, "errors": errors,
            "row_count": len(normalized_rows), "preview": normalized_rows[:8], "mapping_issue": mapping_issue, "file_type": Path(filename).suffix.lower()}


def import_products(rows: list[dict[str, Any]], update_existing_stock: bool = False) -> dict[str, Any]:
    if not rows:
        raise ValueError("There are no valid product rows to import")
    created = updated = 0
    errors: list[dict[str, Any]] = []
    with connect() as con:
        for index, item in enumerate(rows, start=2):
            con.execute("SAVEPOINT product_import_row")
            try:
                name = str(item.get("name") or "").strip()
                if not name:
                    raise ValueError("Product name is required")
                sku = str(item.get("sku") or re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:40]).strip()
                existing = con.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
                if existing:
                    imported_unit = str(item.get("stock_unit", existing["stock_unit"])).lower()
                    if imported_unit != str(existing["stock_unit"]).lower():
                        history = con.execute("SELECT (SELECT COUNT(*) FROM sales WHERE product_id=?)+(SELECT COUNT(*) FROM stock_movements WHERE product_id=?)+(SELECT COUNT(*) FROM stock_batches WHERE product_id=?)", (existing["id"], existing["id"], existing["id"])).fetchone()[0]
                        if history or float(existing["on_hand"]) > 0:
                            raise ValueError("Stock unit cannot be changed for an existing product with stock or history. Create a new SKU instead.")
                    if update_existing_stock:
                        target = float(item.get("opening_stock", existing["on_hand"]))
                        delta = target - float(existing["on_hand"])
                        if abs(delta) > 1e-8:
                            add_stock_movement(con, int(existing["id"]), delta, "catalog_stocktake", "Stock balance updated from imported product catalog", item.get("unit_cost", existing["unit_cost"]))
                    updates = {k: item[k] for k in ("name", "category", "stock_unit", "purchase_unit", "conversion_factor", "min_stock", "pack_size", "shelf_life_days", "unit_cost", "unit_price") if k in item}
                    if updates:
                        sql = ",".join(f"{k}=?" for k in updates)
                        con.execute(f"UPDATE products SET {sql} WHERE id=?", (*updates.values(), existing["id"]))
                    updated += 1
                else:
                    cur = con.execute("INSERT INTO products(name,sku,category,stock_unit,purchase_unit,conversion_factor,min_stock,pack_size,shelf_life_days,unit_cost,unit_price,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (name, sku, item.get("category", "Uncategorized"), item.get("stock_unit", "kg"), item.get("purchase_unit", item.get("stock_unit", "kg")), item.get("conversion_factor", 1), item.get("min_stock", 0), item.get("pack_size", 1), item.get("shelf_life_days", 3), item.get("unit_cost", 0), item.get("unit_price", 0), utc_now()))
                    opening = float(item.get("opening_stock", 0))
                    if opening > 0:
                        add_stock_movement(con, int(cur.lastrowid), opening, "opening_stock", "Opening stock imported from product catalog", item.get("unit_cost", 0))
                    created += 1
                con.execute("RELEASE SAVEPOINT product_import_row")
            except Exception as exc:
                con.execute("ROLLBACK TO SAVEPOINT product_import_row")
                con.execute("RELEASE SAVEPOINT product_import_row")
                errors.append({"row": item.get("source_row", index), "error": str(exc)})
        audit(con, "products_imported", f"Imported product catalog: {created} created, {updated} updated, {len(errors)} row errors")
    return {"created": created, "updated": updated, "skipped": 0, "errors": errors}


def parse_sales_file(filename: str, content: bytes, supplied_mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    headers, raw_rows = _read_tabular_upload(filename, content)
    mapping = _guess_mapping(headers, HEADER_ALIASES, supplied_mapping)
    mapping_issue = None
    if not mapping.get("date") or not mapping.get("quantity") or not (mapping.get("product") or mapping.get("sku")):
        mapping_issue = "Map Sale date, Quantity, and either Product name or SKU before importing."
    normalized_rows = []
    errors = []
    for index, raw in enumerate(raw_rows, start=2):
        if mapping_issue:
            break
        if not any(v not in (None, "") for v in raw.values()):
            continue
        try:
            date_value = _parse_date(raw.get(mapping["date"]))
            qty_raw = raw.get(mapping["quantity"])
            quantity = _number(qty_raw, "quantity")
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero")
            unit = str(raw.get(mapping["unit"]) or "").strip().lower() if mapping.get("unit") else ""
            qty_text = str(qty_raw or "")
            unit_match = re.search(r"\b(kg|g|gram|grams|lb|lbs|oz|piece|pieces|pc|pcs)\b", qty_text, re.I)
            if not unit and unit_match:
                unit = unit_match.group(1).lower()
            unit = {"gram": "g", "grams": "g", "lbs": "lb", "pc": "piece", "pcs": "piece", "pieces": "piece"}.get(unit, unit)
            product = str(raw.get(mapping["product"]) or "").strip() if mapping.get("product") else ""
            sku = str(raw.get(mapping["sku"]) or "").strip() if mapping.get("sku") else ""
            if not product and not sku:
                raise ValueError("Missing product name and SKU")
            unit_price = _number(raw.get(mapping["unit_price"]), "unit price", required=False) if mapping.get("unit_price") else 0.0
            raw_total = raw.get(mapping["total"]) if mapping.get("total") else None
            total = _number(raw_total, "line total", required=False) if raw_total not in (None, "") else quantity * unit_price
            if unit_price == 0 and total > 0:
                unit_price = total / quantity
            sale_id = str(raw.get(mapping["sale_id"]) or "").strip() if mapping.get("sale_id") else ""
            normalized_rows.append({"date": date_value.isoformat(), "product": product or sku, "sku": sku, "quantity": quantity, "unit": unit, "unit_price": unit_price, "total": total, "sale_id": sale_id, "source_row": index})
        except Exception as exc:
            errors.append({"row": index, "error": str(exc)})
    if mapping_issue:
        errors.insert(0, {"row": "Columns", "error": mapping_issue})
    if not normalized_rows and not mapping_issue:
        errors.insert(0, {"row": "File", "error": "No valid sales rows found. Check date formats, quantities and product identifiers."})
    unmatched_products = []
    if normalized_rows:
        with connect() as con:
            for item in normalized_rows:
                match = con.execute("SELECT 1 FROM products WHERE sku=?", (item.get("sku"),)).fetchone() if item.get("sku") else None
                if not match:
                    match = con.execute("SELECT 1 FROM products WHERE lower(name)=lower(?)", (item.get("product"),)).fetchone()
                if not match:
                    label = item.get("sku") or item.get("product")
                    if label not in unmatched_products:
                        unmatched_products.append(label)
    return {"headers": headers, "mapping": mapping, "rows": normalized_rows, "errors": errors, "row_count": len(normalized_rows), "preview": normalized_rows[:8], "unmatched_products": unmatched_products, "mapping_issue": mapping_issue, "file_type": Path(filename).suffix.lower()}

def import_sales(filename: str, file_hash: str, rows: list[dict[str, Any]], apply_to_stock: bool = False) -> dict[str, Any]:
    if not rows:
        raise ValueError("There are no sales rows to import")
    with connect() as con:
        if con.execute("SELECT 1 FROM sales_imports WHERE file_hash=?", (file_hash,)).fetchone():
            raise ValueError("This exact file has already been imported. No duplicate records were added.")
        cur = con.execute("INSERT INTO sales_imports(filename,file_hash,row_count,imported_at,apply_to_stock) VALUES (?,?,?,?,?)", (filename, file_hash, len(rows), utc_now(), int(apply_to_stock)))
        import_id = cur.lastrowid
        imported = duplicate = 0
        errors = []
        for i, item in enumerate(rows):
            con.execute("SAVEPOINT import_row")
            try:
                qty = _positive(item.get("quantity"), "Quantity", False)
                sold_date = _parse_date(item.get("date")).isoformat()
                sku = str(item.get("sku") or "").strip()
                name = str(item.get("product") or sku).strip()
                if not name:
                    raise ValueError("Product is missing")
                product = con.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone() if sku else None
                if product is None:
                    product = con.execute("SELECT * FROM products WHERE lower(name)=lower(?)", (name,)).fetchone()
                if product is None:
                    auto_sku = sku or re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:40] or f"IMP-{i}"
                    existing = con.execute("SELECT id FROM products WHERE sku=?", (auto_sku,)).fetchone()
                    if existing:
                        auto_sku = f"{auto_sku}-{hashlib.md5(name.encode()).hexdigest()[:5]}"
                    product_unit = str(item.get("unit") or "kg")
                    pcur = con.execute("INSERT INTO products(name,sku,category,stock_unit,purchase_unit,created_at) VALUES (?,?,?,?,?,?)", (name, auto_sku, "Imported", product_unit, product_unit, utc_now()))
                    product = con.execute("SELECT * FROM products WHERE id=?", (pcur.lastrowid,)).fetchone()
                if item.get("unit") and str(item["unit"]).lower() != str(product["stock_unit"]).lower():
                    # Avoid unsafe implicit conversions. User can standardize units in product settings.
                    raise ValueError(f"Unit mismatch for {name}: file uses {item['unit']} but product uses {product['stock_unit']}")
                unit_price = _positive(item.get("unit_price", 0), "Unit price")
                total = _positive(item.get("total", qty * unit_price), "Line total")
                sale_id = str(item.get("sale_id") or "")
                signature = "|".join([sold_date, sale_id, str(product["id"]), f"{qty:.6f}", f"{unit_price:.4f}"])
                key_material = f"external|{sale_id}|{product['id']}" if sale_id else f"{file_hash}|{signature}|{item.get('source_row', i)}"
                row_key = hashlib.sha256(key_material.encode()).hexdigest()
                if apply_to_stock and float(product["on_hand"]) + 1e-8 < qty:
                    raise ValueError(f"Insufficient stock for {product['name']}; import without stock deduction or update inventory first")
                try:
                    scur = con.execute("INSERT INTO sales(product_id,sold_at,quantity,unit_price,total,external_sale_id,row_key,source_import_id,stock_deducted) VALUES (?,?,?,?,?,?,?,?,?)", (product["id"], sold_date, qty, unit_price, total, sale_id, row_key, import_id, int(apply_to_stock)))
                except sqlite3.IntegrityError:
                    con.execute("ROLLBACK TO SAVEPOINT import_row")
                    con.execute("RELEASE SAVEPOINT import_row")
                    duplicate += 1
                    continue
                if apply_to_stock:
                    add_stock_movement(con, int(product["id"]), -qty, "sale", f"Imported sale {sale_id or scur.lastrowid}", reference_type="sale", reference_id=scur.lastrowid)
                con.execute("RELEASE SAVEPOINT import_row")
                imported += 1
            except Exception as exc:
                con.execute("ROLLBACK TO SAVEPOINT import_row")
                con.execute("RELEASE SAVEPOINT import_row")
                errors.append({"row": item.get("source_row", i + 2), "error": str(exc)})
        con.execute("UPDATE sales_imports SET imported_count=?,duplicate_count=? WHERE id=?", (imported, duplicate, import_id))
        audit(con, "sales_imported", f"Imported {imported} sales rows from {filename}; {duplicate} duplicates")
        return {"import_id": import_id, "imported": imported, "duplicates": duplicate, "errors": errors, "apply_to_stock": apply_to_stock}


def _sales_map(con: sqlite3.Connection, product_id: int, start: date, end: date) -> dict[date, float]:
    rows = con.execute("SELECT sold_at, SUM(quantity) AS qty FROM sales WHERE product_id=? AND sold_at>=? AND sold_at<=? GROUP BY sold_at", (product_id, start.isoformat(), end.isoformat())).fetchall()
    return {date.fromisoformat(r["sold_at"][:10]): float(r["qty"]) for r in rows}


def _forecast_daily_series(sales: dict[date, float], end_date: date, horizon: int, history_days: int = 56) -> tuple[list[dict[str, Any]], str, int]:
    start = end_date - timedelta(days=history_days - 1)
    all_days = [start + timedelta(days=i) for i in range(history_days)]
    observed = [sales.get(d, 0.0) for d in all_days]
    nonzero_days = sum(1 for x in observed if x > 0)
    if nonzero_days == 0:
        return [], "insufficient", 0
    recent_start = end_date - timedelta(days=27)
    recent = {d: q for d, q in sales.items() if recent_start <= d <= end_date}
    forecast = []
    weekday_samples: dict[int, list[float]] = {i: [] for i in range(7)}
    for d in all_days:
        weekday_samples[d.weekday()].append(sales.get(d, 0.0))
    recent_samples: dict[int, list[float]] = {i: [] for i in range(7)}
    for d in all_days:
        if d >= recent_start:
            recent_samples[d.weekday()].append(sales.get(d, 0.0))
    for offset in range(1, horizon + 1):
        target = end_date + timedelta(days=offset)
        wd = target.weekday()
        base = statistics.mean(weekday_samples[wd]) if weekday_samples[wd] else statistics.mean(observed)
        recent_base = statistics.mean(recent_samples[wd]) if recent_samples[wd] else base
        pred = max(0.0, 0.65 * recent_base + 0.35 * base)
        forecast.append({"date": target.isoformat(), "quantity": round(pred, 3)})
    sample_count = len([d for d in sales if start <= d <= end_date])
    confidence = "high" if nonzero_days >= 24 and sample_count >= 28 else "medium" if nonzero_days >= 10 else "low"
    return forecast, confidence, nonzero_days


def run_forecasts(horizon_days: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    horizon = int(horizon_days or settings.get("forecast_horizon_days", 14))
    horizon = max(1, min(horizon, 90))
    end = today()
    start = end - timedelta(days=55)
    with connect() as con:
        products = con.execute("SELECT * FROM products WHERE active=1 ORDER BY name").fetchall()
        cur = con.execute("INSERT INTO forecast_runs(created_at,horizon_days,method) VALUES (?,?,?)", (utc_now(), horizon, "weekday_weighted_56d_v1"))
        run_id = cur.lastrowid
        results = []
        for p in products:
            sales = _sales_map(con, p["id"], start, end)
            daily, confidence, selling_days = _forecast_daily_series(sales, end, horizon)
            if not daily:
                results.append({"product_id": p["id"], "product": p["name"], "sku": p["sku"], "forecast_total": None, "confidence": "insufficient", "selling_days": 0, "daily": []})
                continue
            for d in daily:
                con.execute("INSERT INTO demand_forecasts(forecast_run_id,product_id,forecast_date,predicted_quantity,confidence) VALUES (?,?,?,?,?)", (run_id, p["id"], d["date"], d["quantity"], confidence))
            results.append({"product_id": p["id"], "product": p["name"], "sku": p["sku"], "forecast_total": round(sum(x["quantity"] for x in daily), 2), "confidence": confidence, "selling_days": selling_days, "daily": daily})
        audit(con, "forecast_generated", f"Generated {horizon}-day forecasts for {len(products)} products")
        return {"run_id": run_id, "horizon_days": horizon, "method": "weekday-weighted historical demand", "created_at": utc_now(), "forecasts": results}


def _product_daily_forecast(con: sqlite3.Connection, product: sqlite3.Row, days: int) -> tuple[list[dict[str, Any]], str, int]:
    end = today()
    start = end - timedelta(days=55)
    sales = _sales_map(con, product["id"], start, end)
    return _forecast_daily_series(sales, end, days)


def get_recommendations() -> list[dict[str, Any]]:
    settings = get_settings()
    review_days = max(1, int(settings.get("review_period_days", 7)))
    with connect() as con:
        products = con.execute("SELECT * FROM products WHERE active=1 ORDER BY name").fetchall()
        incoming_rows = con.execute("SELECT poi.product_id,SUM(poi.quantity-poi.received_quantity) AS incoming FROM purchase_order_items poi JOIN purchase_orders po ON po.id=poi.purchase_order_id WHERE po.status IN ('approved','sent','partially_received') GROUP BY poi.product_id").fetchall()
        incoming = {r["product_id"]: float(r["incoming"] or 0) for r in incoming_rows}
        out = []
        for p in products:
            links = con.execute("SELECT sp.*,s.name AS supplier_name,s.lead_time_days AS supplier_lead FROM supplier_products sp JOIN suppliers s ON s.id=sp.supplier_id WHERE sp.product_id=? AND s.active=1 ORDER BY sp.unit_cost ASC", (p["id"],)).fetchall()
            supplier = links[0] if links else None
            lead = int((supplier["lead_time_days"] if supplier and supplier["lead_time_days"] is not None else supplier["supplier_lead"] if supplier else 2) or 2)
            protection = max(1, lead + review_days)
            daily, confidence, selling_days = _product_daily_forecast(con, p, min(max(protection, 7), 90))
            if daily:
                total_demand = sum(x["quantity"] for x in daily[:protection])
                if protection > len(daily):
                    total_demand += statistics.mean(x["quantity"] for x in daily) * (protection - len(daily))
                observed = _sales_map(con, p["id"], today() - timedelta(days=55), today())
                values = [observed.get(today() - timedelta(days=i), 0.0) for i in range(55, -1, -1)]
                std = statistics.pstdev(values) if len(values) > 1 else 0.0
                safety = 1.28 * std * math.sqrt(max(1, lead))
            else:
                total_demand = 0.0
                safety = 0.0
            inventory_position = float(p["on_hand"]) + incoming.get(p["id"], 0.0)
            target = max(total_demand + safety, float(p["min_stock"]))
            need = max(0.0, target - inventory_position)
            # Do not recommend purchase without sales history unless a minimum stock is explicitly configured.
            if confidence == "insufficient" and float(p["min_stock"]) <= inventory_position:
                need = 0.0
                reason = "Not enough sales history to forecast; set a minimum stock or import more sales."
            else:
                reason = f"Forecast demand {total_demand:.1f} + safety stock {safety:.1f} over {protection} days; position {inventory_position:.1f}."
            conversion_factor = max(0.000001, float(p["conversion_factor"] or 1))
            pack_multiple_stock_units = conversion_factor * max(0.000001, float(p["pack_size"] or 1))
            if need > 0:
                qty = math.ceil(need / pack_multiple_stock_units - 1e-10) * pack_multiple_stock_units
                min_qty = float(supplier["minimum_quantity"] if supplier else 0)  # configured in stock units
                if qty > 0 and min_qty > qty:
                    qty = math.ceil(min_qty / pack_multiple_stock_units - 1e-10) * pack_multiple_stock_units
            else:
                qty = 0.0
            purchase_quantity = qty / conversion_factor
            unit_cost = float(supplier["unit_cost"] if supplier else p["unit_cost"])
            out.append({
                "product_id": p["id"], "product": p["name"], "sku": p["sku"], "category": p["category"],
                "stock_unit": p["stock_unit"], "purchase_unit": p["purchase_unit"], "conversion_factor": conversion_factor,
                "purchase_quantity": round(purchase_quantity, 3), "on_hand": round(float(p["on_hand"]), 3),
                "incoming": round(incoming.get(p["id"], 0.0), 3), "forecast_demand": round(total_demand, 3),
                "safety_stock": round(safety, 3), "inventory_position": round(inventory_position, 3),
                "recommended_quantity": round(qty, 3), "pack_size": pack_multiple_stock_units,
                "unit_cost": unit_cost, "estimated_cost": round(qty * unit_cost, 2),
                "supplier_id": supplier["supplier_id"] if supplier else None,
                "supplier_name": supplier["supplier_name"] if supplier else "Not assigned",
                "lead_time_days": lead, "confidence": confidence, "reason": reason,
                "status": "order" if qty > 0 else "healthy",
            })
        out.sort(key=lambda x: (x["recommended_quantity"] <= 0, -x["estimated_cost"], x["product"]))
        return out


def create_purchase_order(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") or []
    if not items:
        raise ValueError("Select at least one product to create an order")
    supplier_id = payload.get("supplier_id")
    currency = get_settings().get("currency", "USD")
    with connect() as con:
        if supplier_id and not con.execute("SELECT 1 FROM suppliers WHERE id=?", (supplier_id,)).fetchone():
            raise ValueError("Supplier not found")
        clean = []
        total = 0.0
        for item in items:
            product = con.execute("SELECT * FROM products WHERE id=?", (int(item.get("product_id", 0)),)).fetchone()
            if not product:
                raise ValueError("A selected product no longer exists")
            qty = _positive(item.get("quantity", 0), f"Quantity for {product['name']}", False)
            cost = _positive(item.get("unit_cost", product["unit_cost"]), f"Cost for {product['name']}")
            line_total = qty * cost
            clean.append((int(product["id"]), qty, cost, line_total))
            total += line_total
        order_number = f"CP-{datetime.now().strftime('%y%m%d')}-{int(datetime.now().timestamp()) % 100000:05d}"
        expected_delivery = payload.get("expected_delivery")
        if not expected_delivery and supplier_id:
            supplier_row = con.execute("SELECT lead_time_days FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
            lead_days = int(supplier_row["lead_time_days"] or 0)
            for product_id, _, _, _ in clean:
                link = con.execute("SELECT lead_time_days FROM supplier_products WHERE supplier_id=? AND product_id=?", (supplier_id, product_id)).fetchone()
                if link and link["lead_time_days"] is not None:
                    lead_days = max(lead_days, int(link["lead_time_days"]))
            expected_delivery = (today() + timedelta(days=lead_days)).isoformat()
        cur = con.execute("INSERT INTO purchase_orders(order_number,supplier_id,status,created_at,expected_delivery,currency,notes,total_estimate) VALUES (?,?,?,?,?,?,?,?)", (order_number, supplier_id, "draft", utc_now(), expected_delivery, currency, payload.get("notes", "AI-recommended purchase order"), total))
        order_id = cur.lastrowid
        for product_id, qty, cost, line_total in clean:
            con.execute("INSERT INTO purchase_order_items(purchase_order_id,product_id,quantity,unit_cost,line_total) VALUES (?,?,?,?,?)", (order_id, product_id, qty, cost, line_total))
        audit(con, "purchase_order_created", f"Created draft order {order_number}")
        return get_purchase_order(order_id, con)


def get_purchase_order(order_id: int, con: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = con is None
    con = con or connect()
    try:
        order = con.execute("SELECT po.*,s.name AS supplier_name FROM purchase_orders po LEFT JOIN suppliers s ON s.id=po.supplier_id WHERE po.id=?", (order_id,)).fetchone()
        if not order:
            raise ValueError("Purchase order not found")
        result = dict(order)
        result["items"] = [dict(r) for r in con.execute("SELECT poi.*,p.name AS product_name,p.sku,p.stock_unit,p.purchase_unit,p.conversion_factor FROM purchase_order_items poi JOIN products p ON p.id=poi.product_id WHERE poi.purchase_order_id=?", (order_id,)).fetchall()]
        return result
    finally:
        if own:
            con.close()


def list_purchase_orders() -> list[dict[str, Any]]:
    with connect() as con:
        orders = con.execute("SELECT po.*,s.name AS supplier_name,COUNT(poi.id) AS item_count FROM purchase_orders po LEFT JOIN suppliers s ON s.id=po.supplier_id LEFT JOIN purchase_order_items poi ON poi.purchase_order_id=po.id GROUP BY po.id ORDER BY po.created_at DESC").fetchall()
        return [dict(r) for r in orders]


def update_purchase_order_status(order_id: int, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    with connect() as con:
        order = con.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise ValueError("Purchase order not found")
        status = order["status"]
        if action == "approve":
            if status != "draft":
                raise ValueError("Only draft orders can be approved")
            con.execute("UPDATE purchase_orders SET status='approved',approved_at=? WHERE id=?", (utc_now(), order_id))
        elif action == "send":
            if status not in {"approved", "draft"}:
                raise ValueError("Only draft or approved orders can be marked as sent")
            con.execute("UPDATE purchase_orders SET status='sent' WHERE id=?", (order_id,))
        elif action == "receive":
            if status not in {"approved", "sent", "partially_received"}:
                raise ValueError("Only approved or sent orders can be received")
            expiry_date = payload.get("expiry_date")
            if expiry_date:
                try:
                    date.fromisoformat(str(expiry_date))
                except ValueError:
                    raise ValueError("Expiry date must use YYYY-MM-DD")
            rows = con.execute("SELECT * FROM purchase_order_items WHERE purchase_order_id=?", (order_id,)).fetchall()
            received_any = False
            for item in rows:
                remaining = float(item["quantity"]) - float(item["received_quantity"])
                received = payload.get("received_quantities", {}).get(str(item["id"]), remaining)
                received = _positive(received, "Received quantity")
                if received > remaining + 1e-8:
                    raise ValueError("Received quantity cannot exceed the outstanding order quantity")
                if received:
                    received_any = True
                    add_stock_movement(con, item["product_id"], received, "purchase_received", f"Received on {order['order_number']}", item["unit_cost"], order["supplier_id"], expiry_date, "purchase_order", order_id)
                    con.execute("UPDATE purchase_order_items SET received_quantity=received_quantity+? WHERE id=?", (received, item["id"]))
            if not received_any:
                raise ValueError("Enter at least one quantity greater than zero")
            remaining_total = con.execute("SELECT SUM(quantity-received_quantity) FROM purchase_order_items WHERE purchase_order_id=?", (order_id,)).fetchone()[0] or 0
            new_status = "received" if remaining_total <= 1e-8 else "partially_received"
            con.execute("UPDATE purchase_orders SET status=?,received_at=? WHERE id=?", (new_status, utc_now() if new_status == "received" else None, order_id))
        elif action == "cancel":
            if status in {"received", "cancelled"}:
                raise ValueError("This order cannot be cancelled")
            con.execute("UPDATE purchase_orders SET status='cancelled' WHERE id=?", (order_id,))
        else:
            raise ValueError("Unsupported purchase order action")
        audit(con, f"purchase_order_{action}", f"{action.title()} order {order['order_number']}")
        return get_purchase_order(order_id, con)


def record_waste(payload: dict[str, Any]) -> dict[str, Any]:
    product_id = int(payload.get("product_id", 0))
    quantity = _positive(payload.get("quantity", 0), "Waste quantity", False)
    reason = str(payload.get("reason") or "Other")
    with connect() as con:
        product = con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise ValueError("Product not found")
        cost = quantity * float(product["unit_cost"])
        cur = con.execute("INSERT INTO waste_records(product_id,quantity,reason,estimated_cost,recorded_at,note) VALUES (?,?,?,?,?,?)", (product_id, quantity, reason, cost, utc_now(), payload.get("note", "")))
        add_stock_movement(con, product_id, -quantity, "waste", f"Waste: {reason}", reference_type="waste", reference_id=cur.lastrowid)
        audit(con, "waste_recorded", f"Recorded {quantity:g} {product['stock_unit']} waste for {product['name']}")
        return dict(con.execute("SELECT w.*,p.name AS product_name,p.stock_unit FROM waste_records w JOIN products p ON p.id=w.product_id WHERE w.id=?", (cur.lastrowid,)).fetchone())


def get_waste() -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT w.*,p.name AS product_name,p.stock_unit FROM waste_records w JOIN products p ON p.id=w.product_id ORDER BY recorded_at DESC LIMIT 200").fetchall()]


def get_analytics() -> dict[str, Any]:
    end = today()
    last_start = end - timedelta(days=6)
    prior_start = end - timedelta(days=13)
    prior_end = end - timedelta(days=7)
    with connect() as con:
        total = con.execute("SELECT COALESCE(SUM(s.total),0) AS revenue,COALESCE(SUM(s.quantity),0) AS units,COUNT(*) AS lines,COALESCE(SUM(s.quantity*p.unit_cost),0) AS estimated_cogs FROM sales s JOIN products p ON p.id=s.product_id WHERE s.sold_at>=? AND s.sold_at<=?", (last_start.isoformat(), end.isoformat())).fetchone()
        prior = con.execute("SELECT COALESCE(SUM(total),0) AS revenue FROM sales WHERE sold_at>=? AND sold_at<=?", (prior_start.isoformat(), prior_end.isoformat())).fetchone()
        best = con.execute("SELECT p.id,p.name,p.sku,p.stock_unit,SUM(s.quantity) AS quantity,SUM(s.total) AS revenue FROM sales s JOIN products p ON p.id=s.product_id WHERE s.sold_at>=? AND s.sold_at<=? GROUP BY p.id ORDER BY quantity DESC LIMIT 8", ((end-timedelta(days=27)).isoformat(), end.isoformat())).fetchall()
        days = con.execute("SELECT sold_at, SUM(total) AS revenue, SUM(quantity) AS units FROM sales WHERE sold_at>=? AND sold_at<=? GROUP BY sold_at ORDER BY sold_at", ((end-timedelta(days=13)).isoformat(), end.isoformat())).fetchall()
        slow = con.execute("SELECT p.id,p.name,p.sku,p.stock_unit,p.on_hand,COALESCE(SUM(s.quantity),0) AS sold_28d FROM products p LEFT JOIN sales s ON s.product_id=p.id AND s.sold_at>=? AND s.sold_at<=? WHERE p.active=1 GROUP BY p.id ORDER BY sold_28d ASC LIMIT 8", ((end-timedelta(days=27)).isoformat(), end.isoformat())).fetchall()
        waste = con.execute("SELECT COALESCE(SUM(estimated_cost),0) AS cost,COALESCE(SUM(quantity),0) AS quantity FROM waste_records WHERE recorded_at>=?", ((end-timedelta(days=27)).isoformat(),)).fetchone()
        revenue = float(total["revenue"])
        previous_revenue = float(prior["revenue"])
        change = ((revenue - previous_revenue) / previous_revenue * 100) if previous_revenue else None
        return {
            "period_days": 7, "revenue_7d": round(revenue, 2), "revenue_previous_7d": round(previous_revenue, 2),
            "revenue_change_pct": round(change, 1) if change is not None else None,
            "units_7d": round(float(total["units"]), 2), "sales_lines_7d": int(total["lines"]),
            "estimated_cogs_7d": round(float(total["estimated_cogs"]), 2),
            "estimated_gross_profit_7d": round(float(total["revenue"])-float(total["estimated_cogs"]), 2),
            "best_sellers_28d": [dict(r) for r in best], "slow_movers_28d": [dict(r) for r in slow],
            "daily": [dict(r) for r in days], "waste_cost_28d": round(float(waste["cost"]), 2),
            "waste_quantity_28d": round(float(waste["quantity"]), 2),
        }


def get_summary() -> dict[str, Any]:
    settings = get_settings()
    products = list_products()
    recommendations = get_recommendations()
    analytics = get_analytics()
    today_iso = today().isoformat()
    with connect() as con:
        value = sum(p["on_hand"] * p["unit_cost"] for p in products)
        low = [p for p in products if p["on_hand"] <= p["min_stock"] and p["on_hand"] > 0]
        empty = [p for p in products if p["on_hand"] <= 1e-9]
        expiring = con.execute("SELECT b.*,p.name AS product_name,p.stock_unit FROM stock_batches b JOIN products p ON p.id=b.product_id WHERE b.quantity_remaining>0 AND b.expiry_date IS NOT NULL AND b.expiry_date<=? ORDER BY b.expiry_date LIMIT 20", ((today()+timedelta(days=3)).isoformat(),)).fetchall()
        imports = con.execute("SELECT * FROM sales_imports ORDER BY imported_at DESC LIMIT 5").fetchall()
        activity = con.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 8").fetchall()
        pending_orders = con.execute("SELECT COUNT(*) FROM purchase_orders WHERE status IN ('draft','approved','sent','partially_received')").fetchone()[0]
        sales_count = con.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        order_needed = [r for r in recommendations if r["recommended_quantity"] > 0]
        return {
            "business_name": settings.get("business_name", "My Butcher Shop"), "currency": settings.get("currency", "USD"),
            "product_count": len(products), "inventory_value": round(value, 2), "low_stock_count": len(low),
            "out_of_stock_count": len(empty), "suggested_order_count": len(order_needed),
            "suggested_order_value": round(sum(r["estimated_cost"] for r in order_needed), 2),
            "pending_orders": pending_orders, "sales_rows": sales_count,
            "low_stock": low[:8], "out_of_stock": empty[:8], "expiring_batches": [dict(r) for r in expiring],
            "recent_imports": [dict(r) for r in imports], "recent_activity": [dict(r) for r in activity],
            "analytics": analytics, "recommendations": recommendations[:8], "today": today_iso,
        }


def assistant_answer(question: str) -> dict[str, Any]:
    q = (question or "").strip().lower()
    if not q:
        raise ValueError("Please enter a question")
    analytics = get_analytics()
    recs = get_recommendations()
    products = list_products()
    currency = get_settings().get("currency", "USD")
    if any(k in q for k in ["best seller", "popular", "most sold", "selling most", "top product"]):
        items = analytics["best_sellers_28d"][:5]
        if not items:
            answer = "I don't have sales history yet. Import a sales CSV or Excel file to identify your best sellers."
        else:
            answer = "Your top sellers over the last 28 days are: " + "; ".join(f"{x['name']} ({x['quantity']:.1f} {x['stock_unit']})" for x in items) + "."
        return {"answer": answer, "source": "sales database", "data": items}
    if any(k in q for k in ["slow", "least", "not selling", "low demand"]):
        items = [x for x in analytics["slow_movers_28d"] if x["sold_28d"] <= 3][:5]
        answer = "Products with the lowest recorded sales in the last 28 days: " + "; ".join(f"{x['name']} ({x['sold_28d']:.1f} sold, {x['on_hand']:.1f} in stock)" for x in items) + "." if items else "No clear slow movers were found, or more sales history is needed."
        return {"answer": answer, "source": "sales database", "data": items}
    if any(k in q for k in ["order", "buy", "purchase", "reorder", "restock"]):
        items = [x for x in recs if x["recommended_quantity"] > 0][:10]
        if items:
            answer = "Based on recorded demand, stock, incoming orders and supplier pack sizes, consider ordering: " + "; ".join(f"{x['product']}: {x['recommended_quantity']:g} {x['stock_unit']} from {x['supplier_name']}" for x in items) + ". Review the quantities before placing orders."
        else:
            answer = "No purchase quantities are currently recommended. Some products may need more sales history or configured minimum stock levels."
        return {"answer": answer, "source": "forecast and purchasing rules", "data": items}
    if any(k in q for k in ["stock", "left", "inventory", "available", "run out", "stockout", "running out"]):
        matched = [p for p in products if p["name"].lower() in q or p["sku"].lower() in q]
        if matched:
            answer = "; ".join(f"{p['name']}: {p['on_hand']:g} {p['stock_unit']} on hand; minimum stock {p['min_stock']:g}." for p in matched)
            return {"answer": answer, "source": "inventory database", "data": matched}
        low = sorted(products, key=lambda p: p["on_hand"] - p["min_stock"])[:8]
        answer = "Current stock levels: " + "; ".join(f"{p['name']} {p['on_hand']:g} {p['stock_unit']}" for p in low) + "."
        return {"answer": answer, "source": "inventory database", "data": low}
    if any(k in q for k in ["waste", "discard", "expired"]):
        answer = f"Recorded waste over the last 28 days: {analytics['waste_quantity_28d']:.2f} units across products, with an estimated cost of {currency} {analytics['waste_cost_28d']:.2f}. Make sure all discarded stock is recorded for this figure to be useful."
        return {"answer": answer, "source": "waste records", "data": {"quantity": analytics["waste_quantity_28d"], "estimated_cost": analytics["waste_cost_28d"]}}
    if any(k in q for k in ["revenue", "sales", "made", "turnover"]):
        answer = f"Recorded revenue for the last 7 days is {currency} {analytics['revenue_7d']:.2f}, compared with {currency} {analytics['revenue_previous_7d']:.2f} in the previous 7 days."
        if analytics["revenue_change_pct"] is not None:
            answer += f" That's a {analytics['revenue_change_pct']:+.1f}% change."
        return {"answer": answer, "source": "sales database", "data": analytics}
    return {"answer": "I can answer questions about best sellers, slow-moving products, current stock, purchase recommendations, recorded waste and recent sales. Try asking: 'What should I order next week?'", "source": "CutPilot business data", "data": None}


def get_movements(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT m.*,p.name AS product_name,p.stock_unit FROM stock_movements m JOIN products p ON p.id=m.product_id ORDER BY m.created_at DESC LIMIT ?", (min(max(limit, 1), 500),)).fetchall()
        return [dict(r) for r in rows]


def get_imports() -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM sales_imports ORDER BY imported_at DESC LIMIT 50").fetchall()]


def seed_demo_data() -> dict[str, Any]:
    """Create a deterministic, clearly labelled demo shop dataset once."""
    with connect() as con:
        existing = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if existing:
            return {"seeded": False, "message": "This workspace already contains products. Demo data was not added."}
        products = [
            ("Chicken Breast", "CHK-001", "Poultry", "kg", 6, 10, 3.2, 12.5, 28),
            ("Ground Beef", "BEEF-001", "Beef", "kg", 5, 5, 6.8, 16.0, 26),
            ("Lamb Chops", "LAMB-001", "Lamb", "kg", 4, 5, 10.5, 25.0, 16),
            ("Beef Steak", "BEEF-002", "Beef", "kg", 6, 5, 8.8, 22.0, 20),
            ("Chicken Wings", "CHK-002", "Poultry", "kg", 8, 10, 2.5, 8.5, 22),
            ("Beef Ribs", "BEEF-003", "Beef", "kg", 3, 5, 7.0, 18.0, 5),
            ("Turkey Breast", "TUR-001", "Poultry", "kg", 3, 5, 5.8, 15.0, 9),
            ("Sausages", "SAU-001", "Prepared", "kg", 5, 5, 4.0, 11.0, 18),
        ]
        ids = {}
        for name, sku, category, unit, minimum, pack, cost, price, opening in products:
            cur = con.execute("INSERT INTO products(name,sku,category,stock_unit,purchase_unit,min_stock,pack_size,unit_cost,unit_price,shelf_life_days,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (name, sku, category, unit, unit, minimum, pack, cost, price, 3, utc_now()))
            ids[sku] = cur.lastrowid
            add_stock_movement(con, cur.lastrowid, opening, "opening_stock", "Demo opening inventory", cost, expiry_date=(today()+timedelta(days=5)).isoformat())
        supplier_specs = [
            ("Fresh Farm Meats", "orders@freshfarm.example", 2, "Primary meat supplier"),
            ("Prime Poultry Co.", "sales@primepoultry.example", 1, "Poultry specialist"),
        ]
        supplier_ids = []
        for name, email, lead, note in supplier_specs:
            cur = con.execute("INSERT INTO suppliers(name,email,lead_time_days,notes,created_at) VALUES (?,?,?,?,?)", (name, email, lead, note, utc_now()))
            supplier_ids.append(cur.lastrowid)
        for sku in ids:
            sid = supplier_ids[1] if sku.startswith(("CHK", "TUR")) else supplier_ids[0]
            product = con.execute("SELECT id,unit_cost FROM products WHERE sku=?", (sku,)).fetchone()
            con.execute("INSERT INTO supplier_products(supplier_id,product_id,unit_cost,lead_time_days,minimum_quantity) VALUES (?,?,?,?,?)", (sid, product["id"], product["unit_cost"], 1 if sid == supplier_ids[1] else 2, 0))
        # 70 days of repeatable demo demand, with weekday and trend variation.
        end = today() - timedelta(days=1)
        base_daily = {"CHK-001": 3.1, "BEEF-001": 2.7, "LAMB-001": 1.25, "BEEF-002": 2.0, "CHK-002": 2.4, "BEEF-003": 0.35, "TUR-001": 0.8, "SAU-001": 1.7}
        weekday_factor = [0.82, 0.9, 1.0, 1.12, 1.45, 1.55, 1.15]
        for day_offset in range(70, 0, -1):
            d = end - timedelta(days=day_offset-1)
            trend = 0.88 + (70-day_offset) * 0.003
            for sku, base in base_daily.items():
                factor = weekday_factor[d.weekday()]
                qty = round(max(0.1, base * factor * trend * (1 + 0.09 * math.sin(day_offset * 1.7 + ids[sku]))), 2)
                price = con.execute("SELECT unit_price,id FROM products WHERE sku=?", (sku,)).fetchone()
                row_key = hashlib.sha256(f"demo|{d.isoformat()}|{sku}|{day_offset}".encode()).hexdigest()
                con.execute("INSERT INTO sales(product_id,sold_at,quantity,unit_price,total,external_sale_id,row_key,stock_deducted) VALUES (?,?,?,?,?,?,?,0)", (price["id"], d.isoformat(), qty, price["unit_price"], round(qty*price["unit_price"],2), f"DEMO-{d.strftime('%y%m%d')}-{sku}", row_key))
        # A few demo waste events, not deducted from opening stock (historical records).
        for sku, qty, reason, days_ago in [("BEEF-003", 0.8, "Slow-moving stock", 2), ("CHK-002", 0.4, "Handling loss", 5)]:
            product = con.execute("SELECT id,unit_cost FROM products WHERE sku=?", (sku,)).fetchone()
            con.execute("INSERT INTO waste_records(product_id,quantity,reason,estimated_cost,recorded_at,note) VALUES (?,?,?,?,?,?)", (product["id"], qty, reason, qty*product["unit_cost"], (datetime.now(timezone.utc)-timedelta(days=days_ago)).isoformat(), "Demo record"))
        audit(con, "demo_data_loaded", "Loaded sample butcher shop data (demo records)")
        return {"seeded": True, "message": "Demo workspace loaded with 8 products, 2 suppliers and 70 days of sample sales."}


def export_sales_csv() -> str:
    with connect() as con:
        rows = con.execute("SELECT s.sold_at,p.sku,p.name,s.quantity,p.stock_unit,s.unit_price,s.total,s.external_sale_id FROM sales s JOIN products p ON p.id=s.product_id ORDER BY s.sold_at").fetchall()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["date", "sku", "product", "quantity", "unit", "unit_price", "total", "sale_id"])
        for r in rows:
            writer.writerow(list(r))
        return out.getvalue()


def export_purchase_order_csv(order_id: int) -> str:
    order = get_purchase_order(order_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["order_number", "supplier", "status", "expected_delivery", "sku", "product", "purchase_quantity", "purchase_unit", "stock_quantity", "stock_unit", "unit_cost_per_stock_unit", "line_total", "currency"])
    for item in order["items"]:
        # Purchase quantity is displayed in supplier-facing units; stock quantity remains the inventory base unit.
        conversion = float(item["conversion_factor"] or 1)
        writer.writerow([order["order_number"], order.get("supplier_name") or "", order["status"], order.get("expected_delivery") or "", item["sku"], item["product_name"], round(float(item["quantity"])/conversion, 3), item["purchase_unit"], item["quantity"], item["stock_unit"], item["unit_cost"], item["line_total"], order["currency"]])
    return out.getvalue()

