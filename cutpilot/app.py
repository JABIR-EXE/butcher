#!/usr/bin/env python3
"""CutPilot local web application server. Run with: python app.py"""
from __future__ import annotations

import base64
import csv
import io
import hashlib
import json
import mimetypes
import os
import re
import sys
import traceback
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlencode

import core
import auth

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
SAAS_MODE = os.environ.get("CUTPILOT_MODE", "local").lower() == "saas"
HOST = os.environ.get("CUTPILOT_HOST", "0.0.0.0" if SAAS_MODE else "127.0.0.1")
PORT = int(os.environ.get("PORT", os.environ.get("CUTPILOT_PORT", "8765")))
MAX_BODY = 15 * 1024 * 1024


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "CutPilot/1.8"
    _rate_lock = threading.Lock()
    _attempts: dict[str, list[float]] = {}

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _cookie_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            morsel = cookie.get(auth.SESSION_COOKIE)
            return morsel.value if morsel else None
        except Exception:
            return None

    def _session(self):
        return auth.get_session(self._cookie_token())

    def _cookie_header(self, token=None, max_age=0):
        secure = os.environ.get("CUTPILOT_COOKIE_SECURE", "1" if os.environ.get("RENDER") else "0") == "1"
        parts = [f"{auth.SESSION_COOKIE}={token or ''}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _send_auth_json(self, payload, status=200, token=None, max_age=0):
        self.send_bytes(json_bytes(payload), status, "application/json; charset=utf-8", {"Set-Cookie": self._cookie_header(token, max_age)})

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_page(self, filename):
        page = STATIC / filename
        if not page.is_file():
            return self.send_json({"error": "Page not found"}, 404)
        return self.send_bytes(page.read_bytes(), 200, "text/html; charset=utf-8")

    def _rate_limited(self, bucket, limit, window):
        now = time.time()
        key = f"{bucket}:{self.client_address[0]}"
        with self._rate_lock:
            recent = [stamp for stamp in self._attempts.get(key, []) if now - stamp < window]
            if len(recent) >= limit:
                self._attempts[key] = recent
                return True
            recent.append(now)
            self._attempts[key] = recent
            return False

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        expected = self.headers.get("X-Forwarded-Host", self.headers.get("Host", ""))
        return bool(expected and urlparse(origin).netloc.lower() == expected.lower())

    def _require_workspace(self):
        if not SAAS_MODE:
            return True
        session = self._session()
        if not session:
            self.send_json({"error": "Please sign in to access your business workspace."}, 401)
            return False
        core.set_active_db_path(session["db_path"])
        self._active_session = session
        return True

    def _handle_auth_post(self, path, body):
        if not SAAS_MODE:
            self.send_json({"error": "Customer accounts are not enabled in local preview. Switch CUTPILOT_MODE=saas for account testing."}, 403)
            return True
        if path == "/api/auth/register":
            if not SAAS_MODE:
                self.send_json({"error": "Customer accounts are available only in hosted SaaS mode. Local preview remains a single-shop demo."}, 403); return True
            if self._rate_limited("register", 5, 3600):
                self.send_json({"error": "Too many registration attempts. Try again later."}, 429); return True
            require_verify = os.environ.get("CUTPILOT_REQUIRE_EMAIL_VERIFICATION", "1") == "1"
            if require_verify and (not auth.smtp_ready() or not os.environ.get("CUTPILOT_BASE_URL")):
                self.send_json({"error": "Email verification requires SMTP settings and CUTPILOT_BASE_URL. Configure these before opening public signup."}, 503); return True
            try:
                account = auth.create_account(full_name=str(body.get("full_name") or ""), email=str(body.get("email") or ""),
                    password=str(body.get("password") or ""), business_name=str(body.get("business_name") or ""),
                    country=str(body.get("country") or ""), currency=str(body.get("currency") or "USD"), plan=str(body.get("plan") or "starter"))
                core.set_active_db_path(account["db_path"])
                try:
                    core.init_db()
                    core.update_settings({"business_name": account["business_name"], "currency": body.get("currency") or "USD"})
                finally:
                    core.clear_active_db_path()
                if require_verify:
                    token = auth.create_email_token(account["user_id"], "verify", 24)
                    base = os.environ.get("CUTPILOT_BASE_URL", "").rstrip("/")
                    verify_url = base + "/verify?" + urlencode({"token": token})
                    auth.send_email(account["email"], "Verify your CutPilot account", f"Hello {account['full_name']},\n\nVerify your CutPilot account using this link (valid for 24 hours):\n{verify_url}\n\nIf you did not create this account, ignore this email.")
                    return self.send_json({"ok": True, "verification_required": True, "message": "Check your email for the verification link."}, 201)
                auth.mark_email_verified(account["user_id"])
                token, _ = auth.create_session(account["user_id"], account["organization_id"])
                return self._send_auth_json({"ok": True, "message": "Account created.", "redirect": "/app"}, 201, token, auth.SESSION_DAYS * 86400)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except Exception:
                traceback.print_exc()
                return self.send_json({"error": "Could not create the account. Check email and hosting configuration."}, 500)
        if path == "/api/auth/login":
            if not SAAS_MODE:
                self.send_json({"error": "Sign-in is enabled in hosted SaaS mode. The local preview opens directly."}, 403); return True
            if self._rate_limited("login", 8, 900):
                self.send_json({"error": "Too many sign-in attempts. Wait 15 minutes and try again."}, 429); return True
            try:
                user = auth.authenticate(str(body.get("email") or ""), str(body.get("password") or ""))
                if not user:
                    return self.send_json({"error": "Email or password is incorrect."}, 401)
                token, _ = auth.create_session(user["user_id"], user["organization_id"])
                return self._send_auth_json({"ok": True, "redirect": "/app"}, 200, token, auth.SESSION_DAYS * 86400)
            except PermissionError as exc:
                return self.send_json({"error": str(exc)}, 403)
        if path == "/api/auth/logout":
            auth.delete_session(self._cookie_token())
            return self._send_auth_json({"ok": True}, 200, None, 0)
        if path == "/api/auth/forgot-password":
            email = str(body.get("email") or "").strip().lower()
            try:
                with auth.connect() as con:
                    row = con.execute("SELECT id,email,full_name FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
                if row and auth.smtp_ready():
                    token = auth.create_email_token(row["id"], "reset", 1)
                    base = os.environ.get("CUTPILOT_BASE_URL", "").rstrip("/")
                    link = base + "/reset?" + urlencode({"token": token})
                    auth.send_email(row["email"], "Reset your CutPilot password", f"Hello {row['full_name']},\n\nReset your password using this one-time link (valid for one hour):\n{link}\n\nIf you did not request this, ignore this email.")
                return self.send_json({"ok": True, "message": "If that account exists, password-reset instructions have been sent."})
            except Exception:
                traceback.print_exc()
                return self.send_json({"error": "Password reset email could not be sent. Contact support."}, 500)
        if path == "/api/auth/reset-password":
            new_password = str(body.get("password") or "")
            if len(new_password) < 12:
                return self.send_json({"error": "Use a password with at least 12 characters."}, 400)
            user_id = auth.consume_email_token(str(body.get("token") or ""), "reset")
            if not user_id:
                return self.send_json({"error": "This reset link is invalid or expired."}, 400)
            try:
                auth.reset_password(user_id, new_password)
                return self.send_json({"ok": True, "message": "Password updated. You can now sign in."})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        return False

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/health":
            return self.send_json({"ok": True, "app": "CutPilot", "version": "1.8.0", "mode": "saas" if SAAS_MODE else "local"})
        if path == "/api/config":
            return self.send_json({"mode": "saas" if SAAS_MODE else "local", "account_signup": SAAS_MODE,
                "email_verification": os.environ.get("CUTPILOT_REQUIRE_EMAIL_VERIFICATION", "1") == "1",
                "billing_enabled": False, "version": "1.8.0"})
        if path == "/api/auth/me":
            if not SAAS_MODE:
                return self.send_json({"authenticated": False, "mode": "local"})
            session = self._session()
            if not session:
                return self.send_json({"authenticated": False, "mode": "saas"}, 401)
            return self.send_json({"authenticated": True, "mode": "saas", "user": {k:v for k,v in session.items() if k != "db_path"}})
        if SAAS_MODE:
            if path == "/": return self._serve_page("marketing.html")
            if path == "/pricing": return self._serve_page("public-pricing.html")
            if path == "/privacy": return self._serve_page("privacy.html")
            if path == "/terms": return self._serve_page("terms.html")
            if path == "/login":
                if self._session(): return self._redirect("/app")
                return self._serve_page("login.html")
            if path == "/signup":
                if self._session(): return self._redirect("/app")
                return self._serve_page("signup.html")
            if path == "/forgot-password": return self._serve_page("forgot-password.html")
            if path == "/reset": return self._serve_page("reset-password.html")
            if path == "/verify":
                query = parse_qs(urlparse(self.path).query)
                user_id = auth.consume_email_token((query.get("token") or [""])[0], "verify")
                if not user_id: return self._serve_page("verify-invalid.html")
                auth.mark_email_verified(user_id)
                return self._serve_page("verify-success.html")
            if path == "/app":
                if not self._session(): return self._redirect("/login?next=%2Fapp")
                return self._serve_page("index.html")
        else:
            if path == "/": return self._serve_page("index.html")
            if path == "/pricing": return self._serve_page("public-pricing.html")
            if path == "/privacy": return self._serve_page("privacy.html")
            if path == "/terms": return self._serve_page("terms.html")
            if path == "/login": return self._serve_page("login.html")
            if path == "/signup": return self._serve_page("signup.html")
        private_api = path.startswith("/api/") and path not in {"/api/health", "/api/config", "/api/auth/me"}
        if SAAS_MODE and private_api and not self._require_workspace():
            return
        try:
            return self._do_GET()
        finally:
            core.clear_active_db_path()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self.read_json()
            if not self._same_origin():
                return self.send_json({"error": "Cross-origin request blocked."}, 403)
            if path.startswith("/api/auth/") and self._handle_auth_post(path, body):
                return
            if SAAS_MODE and path.startswith("/api/") and not self._require_workspace():
                return
            self._cached_json_body = body
            return self._do_POST()
        finally:
            core.clear_active_db_path()

    def do_PUT(self):
        path = urlparse(self.path).path
        try:
            if not self._same_origin(): return self.send_json({"error": "Cross-origin request blocked."}, 403)
            if SAAS_MODE and path.startswith("/api/") and not self._require_workspace(): return
            return self._do_PUT()
        finally:
            core.clear_active_db_path()

    def send_bytes(self, data: bytes, status=200, content_type="application/json; charset=utf-8", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200):
        self.send_bytes(json_bytes(value), status)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise ValueError("Request is too large. Maximum request size is 12 MB.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ValueError("Request body must be valid JSON")

    def _do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/health":
                return self.send_json({"ok": True, "app": "CutPilot", "version": "1.8.0", "mode": "saas" if SAAS_MODE else "local"})
            if path == "/api/summary":
                return self.send_json(core.get_summary())
            if path == "/api/products":
                return self.send_json(core.list_products())
            if path == "/api/suppliers":
                return self.send_json(core.list_suppliers())
            if path == "/api/analytics":
                return self.send_json(core.get_analytics())
            if path == "/api/recommendations":
                return self.send_json(core.get_recommendations())
            if path == "/api/purchase-orders":
                return self.send_json(core.list_purchase_orders())
            if path == "/api/waste":
                return self.send_json(core.get_waste())
            if path == "/api/movements":
                return self.send_json(core.get_movements())
            if path == "/api/imports":
                return self.send_json(core.get_imports())
            if path == "/api/settings":
                return self.send_json(core.get_settings())
            if path == "/api/forecasts":
                # Return the most recent persisted forecast run; generate one if none exists.
                with core.connect() as con:
                    run = con.execute("SELECT * FROM forecast_runs ORDER BY id DESC LIMIT 1").fetchone()
                    if not run:
                        result = core.run_forecasts()
                        return self.send_json(result)
                    forecasts = con.execute("SELECT d.*,p.name AS product,p.sku,p.stock_unit FROM demand_forecasts d JOIN products p ON p.id=d.product_id WHERE d.forecast_run_id=? ORDER BY p.name,d.forecast_date", (run["id"],)).fetchall()
                    return self.send_json({"run_id": run["id"], "horizon_days": run["horizon_days"], "created_at": run["created_at"], "method": run["method"], "forecasts": [dict(r) for r in forecasts]})
            if path.startswith("/api/purchase-orders/") and path.endswith("/export"):
                order_id = int(path.split("/")[3])
                data = core.export_purchase_order_csv(order_id).encode("utf-8")
                return self.send_bytes(data, 200, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="cutpilot-order-{order_id}.csv"'})
            order_match = re.fullmatch(r"/api/purchase-orders/(\d+)", path)
            if order_match:
                return self.send_json(core.get_purchase_order(int(order_match.group(1))))
            if path == "/api/export/sales":
                data = core.export_sales_csv().encode("utf-8")
                return self.send_bytes(data, 200, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="cutpilot-sales-export.csv"'})
            if path.startswith("/api/"):
                return self.send_json({"error": "API endpoint not found"}, 404)
            return self.serve_static(path)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            return self.send_json({"error": "The server encountered an unexpected error. Check the terminal for details."}, 500)

    def _do_POST(self):
        path = urlparse(self.path).path
        try:
            body = getattr(self, "_cached_json_body", None)
            if body is None:
                body = self.read_json()
            if path == "/api/products/import/preview":
                filename = str(body.get("filename") or "products.csv")
                encoded = body.get("content_base64")
                if not encoded:
                    raise ValueError("No product file was received")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except Exception:
                    raise ValueError("The uploaded product file could not be decoded")
                parsed = core.parse_product_file(filename, raw, body.get("mapping"))
                parsed["filename"] = filename
                parsed["file_hash"] = hashlib.sha256(raw).hexdigest()
                return self.send_json(parsed)
            if path == "/api/products/import/confirm":
                return self.send_json(core.import_products(body.get("rows") or [], bool(body.get("update_existing_stock", False))))
            if path == "/api/products/import":
                filename = str(body.get("filename") or "products.csv")
                encoded = body.get("content_base64")
                if not encoded:
                    raise ValueError("No product file was received")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    if filename.lower().endswith((".xlsx", ".xlsm")):
                        from openpyxl import load_workbook
                        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                        ws = wb.active
                        values = list(ws.iter_rows(values_only=True))
                        headers = [str(x or "").strip().lower() for x in values[0]]
                        records = [dict(zip(headers, row)) for row in values[1:]]
                    elif filename.lower().endswith(".csv"):
                        text = raw.decode("utf-8-sig")
                        records = list(csv.DictReader(io.StringIO(text)))
                        records = [{str(k or "").strip().lower(): v for k, v in row.items()} for row in records]
                    else:
                        raise ValueError("Choose a product CSV or Excel .xlsx file")
                except ValueError:
                    raise
                except Exception as exc:
                    raise ValueError(f"Could not read product file: {exc}")
                aliases = {"product":("product", "name", "product_name", "item"), "sku":("sku", "item_code", "code"), "category":("category", "type"), "stock_unit":("stock_unit", "unit", "uom"), "unit_cost":("unit_cost", "cost", "purchase_cost", "cost_per_unit"), "unit_price":("unit_price", "price", "selling_price", "sale_price"), "opening_stock":("opening_stock", "on_hand", "stock", "quantity"), "min_stock":("min_stock", "minimum_stock", "reorder_level"), "purchase_unit":("purchase_unit",), "conversion_factor":("conversion_factor", "purchase_to_stock_factor"), "pack_size":("pack_size", "order_multiple"), "shelf_life_days":("shelf_life_days",)}
                created = updated = skipped = 0
                for row in records:
                    norm = {str(k).strip().lower(): v for k, v in row.items()}
                    def pick(key, default=None):
                        return next((norm[a] for a in aliases[key] if a in norm and norm[a] not in (None, "")), default)
                    name = str(pick("product", "")).strip()
                    if not name:
                        skipped += 1; continue
                    payload = {"name": name, "sku": str(pick("sku", "")).strip(), "category": str(pick("category", "Uncategorized") or "Uncategorized"), "stock_unit": str(pick("stock_unit", "kg") or "kg"), "purchase_unit": str(pick("purchase_unit", pick("stock_unit", "kg")) or "kg"), "unit_cost": float(pick("unit_cost", 0) or 0), "unit_price": float(pick("unit_price", 0) or 0), "opening_stock": float(pick("opening_stock", 0) or 0), "min_stock": float(pick("min_stock", 0) or 0), "conversion_factor": float(pick("conversion_factor", 1) or 1), "pack_size": float(pick("pack_size", 1) or 1), "shelf_life_days": int(pick("shelf_life_days", 3) or 3)}
                    with core.connect() as con:
                        existing = con.execute("SELECT id FROM products WHERE sku=?", (payload["sku"],)).fetchone() if payload["sku"] else None
                    if existing:
                        core.update_product(int(existing["id"]), {k:v for k,v in payload.items() if k not in ("opening_stock", "name")})
                        updated += 1
                    else:
                        core.create_product(payload); created += 1
                return self.send_json({"created": created, "updated": updated, "skipped": skipped})
            if path == "/api/demo/seed":
                return self.send_json(core.seed_demo_data())
            if path == "/api/products":
                return self.send_json(core.create_product(body), 201)
            if path == "/api/suppliers":
                return self.send_json(core.create_supplier(body), 201)
            if path == "/api/supplier-products":
                return self.send_json(core.link_supplier_product(body), 201)
            if path == "/api/stock/adjust":
                return self.send_json(core.adjust_stock(body))
            if path == "/api/imports/preview":
                filename = str(body.get("filename") or "upload.csv")
                encoded = body.get("content_base64")
                if not encoded:
                    raise ValueError("No file content was received")
                try:
                    content = base64.b64decode(encoded, validate=True)
                except Exception:
                    raise ValueError("The uploaded file could not be decoded")
                parsed = core.parse_sales_file(filename, content, body.get("mapping"))
                parsed["filename"] = filename
                parsed["file_hash"] = hashlib.sha256(content).hexdigest()
                return self.send_json(parsed)
            if path == "/api/imports/confirm":
                return self.send_json(core.import_sales(str(body.get("filename") or "sales-import.csv"), str(body.get("file_hash") or ""), body.get("rows") or [], bool(body.get("apply_to_stock", False))))
            if path == "/api/forecasts/run":
                return self.send_json(core.run_forecasts(body.get("horizon_days")))
            if path == "/api/purchase-orders":
                return self.send_json(core.create_purchase_order(body), 201)
            if path.startswith("/api/purchase-orders/"):
                match = re.fullmatch(r"/api/purchase-orders/(\d+)/(approve|send|receive|cancel)", path)
                if match:
                    order_id, action = int(match.group(1)), match.group(2)
                    return self.send_json(core.update_purchase_order_status(order_id, action, body))
            if path == "/api/waste":
                return self.send_json(core.record_waste(body), 201)
            if path == "/api/assistant":
                return self.send_json(core.assistant_answer(str(body.get("question") or "")))
            return self.send_json({"error": "API endpoint not found"}, 404)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            return self.send_json({"error": "The server encountered an unexpected error. Check the terminal for details."}, 500)

    def _do_PUT(self):
        path = urlparse(self.path).path
        try:
            body = self.read_json()
            if path == "/api/settings":
                return self.send_json(core.update_settings(body))
            match = re.fullmatch(r"/api/products/(\d+)", path)
            if match:
                return self.send_json(core.update_product(int(match.group(1)), body))
            return self.send_json({"error": "API endpoint not found"}, 404)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception:
            traceback.print_exc()
            return self.send_json({"error": "The server encountered an unexpected error. Check the terminal for details."}, 500)

    def serve_static(self, path: str):
        if path in ("", "/"):
            file_path = STATIC / "index.html"
        elif path.startswith("/samples/"):
            relative = path[len("/samples/"):]
            file_path = (BASE / "samples" / relative).resolve()
            if (BASE / "samples").resolve() not in file_path.parents:
                return self.send_json({"error": "Not found"}, 404)
        else:
            relative = path.lstrip("/")
            file_path = (STATIC / relative).resolve()
            if STATIC.resolve() not in file_path.parents and file_path != STATIC.resolve():
                return self.send_json({"error": "Not found"}, 404)
        if not file_path.exists() or not file_path.is_file():
            return self.send_json({"error": "Not found"}, 404)
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        return self.send_bytes(file_path.read_bytes(), 200, content_type)


def main():
    if SAAS_MODE:
        auth.init_db()
        print("  Mode: HOSTED SAAS PILOT — isolated workspace databases")
        print("  Account database: " + str(auth.AUTH_DB))
    else:
        core.init_db()
        print("  Mode: LOCAL PREVIEW — single workspace, no customer accounts")
        print("  Local database: " + str(core.DB_PATH))
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("\n  CUTPILOT is running")
    print(f"  Bind address: {HOST}:{PORT}")
    if SAAS_MODE:
        print("  Public site: /  |  Pricing: /pricing  |  Sign up: /signup  |  App: /app")
    print("  Press Ctrl+C to stop the server.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CutPilot...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
