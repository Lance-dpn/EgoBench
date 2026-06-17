# Improve and Clarify Fuzzy Name Matching for Visual/OCR-Like Names in Track 2 Tools

Hi EgoLink team,

I would like to ask whether the Track 2 tool layer could further improve and clarify the current fuzzy matching behavior for product, dish, set-meal, recipe, and ingredient names, especially for names inferred from visual observations.

In the current implementation, some tools describe name lookup as fuzzy matching, but the actual behavior appears to be bidirectional substring matching only. For example, in `tools/retail/retail_db.py`, `_find_matching_products()` matches when:

```python
query_lower in product_name_lower or product_name_lower in query_lower
```

Similar substring-based matching helpers are also used for dish and set-meal names in the order and restaurant tools. This works well for partial-keyword cases, such as querying `oyster` and matching `Merlot Oyster Bay`. However, it does not handle small OCR or visual-recognition spelling errors.

For kitchen tools, recipe and ingredient lookups appear to be mostly exact lower-case key matching. This is clear and deterministic, but it also means visually inferred recipe or ingredient names must already match the database spelling exactly.

## Concrete Example

One concrete example from the retail cheese scenario:

```text
DB product name: Bezza Lepadano cheese
Visual/OCR-like model output: Bezza Lepadino cheese
```

These two names differ by only one character, but `get_price("Bezza Lepadino cheese")` returns:

```json
{
  "status": "error",
  "message": "No matching products found for 'Bezza Lepadino cheese'."
}
```

whereas `get_price("Bezza Lepadano cheese")` correctly returns the product price.

This creates a practical issue for multimodal agents: the agent may visually identify almost the correct product name, but a small spelling or OCR deviation prevents it from canonicalizing the name through the official tools. The agent then cannot reliably continue with downstream tool calls such as price lookup, tax lookup, discount lookup, nutrition lookup, or cart operations.

The same issue can apply to dish names, set meal names, recipe names, and ingredient names when they are inferred from visual content rather than copied from a database response.

Would the team consider improving this fuzzy matching behavior across Track 2 tools, or alternatively providing explicit canonicalization tools for each scenario?

Examples of useful canonicalization tools could include:

- `canonicalize_product_name`
- `canonicalize_dish_name`
- `canonicalize_set_meal_name`
- `canonicalize_recipe_name`
- `canonicalize_ingredient_name`

These tools could return exact matches, high-confidence fuzzy matches, or candidate lists for ambiguous cases.

## Possible Implementation

A robust implementation could include the following steps:

1. Normalize names before matching:
   - lowercase
   - trim repeated spaces
   - remove punctuation
   - normalize accents, for example `Gruyere` and `Gruyère`

2. Preserve current exact and substring matching as the first priority.

3. If no substring match is found, perform a conservative similarity match, for example with edit distance or `SequenceMatcher`.

4. Use confidence thresholds:
   - high confidence, for example `>= 0.93`: return the unique canonical product
   - medium confidence, for example `0.86 - 0.93`: return candidate products, but do not treat them as confirmed
   - low confidence: return no match

5. Add ambiguity control:
   - only auto-match if the top candidate is clearly better than the second candidate
   - otherwise return candidates for the agent to disambiguate

6. Distinguish read-only and state-changing tools:
   - read-only tools such as `get_price`, `get_tax_rate`, `get_discount`, `get_nutrition`, `get_dish_price`, `get_dish_allergens`, `get_recipe_taste`, and `get_ingredient_nutrition` can safely return high-confidence fuzzy matches
   - state-changing tools such as `add_to_cart`, `delete_product`, `add_dish_to_order`, `delete_dish_from_order`, `add_recipe_to_menu`, or `add_to_shopping_list` should be more conservative and only accept exact, substring, or unique high-confidence matches

7. Return match metadata when fuzzy matching is used, for example:

```json
{
  "products": [
    {
      "product_name": "bezza lepadano cheese",
      "price": 26.9,
      "match": {
        "query": "Bezza Lepadino cheese",
        "matched_by": "fuzzy",
        "score": 0.95
      }
    }
  ],
  "count": 1
}
```

This would help service agents consistently switch from visually inferred names to official canonical DB names for later tool calls.

For ambiguous cases, the tool could return candidate metadata without executing a state-changing operation:

```json
{
  "status": "ambiguous_match",
  "query": "Bezza Lapadino cheese",
  "candidates": [
    {
      "product_name": "bezza lepadano cheese",
      "score": 0.90,
      "matched_by": "fuzzy"
    }
  ]
}
```

## Why This Matters

Track 2 tasks often require an agent to bridge visual understanding and database tools. The visual model may infer a name from menu text, shelf labels, dish labels, or object appearance. Even when the semantic identification is nearly correct, small OCR-like errors can make the official tools return no match.

This has two effects:

1. It can make a correctly localized visual observation fail at the tool-canonicalization step.
2. It can force agents to implement their own unofficial canonicalization logic outside the tool layer, which may reduce benchmark consistency across participants.

Clearer and more robust tool-side canonicalization would make the benchmark focus more directly on the intended capabilities: visual grounding, tool use, and task reasoning.

If changing the tool behavior is not intended for the benchmark, it may still be helpful to clarify in the tool descriptions that the current "fuzzy matching" is substring-based rather than typo-tolerant. That clarification would help participants design agent-side canonicalization strategies more appropriately.

Thanks for considering this improvement.
