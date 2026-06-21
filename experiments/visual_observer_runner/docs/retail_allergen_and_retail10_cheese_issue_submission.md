# Track2 Retail: allergen fields are not queryable, and retail10 has a product-name typo

## Summary

While testing Track2 retail tasks, I found two data/tool issues that can make otherwise reasonable service-agent behavior hard to evaluate reliably:

1. Retail products contain `allergens` in the DB, but the released retail tools do not expose any read-only way to query this field.
2. `retail_init_data10` contains two cart entries named `switzerland switzerland swiss cheese`, while the catalog product is `switzerland swiss cheese`.

I checked these against the current `main` branch of `ego-link/egolink2026`.

## 1. Retail allergen data exists but cannot be queried

The retail DB schema stores allergen data:

- `tools/retail/retail_db.py`
  - `Product.allergens`
  - `init_from_json(...): allergens=product_info.get("allergens", [])`

The product init data also contains `allergens` for products.

However, the public retail tool list does not include a read-only allergen query such as:

- `get_allergens(product_name)`
- `find_products_by_allergen(allergen)`
- `get_product_details(product_name)` including allergens

The only exposed tool schema field named `allergens` appears under `add_product`, which is a mutation tool, not a query tool.

### Current query tool outputs

I checked the concrete implementations in `tools/retail/retail_db.py`. The current read/query tools return only these fields:

- `find_products_by_nutritional_characteristic`: product names only
- `find_products_by_taste`: product names only
- `find_products_by_country_of_origin`: product names only
- `find_products_by_price_range`: product names only
- `get_price`: `product_name`, `price`
- `get_tax_rate`: `product_name`, `tax_rate`
- `get_category`: `product_name`, `category`
- `get_discount`: `product_name`, `discount`
- `get_nutrition`: `product_name`, `nutrition`
- `list_discounted_products`: product names only
- `get_cart`: product name, quantity, category, price, tax rate, discount
- `get_shopping_list`: product name, quantity
- `compute_total_payment`, `compute_total_tax`, `compute_total_nutrition`: aggregate results and processed item details

None of these exposes `allergens`.

### Why this matters

Some retail instructions require decisions based on allergens, for example:

> search for cookies containing the "nuts" allergen

The DB contains the answer, but the service agent cannot access it through the official read-only tools. In our testing, this led to a failure mode where the agent either had to:

- guess from product names, which is not reliable or tool-grounded,
- refuse/stop because no allergen lookup exists,
- or accidentally use non-official knowledge outside the tool interface.

For example, in `retail6` task 5, the expected branch requires finding cookies with the `nut` allergen and discount `< 0.85`; the DB supports `Grisbi Nocciola` as the qualifying item, but the official tool interface does not provide a way to verify that allergen condition.

### Suggested fix

Please consider exposing allergen information through a read-only tool, for example:

```json
{
  "tool_name": "get_allergens",
  "parameters": {
    "product_name": "string"
  }
}
```

and/or:

```json
{
  "tool_name": "find_products_by_allergen",
  "parameters": {
    "allergen": "string"
  }
}
```

This would make allergen-based tasks tool-grounded and reproducible.

## 2. retail10 contains `switzerland switzerland swiss cheese`

In the current `main` branch, `tools/retail/retail_init.py` contains:

```text
switzerland switzerland swiss cheese
```

at two `retail_init_data10.user_carts` entries:

- `user_123`, quantity `1`
- `user_456`, quantity `2`

But the canonical catalog product is:

```text
switzerland swiss cheese
```

### Why this matters

Because the cart item name does not match the catalog key, `get_cart` can return an item with missing/default metadata, and aggregate compute tools can skip it or return `partial_success`.

This affects tasks that compute totals over carts containing this item. Depending on whether the GT includes the typo, excludes the item, or uses the canonical product name, evaluation can become inconsistent.

### Suggested fix

Replace both initial cart entries:

```diff
- "product_name": "switzerland switzerland swiss cheese"
+ "product_name": "switzerland swiss cheese"
```

Then regenerate affected retail10 GT so all final aggregate calls consistently use:

```text
Switzerland Swiss Cheese
```

## Closing note

These issues are not about adding extra agent capability. They affect whether the official tool interface can support the conditions already present in the released tasks and whether DB/GT evaluation remains consistent.
