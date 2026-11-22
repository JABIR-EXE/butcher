# CutPilot — what each section is for

This guide describes the butcher workflow in v1.8. Local preview has one shop; SaaS pilot mode adds one owner account and one isolated shop workspace per business. Employee invitations and multi-location workspaces are not included yet.

| Section | What the butcher does there | How often |
|---|---|---|
| Overview | Check sales, estimated gross profit, stock warnings and important next actions. | Daily |
| Products & stock | Add products, maintain SKUs, costs, selling prices, opening stock and reorder minimums. Receive deliveries and adjust physical counts. | Setup + when stock changes |
| Import data | Upload the product catalogue (setup or changes) and daily POS/till sales export. Auto-detected fields can be remapped; preview and correct row errors before importing. CSV, Excel and simple row-based XML are supported. | Products: setup/changes. Sales: daily |
| Sales & profit | See revenue trends, quantities sold, best sellers and estimated gross profit. | Daily / weekly |
| Buying suggestions | Recalculate the forecast and review which products may need replenishing and why. | Before ordering |
| Purchase orders | Turn selected suggestions into draft orders, approve them, record sent status and receive deliveries. | Each supplier order |
| Suppliers | Maintain supplier contacts, product costs, pack sizes and delivery lead times. | Setup + when details change |
| Waste & expiry | Record discarded quantities and review expiry risks. | Whenever waste occurs / daily |
| Ask CutPilot | Ask questions about already-recorded business data. The current rules-based assistant is read-only. | Whenever useful |
| Help & setup guide | Follow product setup, daily importing, delivery receiving and purchasing instructions. | During onboarding |
| Plans & pricing | Review proposed Starter, Professional and Multi-location prices. They are hypotheses, not live subscriptions or checkout. | Founder planning / customer discussions |
| Settings | Set shop name, currency, timezone, review period and forecast horizon. See the local-vs-hosted deployment status. | Setup + when changed |

## The butcher's real workflow

### Once when starting

1. Enter the shop profile and currency in Settings.
2. Open Import data and download the product CSV, Excel or simple XML template.
3. Fill in each SKU, category, stock unit, purchase unit, conversion factor, purchase cost, selling price, opening stock and minimum stock.
4. Import that product catalog. Check the stock values against the real shop stock.
5. Add suppliers and link key products to their supplier, delivery lead time and prices.

### Each day

1. At closing time, export the day's item-level transactions from the POS/till.
2. Upload the export in Import data.
3. Review the suggested date, product/SKU, quantity and price column mapping. Change any incorrect match, inspect the row preview and fix errors or unmatched products before confirmation.
4. For historical sales, keep stock deduction OFF. For today's sales only, turn it on only if the POS has not already reduced stock elsewhere.
5. Open Overview or Sales & profit to check revenue and gross profit estimate.

### Whenever a delivery arrives

1. Open Products & stock or Purchase orders.
2. Receive the actual delivered quantity, not the originally ordered quantity if the supplier delivered less.
3. Add an expiry date when known.
4. Verify on-hand stock moved up.

### Whenever stock is wasted

1. Open Waste & expiry.
2. Select the product, enter the quantity and reason.
3. Confirm it; inventory should decrease and the event should appear in the ledger.

### Before the next order

1. Open Buying suggestions and recalculate.
2. Read the forecast, on-hand stock, incoming stock, safety stock, supplier lead time and suggested pack-rounded quantity.
3. Select the items to buy and create draft purchase orders.
4. Review the supplier order. The app does not send or place orders automatically.

## Important interpretation notes

- **Revenue** is the sales amount in imported records, before costs and operating expenses.
- **Estimated gross profit** subtracts recorded product cost only. It is not accounting or net profit.
- **Inventory value** is based on recorded purchase cost and current on-hand quantity.
- If sales data has no price or total, revenue cannot be accurately calculated for those rows.
- Products created from unknown sales rows may have zero cost or zero opening stock; review them before trusting profit or buying calculations.
- Forecast quality depends on complete item-level sales history and accurate stock/supplier data.
- Do not deduct historical sales from current stock a second time.


## Import file essentials

- Product catalogue: **one row per product/SKU**. At minimum include `name`. Recommended: `sku`, `category`, `stock_unit`, `unit_cost`, `unit_price`, `opening_stock` and `min_stock`. This establishes the catalogue and initial stock.
- Sales history: **one row per product line sold**. Required: `date`, `quantity`, and either `product` or `sku`. Recommended: `unit`, `unit_price` or `line_total`, and `sale_id`. Do not upload a daily cash total with no product breakdown.
- Units must agree. If the product is measured in `kg`, the sales quantity must also be in `kg`. Convert units before importing; CutPilot does not silently convert lb, kg and pieces.
- The import wizard suggests columns based on their headings. If a POS uses different column names, choose the matching source heading from the dropdown. Always inspect the preview.
- Supported XML is the simple row-based structure shown in the included XML templates. Complex vendor-specific XML is not guaranteed to import directly.
- Header matching is deterministic alias matching, not an AI model. Forecasting and assistant answers are based on recorded shop data and deterministic business rules; the assistant does not invent sales or stock figures.
