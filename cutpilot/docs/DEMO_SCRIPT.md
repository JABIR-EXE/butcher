# CutPilot v1.8 — 3-minute demo recording guide

Use only the included fictional sample files. The product walkthrough uses local preview mode. A separate account-flow segment can be recorded in local SaaS test mode; neither is a public hosted service.

## Prepare the demo

1. Extract the ZIP and open the inner `cutpilot` folder in VS Code.
2. Run `py -m pip install -r requirements.txt` once.
3. Start with `py app.py` and open `http://127.0.0.1:8765`.
4. Use a fresh empty workspace. Do not load demo workspace data if you plan to import the included sample files.
5. In **Products & stock**, use **Import products** and upload `samples/butcher_products_sample.csv`. Review the preview and confirm it.
6. Open **Import sales**, upload `samples/butcher_sales_sample.csv`, review the suggested column mapping, inspect the preview, and confirm. Keep historical stock deduction unchecked.

## Suggested screen recording (about 3 minutes)

### 0:00–0:20 — Introduce the problem

“Independent butcher shops need to know what is selling, what is in stock and what to reorder. CutPilot brings those checks into one dashboard.”

### 0:20–0:45 — Show the dashboard

Point out the sales/revenue summary, estimated gross profit, stock value and items that need attention. Explain that these are calculated from the imported sample data.

### 0:45–1:15 — Show products and stock

Open **Products & stock**. Show product names, SKUs, units, current stock, minimum stock and cost. Explain that the product catalogue is uploaded first because sales rows need to match known products.

### 1:15–1:45 — Show the sales import

Open **Import sales**. Explain that a butcher exports a CSV or Excel file from their existing till/POS. CutPilot detects likely columns, lets the owner correct the mapping, previews the rows and flags validation errors before saving.

### 1:45–2:20 — Show sales and profit

Open **Sales & profit**. Show the revenue trend, sold quantities and gross profit estimate. Explain that this is gross profit based on recorded sale prices and product costs, not net profit after rent, wages, utilities or tax.

### 2:20–2:50 — Show buying suggestions

Open **Buying suggestions**. Explain that CutPilot combines recent sales, current stock, incoming deliveries, supplier lead times, pack sizes and safety stock to propose an order. The butcher reviews and approves the order; CutPilot does not autonomously purchase meat.

### 2:50–3:00 — Explain availability

“The account pilot can create a separate owner login and private workspace for each shop. In this demo, the accounts are running locally for testing. Public hosting, production database migration and subscription billing still need to be completed before commercial onboarding.”

## Demo-safe wording

Say “suggests”, “estimates” and “helps the owner decide”. Do not claim guaranteed forecast accuracy, guaranteed savings, live supplier integration, employee invitations, a fully production-hardened public service or active subscription checkout. Owner account creation and per-shop data isolation exist in SaaS pilot mode, but the public hosted service still needs deployment and security review.


## Optional account-flow recording (about 1 minute)

Run the local SaaS test settings in `docs/HOSTED_SAAS_SETUP.md`. Open `/pricing`, then `/signup`, create a first fictional shop owner, sign out, register a second owner with a different email and shop name, and show that their product lists are separate. Be explicit that this is an account-flow test on your computer, not a live public subscription service. Do not show real personal data.
