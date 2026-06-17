# Restaurant GT Rebuild Diff Report

- Total tasks: 169
- Manual reviewed: 73
- Same as official after review: 57
- Review required: 16
- Pending manual rebuild: 96

## Review Required

- restaurant1 task 16: Official GT contains `Homemade pappardelle with bolognese sauce*`, which is not a DB dish name. The corrected trace removes the stray asterisk; quantity-halving semantics still need human review.
- restaurant1 task 18: Official GT adds Walnut bread after clearing the order but computes tax for `Handmade Bread`, which is a category name rather than a DB dish.
- restaurant1 task 36: Official GT misspells `Kalamata olives` as `Kalamata olives'` in compute_total_payment.
- restaurant2 task 2: Official GT likely selects Salmon & asparagus, but Italian Pasta savory lowest sodium by DB is Pesto. The official analysis field also conflicts with the instruction for the second add.
- restaurant2 task 8: Official GT uses Culatello, but if first pointed section is Cold Cuts and the instruction asks lowest price after discount among high-sodium dishes, Salame Milano has the lower discounted price.
- restaurant2 task 16: The visual category below Selected Steaks appears to be the Handmade Bread section, not Cheese & Olives. Since the found bread price is not above 80, only the final highest-calorie bread should be added.
- restaurant2 task 23: Instruction asks for smoked/salty dishes priced 600-700 in Selected Steaks, but DB taste profiles for the Selected Steaks candidates are savory/rich or savory/buttery, not smoked/salty. Official GT also follows an analysis field that changes the instruction wording.
- restaurant2 task 26: The official key/value identifies the bottom-left panel as Annie's top dishes, whose discounts are not lower than 0.8. Therefore the fallback branch should select Veggie salad from Salads, not Turkey breast ham from Cold Cuts.
- restaurant2 task 30: Instruction asks for a high-protein lowest-price dish in the third pointed category, which supports Bolognese. The later Sandwiches & Panini condition says salty and umami, but DB has no sandwich with both taste labels; official GT adds Tuna panini after the analysis rewrites the condition as salty-savory/umami.
- restaurant3 task 27: Official GT adds Baguette but later computes nutrition for `Handmade Bread`, which is a category name rather than a DB dish.
- restaurant4 task 5: Official GT has a user_id typo (`ustomer_002`) in add_dish_to_order; instruction and DB otherwise support the same action sequence.
- restaurant4 task 7: Instruction asks to calculate total tax, but official GT calls compute_total_payment. The visual/DB branch and added dish are otherwise supported.
- restaurant4 task 11: Salmone affumicato discount is 0.8, so the true branch is entered, but DB has no low-sugar Dessert item. Official GT instead adds a Pasta item and removes Margherita, which is not supported by the instruction branch.
- restaurant4 task 14: Official GT has a user_id typo (`ustomer_004`) in compute_total_tax; instruction and DB otherwise support the same dish addition.
- restaurant4 task 15: Salmone affumicato sodium is exactly 800mg, so it does not exceed 800mg. The fallback rich-flavor Annie top dish is Lasagne, not Mushroom soup.
- restaurant4 task 30: Official GT misspells `Salmon & asparagus` as `Salmon & asparagu` in the final compute_total_nutrition dish list.

## Pending

Tasks marked `pending_manual_rebuild` have not yet been treated as corrected GT.
