# CutPilot v1.8 — CutPilot · Butcher Intelligence

CutPilot is an inventory and purchasing assistant for independent butcher shops. It includes the friendly 3D cow identity, teal/navy light and dark themes, product/sales CSV/Excel/simple XML import workflows, sales analytics, demand forecasts, stock and waste tracking, purchase orders, and public and in-app pricing pages.

> **Deployment status:** Local preview remains the default (`CUTPILOT_MODE=local`) and uses one SQLite workspace. This release also adds a hosted account pilot (`CUTPILOT_MODE=saas`) with owner registration, sign-in/out, email verification, password reset, and one separate SQLite workspace database per butcher business. The hosted pilot needs a paid persistent-storage hosting service and SMTP setup. Billing/checkout is not active. The per-business SQLite layout is an early single-instance beta bridge, not a scale-ready PostgreSQL architecture; complete the security and hosting checklist before accepting real customer data.

## What's new in v1.8

- Added a public CutPilot marketing website at `/` and public pricing at `/pricing` when hosted SaaS mode is enabled.
- Kept the in-app **Plans & pricing** section.
- Added owner registration, sign-in, sign-out, email verification and password-reset flows.
- Added scrypt password hashing, expiring hashed session tokens, HttpOnly/SameSite cookies, basic login/registration rate limiting and same-origin checks.
- Each new butcher business gets a separate SQLite workspace database. Authenticated API requests resolve the workspace from the server-side session, not a browser-supplied organization ID.
- Added a Render Blueprint with a persistent disk and private SMTP environment variables for an early hosted pilot.
- Added local SaaS account testing instructions and hosted setup documentation.
- Pricing is a proposal only. Checkout, recurring billing, payment webhooks and payouts are not activated.
- Added draft privacy and terms pages that require professional review before a public commercial launch.

## What's new in v1.7

- Replaced the aggressive bull mark with a friendly, smiling 3D cow mascot in a teal app tile.
- Added a compact sun/moon icon toggle for day and night modes. The first launch defaults to the original light design; the selected mode is saved in this browser.
- Restored the original navy, white and fresh teal visual identity; dark mode uses deep navy surfaces with mint highlights.

## What's new in v1.5

- Restored a dedicated **Plans & pricing** navigation page with proposed Starter ($29), Professional ($59) and Multi-location ($99+) price hypotheses. These are not active subscriptions or checkout.
- Product and sales import now support CSV, Excel `.xlsx`/`.xlsm` and the supplied simple row-based XML format.
- Both import flows show detected column mappings, let the user correct mappings, preview records and review row errors before confirmation.
- Added XML examples and a detailed import contract describing columns, units, row structure and data validation.
- Sales preview flags product names/SKUs that are not present in the product catalogue before import.
- Added a clear customer sales pitch and a recommended hosted account model in `docs/SELLING_CUTPILOT.md`.

## What's new in v1.4

- Added the earlier bull-head mascot and CutPilot AI wordmark.
- Introduced a dark graphite interface with crimson branding and matching marketing assets.


## Core functionality retained

- Existing butcher workflow: products, stock, sales imports, analytics, forecasting and purchase recommendations.
- Custom vector navigation icons and category illustrations (no default platform emoji for product/category icons).
- Simpler grouped navigation: Shop, Buying & Operations, Intelligence, Help and Settings.
- Improved responsive layout for the import page and smaller screens.
- Explicit **Local Preview** status so users do not mistake this prototype for the future hosted product.
- Settings now explains exactly where data is stored today and how customer cloud accounts are intended to work.
- Includes reusable SVG logo, app mark and social-ad preview artwork in `brand/`.
- Includes account/hosting architecture, payment-provider research, founder sign-up flow, butcher workflow and a 3-minute demo script in `docs/`.

## 1. Requirements

- Windows, macOS or Linux
- Python 3.10 or newer (3.11+ recommended)
- Chrome, Edge, Firefox or Safari
- `openpyxl` for Excel `.xlsx` imports

## 2. Run locally on Windows

1. Extract the ZIP.
2. Open the **inner `cutpilot` folder** in VS Code (the folder containing `app.py` and `requirements.txt`).
3. Open Terminal → New Terminal. Confirm the prompt is in that folder:

   ```powershell
   dir
   ```

   You should see `app.py`, `core.py`, `requirements.txt`, `static` and `samples`.

4. Install the dependency:

   ```powershell
   py -m pip install -r requirements.txt
   ```

5. Start the app:

   ```powershell
   py app.py
   ```

6. Open `http://127.0.0.1:8765` in your browser.
7. Keep the terminal open while using the app. Press `Ctrl+C` to stop it.

Or double-click `run.bat` from the extracted project folder.

### macOS / Linux

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Then visit `http://127.0.0.1:8765`.

## 3. Try the demo data

1. Open Overview.
2. To explore quickly, select **Load demo workspace**. It adds synthetic products, suppliers, opening stock and sales history.
3. Review Products & stock, Sales & profit, Buying suggestions and Purchase orders.
4. Try recording a waste entry and asking CutPilot a question.

**To test the two-file upload workflow instead:** use a fresh/empty local database and do not load the demo workspace first. Import `samples/butcher_products_sample.csv` in Import data (Step 1), then import `samples/butcher_sales_sample.csv` in Import data (Step 2). Leave stock deduction OFF for this historical sample. The 420 sample sales rows run from 19 Sep through 17 Nov 2026, so the recent revenue chart and 7-/28-day analysis populate.

The demo loader only works when the workspace has no products. To reset a disposable test install, stop the app and back up or delete `data/cutpilot.sqlite3` (plus any `-wal` / `-shm` files), then restart. Deleting this file permanently removes that local test database.

## 4. How the butcher uses CutPilot

### One-time setup

1. Open **Settings** and enter business name, currency and timezone.
2. Open **Import data** and download the Product CSV, Excel or XML template.
3. Fill out each product's name, SKU, category, stock unit, purchase unit, conversion factor, purchase cost, selling price, opening stock, minimum stock and pack size.
4. Import that product catalog. Review quantities and costs carefully.
5. Open **Suppliers**, add supplier details and link important products to their supplier, price and delivery lead time.

### Each day

1. Export item-level daily transactions from the shop's existing POS/till.
2. Open **Import data** and upload the sales CSV/Excel/XML export.
3. Review the detected date, SKU/product, quantity and price rows.
4. Confirm the import.
5. Open Overview or Sales & profit to review revenue and estimated gross profit.

If the POS cannot export sales, the butcher can use the included sales spreadsheet template and record one row per product sold.

### When a delivery arrives

Open **Products & stock** or **Purchase orders**, record the actual quantity received and the expiry date when known. Do not count an order as on-hand stock before it physically arrives.

### When stock is wasted

Open **Waste & expiry**, select the product, quantity and reason, then save. This creates a stock movement and updates inventory.

### Before the next supplier order

Open **Buying suggestions**, recalculate the forecast, review the recommended quantities and explanation, select products and create draft purchase orders. CutPilot does not automatically contact suppliers or place orders.

## 5. Product file vs sales file

These files have different purposes and must not be mixed:

- **Product catalog:** what the shop sells, its SKU, purchase cost, selling price, purchase pack, minimum level and starting stock. Upload at setup and when the product catalog/costs change.
- **Sales history:** what customers bought, the sale date, product/SKU, quantity and selling price. Upload daily or whenever a POS export is available.

Product rows establish the opening stock. Sales rows build demand and revenue history. Historical sales must not be deducted from current stock a second time. Leave the stock-deduction option off for historical imports; only enable it for current sales that have not already been reflected in stock.

Unknown products encountered in a sales import may be created with zero costs and stock. Review and complete those product records before relying on profitability or reorder recommendations.

## 6. Financial numbers

- **Revenue:** total sale amounts recorded in imported sales rows.
- **Estimated gross profit:** revenue less quantity multiplied by the recorded product unit cost. This is an estimate, not net profit or formal accounting profit.
- **Inventory value:** current on-hand quantity multiplied by recorded product purchase cost.

The estimates exclude expenses such as wages, rent, electricity, taxes, payment fees and other operating costs. Keep product purchase costs up to date.

## 7. Files and useful references

- `samples/butcher_products_sample.csv` / `.xlsx` — sample product catalog
- `samples/butcher_sales_sample.csv` / `.xlsx` — fictional sample sales history (420 lines across 60 recent days, ending 17 Nov 2026)
- `samples/sales_import_template.csv` / `.xlsx` — blank sales-entry template
- `samples/butcher_products_template.xml` — supported simple XML product-catalogue example
- `samples/butcher_sales_template.xml` — supported simple XML sales example
- `docs/IMPORT_FILE_SPECIFICATION.md` — required/optional import fields, aliases, row rules, units, XML shape and validation
- `docs/SELLING_CUTPILOT.md` — customer pitch, hosted-vs-local recommendation and pricing experiments
- `docs/WHAT_EACH_SECTION_DOES.md` — each app section and the butcher's daily workflow
- `docs/SAAS_ARCHITECTURE.md` — account model, hosting choice, tenant isolation, security and launch plan
- `static/account-model.html` — in-app explanation of local vs hosted customer use
- `brand/cutpilot-logo.svg` / `.png` — main logo
- `brand/cutpilot-symbol.png` — transparent abstract symbol
- `brand/cutpilot-mark.svg` / `.png` — icon/app mark
- `brand/social-preview.svg` / `.png` — social/advertising preview artwork

## 8. Where local data is stored

The app creates `data/cutpilot.sqlite3` on first run. This file is the source of truth for this local test workspace. Stop the app before copying it for backup. Do not send a database containing real business records to anyone without permission.

The app binds to `127.0.0.1` by default. Do not expose this local server to the public internet or change the host to `0.0.0.0` for customer use.

## 9. Account mode and hosted SaaS — important

Version 1.8 adds an early account pilot. To test it locally, set `CUTPILOT_MODE=saas` and use a separate `CUTPILOT_DATA_DIR`; see `docs/HOSTED_SAAS_SETUP.md`. Owners can register, verify email (or disable verification only in a local test), sign in and receive a separate SQLite workspace database file. Two-account isolation is covered by tests.

The normal `CUTPILOT_MODE=local` remains a single local workspace for product demonstrations. It is not the customer account mode.

The supplied `render.yaml` is a starting template for a single-instance hosted pilot with persistent disk and SMTP. It has not been deployed for you. Before a public launch, a responsible adult/business owner must configure the hosting account, domain, transactional email and secrets. The SQLite-per-tenant design is an early pilot bridge; move to managed PostgreSQL and complete production security review before scaling or accepting sensitive business data.

The public site and Plans & pricing page are included. Prices are proposals only: no checkout, recurring billing, payment webhooks or payouts are active. Read `docs/HOSTED_SAAS_SETUP.md`, `docs/SAAS_ARCHITECTURE.md` and `docs/GETTING_PAID_AND_SIGNUPS.md`. Use `docs/DEMO_SCRIPT.md` for a truthful demo; it distinguishes the local product demo from the local account-flow test and a future hosted pilot.

## Brand assets

- `brand/cutpilot-mark.svg` / `.png` — friendly cow app icon and favicon.
- `brand/cutpilot-logo.svg` / `.png` — horizontal CutPilot wordmark.
- `brand/social-preview.svg` / `.png` — social sharing / ad preview.
- `static/premium.css` — foundational premium surfaces; `static/themes.css` adds the teal/navy light and dark appearance system.

The friendly teal cow mascot is the current visual identity for CutPilot. Local mode remains single-workspace; hosted pilot mode adds owner accounts and isolated per-business SQLite workspaces. Checkout and recurring payments are still disabled.

## Design previews carried forward from v1.4

The `previews/` directory contains interface reference images and synthetic demo views. They are design references, not screenshots from a customer's live shop.
