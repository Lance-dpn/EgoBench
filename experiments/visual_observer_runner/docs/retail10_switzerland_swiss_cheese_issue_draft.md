# Issue draft: retail10 cart product typo causes DB/GT mismatch

## Summary

In `retail_init_data10`, two user cart entries use `switzerland switzerland swiss cheese`, but the product catalog contains `switzerland swiss cheese`.

This creates a mismatch between the initial user carts, product lookup tools, and generated/evaluated ground truth for retail10 tasks.

## Affected data

File:

- `code/track2/EgoBench/tools/retail/retail_init.py`

Affected entries:

- `retail_init_data10.user_carts`, `user_123`, quantity `1`
- `retail_init_data10.user_carts`, `user_456`, quantity `2`

Current typo:

```text
switzerland switzerland swiss cheese
```

Expected canonical product:

```text
switzerland swiss cheese
```

## Why this matters

The misspelled cart item is not matched against the product catalog during retail DB initialization. As a result, `get_cart` can expose a cart item with missing product metadata such as default price/category/tax fields, while product-level tools such as `get_price` and aggregate compute tools only work correctly with the canonical product name.

This can make evaluation ambiguous:

- If the GT includes the misspelled name, official tools may fail to compute it correctly.
- If the GT excludes the item because it is not in DB, a service agent that faithfully reasons from the user cart may be penalized.
- If the GT is regenerated after correcting the DB, aggregate tasks should include `Switzerland Swiss Cheese` consistently.

## Minimal reproduction

```python
from tools.retail.retail_db import RetailDB
from tools.retail.retail_init import retail_init_data10

db = RetailDB()
db.init_from_json(retail_init_data10)

print(db.get_cart("user_123"))
print(db.get_price("switzerland swiss cheese"))
print(db.compute_total_nutrition(
    "user_123",
    [{"product_name": "switzerland switzerland swiss cheese", "quantity": 1}],
))
```

The cart contains `switzerland switzerland swiss cheese`, while the catalog lookup succeeds for `switzerland swiss cheese`.

## Suggested fix

Update both initial cart entries:

```diff
- "product_name": "switzerland switzerland swiss cheese"
+ "product_name": "switzerland swiss cheese"
```

Then regenerate affected retail10 GT so the aggregate product lists consistently use:

```text
Switzerland Swiss Cheese
```

## Local validation

After applying the correction locally:

- `get_price("switzerland swiss cheese")` returns price `19.8`.
- `get_cart("user_123")` returns `switzerland swiss cheese` with category `cheese`, price `19.8`, tax rate `0.08`, and discount `1.0`.
- A retail10 smoke evaluation result that previously suffered from this mismatch improved after regenerating GT with the corrected DB.
