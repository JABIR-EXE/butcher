# CutPilot import file specification (v1.8)

CutPilot accepts **CSV**, **Excel `.xlsx` / `.xlsm`**, and **simple row-based XML** files up to 10 MB. CSV should be UTF-8. For Excel, the first worksheet is read and its first row is treated as the header row. XML must follow the supplied CutPilot structure: one `<products>` or `<sales>` root containing repeated `<product>` or `<sale>` elements with simple child fields. Complex POS-specific XML exports may need conversion to the template format.

The importer uses deterministic header-name matching (aliases) to suggest column mappings. It is not an AI model and does not guess missing values. The user can change each mapping in the review screen, inspect the row preview and review validation errors before confirming.

## Product catalogue file

**Purpose:** Set up or refresh the items the shop sells. Import it before sales history. Re-import when names, supplier costs, selling prices or product settings change. Opening stock is applied when a new SKU is created. For existing SKUs, current stock is preserved unless the owner explicitly selects the stock-update option.

One row = one product/SKU.

| CutPilot field | Required? | Example | Meaning |
|---|---|---|---|
| `name` | Yes | Chicken Breast | Customer-facing product name |
| `sku` | Recommended | CHK-001 | Stable unique shop SKU/barcode; generated from name if omitted |
| `category` | Optional | Poultry | Beef, Poultry, Lamb, Pork, Fish, Sausage, etc. |
| `stock_unit` | Recommended | kg | Base unit used for stock and sales: kg, piece, etc. Defaults to kg |
| `purchase_unit` | Optional | carton | Unit in which supplier sells it; defaults to stock unit |
| `conversion_factor` | Optional | 10 | Number of stock units in one purchase unit. Example: 1 carton = 10 kg |
| `unit_cost` | Recommended | 7.20 | Purchase cost per base stock unit (e.g. USD per kg), not necessarily per carton |
| `unit_price` | Recommended | 12.50 | Selling price per base stock unit (e.g. USD per kg) |
| `opening_stock` | Recommended at first setup | 24 | Physical stock currently on hand, in `stock_unit` |
| `min_stock` | Optional | 8 | Minimum desired stock, in `stock_unit` |
| `pack_size` | Optional | 2 | Purchase-unit order multiple. With 1 carton = 10 kg and pack size 2, reorder in 20 kg increments |
| `shelf_life_days` | Optional | 3 | Shelf-life planning value in days; default 3 |

Minimum product template:

```csv
name,sku,category,stock_unit,purchase_unit,conversion_factor,unit_cost,unit_price,opening_stock,min_stock,pack_size,shelf_life_days
Chicken Breast,CHK-001,Poultry,kg,kg,1,7.20,12.50,24,8,1,3
Ground Beef,BEEF-001,Beef,kg,kg,1,8.40,15.00,18,6,1,2
```

## Sales history file

**Purpose:** Record what customers bought so CutPilot can calculate revenue, sales trends, best sellers and demand forecasts. Upload after the product catalogue. Normally import daily POS exports or a chosen historical period once.

One row = one product line sold on a transaction/receipt. If one receipt has three different products, it should contain three item rows. If your POS export contains one row per item per day, that is also usable. Do not upload only a single daily shop revenue total; it does not identify product demand.

| CutPilot field | Required? | Example | Meaning |
|---|---|---|---|
| `date` | Yes | 2026-11-17 | Sale date; supported common formats include YYYY-MM-DD, DD/MM/YYYY and MM/DD/YYYY |
| `product` | Product name or SKU is required | Chicken Breast | Name matching the product catalogue |
| `sku` | Product name or SKU is required | CHK-001 | Exact product SKU/barcode; preferred because names can vary |
| `quantity` | Yes | 2.5 | Amount sold, expressed in the product's base stock unit |
| `unit` | Recommended | kg | Must match the product's `stock_unit`; CutPilot will not silently convert kg to pieces or lb |
| `unit_price` | Recommended | 12.50 | Selling price per base stock unit |
| `total` / `line_total` | Recommended | 31.25 | Total for this line. If unit price is blank, CutPilot derives it as line total divided by quantity |
| `sale_id` | Recommended | POS-1001 | Receipt/transaction reference to help identify duplicate imports |

Minimum sales template:

```csv
date,product,sku,quantity,unit,unit_price,line_total,sale_id
2026-11-17,Chicken Breast,CHK-001,2.5,kg,12.50,31.25,POS-1001
2026-11-17,Ground Beef,BEEF-001,1.2,kg,15.00,18.00,POS-1002
```

If both `unit_price` and `total` are missing, the sales row can be imported but its revenue will be zero. CutPilot does not invent a selling price. Add at least one of these columns for meaningful revenue and gross-profit estimates.

## Automatic matching and manual mapping

CutPilot automatically recognizes common alternatives, including:

- Date: `date`, `sold_at`, `saleDate`, `transaction_date`, `timestamp`
- Product: `product`, `product_name`, `item`, `description`, `item_name`
- SKU: `sku`, `product_code`, `item_code`, `barcode`, `PLU`
- Quantity: `quantity`, `qty`, `units`, `weight`, `net_weight`
- Price: `unit_price`, `price`, `sell_price`, `rate`
- Line total: `total`, `line_total`, `amount`, `net_amount`

For product catalogs, common matches include `name`, `item`, `product_description`, `cost_price`, `purchase_cost`, `retail_price`, `current_stock`, `on_hand`, `reorder_level` and `minimum_stock`.

If a POS export uses different names, choose the correct source column in the mapping dropdown. Required sales fields are sale date, quantity, and either product name or SKU. Product catalogue files require a product name. Check the preview before confirming.

## Validation and warnings

- Blank product names or invalid dates are rejected row by row.
- Quantity must be greater than zero.
- Cost, selling price and stock values cannot be negative.
- Conversion factor and supplier pack size must be greater than zero.
- A sales quantity unit that conflicts with the product's stock unit is rejected; no silent unit conversion is performed.
- Unknown sales SKUs/names are flagged before import. If the user continues, they may be created as products with zero stock and zero purchase cost; complete those products before trusting stock or profit figures.
- Historical sales imports should leave **Deduct these sales from current stock** unchecked. Only turn it on for sales that have not already been reflected in the stock balance.
- Re-importing the exact same sales file is blocked by its file hash. Receipt IDs also help protect against repeated rows.
- Updating a product catalogue does not overwrite existing stock by default. The optional stock-update checkbox is an explicit stocktake action, not recommended for routine price/catalogue refreshes.

## XML structure examples

See the included files:

- `samples/butcher_products_template.xml`
- `samples/butcher_sales_template.xml`

XML must look like this simple shape:

```xml
<products>
  <product>
    <name>Chicken Breast</name>
    <sku>CHK-001</sku>
    <stock_unit>kg</stock_unit>
  </product>
</products>
```

A deeply nested POS XML format or an XML document using an unrelated schema is not guaranteed to parse. Convert it to the supplied structure or use CSV/Excel export instead.
