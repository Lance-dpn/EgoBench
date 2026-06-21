# restaurant5 GT v1 audit

Source files:
- Scenario: `scenarios/final/restaurant5.json`
- Video: `videos/restaurant5.mp4`
- DB seed: `tools/restaurant/restaurant_init.py::restaurant_init_data5`
- Evaluator: `analysis_scripts/evaluate_interaction.py`

Video mapping used for the six left-menu visual drinks:
- `T`: top-left drink, cinnamon/rectangular garnish, dark horizontal middle band.
- `H`: top-middle drink, red strip across the cup rim, slender grass/rosemary leaves.
- `E`: top-right stemmed cocktail, orange lower half and white upper half.
- `F`: bottom-left drink, rectangular bread/biscuit on the rim.
- `U`: bottom-middle drink, dark long thin diagonal stirrer/rod.
- `R`: bottom-right drink, whole dark citrus slice in the cup.

Evaluation interpretation:
- Ground truth records state-changing order operations plus explicit final aggregate calculations.
- Visual/query-only checks used only to choose a branch are not recorded unless the instruction explicitly asks for an aggregate calculation as the requested output.
- `largest discount` is interpreted as the greatest markdown, i.e. the lowest `discount` factor, matching existing restaurant GT usage.
- `discount factor` comparisons use the stored `discount` value directly.
- `drink` excludes `Tiramisu` and `Cheesecake`; `Affogato` is treated as a drink/dessert option when an instruction asks broadly for drinks/options containing egg allergens.
- `dessert` is interpreted through dessert-like items in the restaurant5 DB, chiefly `Tiramisu`, `Cheesecake`, and, where allergen/filter wording is broad, `Affogato`.
- `gluten-free`, `dairy-free`, `alcohol-free`, and `nut-free` mean absence of that allergen in the DB allergen list.
- `zero-sugar`, `low-calorie`, `low-sodium`, `high-protein`, etc. mean the corresponding nutritional tag in `nutritional_characteristics`, unless the instruction explicitly asks for a numeric nutrient threshold.

Validation performed:
- Added `ground_truth` to all 50 `restaurant5` tasks.
- Constructed an interaction log using the exact generated GT calls.
- Ran `evaluate_interaction_success(..., scenario="restaurant", scenario_number=5)`.
- Result: 50/50 valid tasks, 50/50 tool success, 50/50 result hash success, 50/50 joint success.

Manual review update:
- Reviewed all 50 tasks against the video mapping, `restaurant_init_data5`, and branch logic.
- Found and fixed one error in task 39: `White Tea` was tied with `Oolong Tea` and `Jasmine Tea` for the lowest calories among sweet, nut-free items, so it must be added with quantity 2 and included in the final nutrition calculation.
- After the fix, the GT contains 169 calls across 50 tasks.
- Follow-up: corrected task 8's stored visual anchor `value` from the later bottom-right drink `R` to the initial stemmed cocktail `E`; the reviewed GT operations already matched the `E, then R` branch logic below.
- Follow-up after local DB normalization: `restaurant_init_data5` now uses
  `low_calories` for `F`, so `low_calorie` is empty and `low_calories` contains
  `F` plus the existing low-calorie tea/coffee items. Rechecked and updated
  affected tasks 11, 22, 24, 27, 33, and 48. Current GT contains 168 calls
  across 50 tasks.

Per-task review summary:

| task | visual item(s) | branch outcome | reviewed GT outcome |
| --- | --- | --- | --- |
| 1 | H, then T | H protein is not >4; T calories not <100 | add `Latte`; compute nutrition |
| 2 | F, then E | F is not bitter; E is not in a set meal | add `F`; compute nutrition |
| 3 | U, then F | U discount <0.8; F is not in a set meal; total payment >80 | add `White Tea`, `Jasmine Tea`; remove `Cheesecake` |
| 4 | T, then H | T is sugar-free; H carbs !=0 | add `Flat White`; compute payment |
| 5 | E, then R | E fat is 10, not >10; order item count is not <2 | add `H`; compute nutrition |
| 6 | U, then H | U has no alcohol allergen; H calories not <150 | add `Black Tea` x2 and `Oolong Tea` x2; compute tax |
| 7 | T, then F | T sugar is not <5; F is not in a combo | add non-dairy largest-discount tied items `H`, `E`, `F`, `Cold Brew`, `White Tea`, `Green Tea`, `Matcha`; compute nutrition |
| 8 | E, then R | E has high-protein tag; R discount !=0.8 | add `Cold Brew`; compute nutrition |
| 9 | F, then U | F has no alcohol allergen; total tax is not <5 | add `Black Tea`, `Oolong Tea`; compute tax |
| 10 | R, then H | R calories not <60; H is not in a set meal | add `Cheesecake`; compute nutrition |
| 11 | H, then R | H price not >20; among `low_calories`, `Matcha` has the highest protein; non-set payment is not <30 | add `Matcha` |
| 12 | U, then E | U contains dairy; E carbs !=0 | add `F`, `Cold Brew`; compute nutrition |
| 13 | T, then F | T calories >150; F is not in a combo | add six 2-kcal teas: `White Tea`, `Green Tea`, `Black Tea`, `Oolong Tea`, `Jasmine Tea`, `Earl Grey`; compute payment |
| 14 | R, then H | R lacks high-sugar tag; sugar total >40; H has discount | add `H`, remove `H`, add `H` |
| 15 | F, then T | F is dairy-free; T is not in a combo | add `Matcha`; compute nutrition |
| 16 | H, then R | H is not bitter; R is not in a combo | add `Matcha`; compute tax |
| 17 | F, then R | F lacks high-fiber tag; R is not in a set meal | add `Chai Tea`; compute nutrition |
| 18 | E, then H | E has low-sugar tag; H price <30 | add `Latte`, `Mocha`, `Affogato`, `H`; compute nutrition |
| 19 | T, then U | T discount !=1.0; U is not in a set meal | add `H`; no matching original-price aggregate tool exists |
| 20 | U, then T | U calories not >200; T discount <0.85 | add `Cheesecake`, add `T` x2; compute nutrition |
| 21 | T, then E | T lacks high-sugar tag; E discount <0.9 | add `Espresso`, add `E` x2; compute tax |
| 22 | U, then E | U has no alcohol allergen; all `low_calories` candidates tie at 0 fat; E is not in a set meal | add `F`, `Espresso`, `Americano`, `Cold Brew`, `White Tea`, `Green Tea`, `Black Tea`, `Oolong Tea`, `Jasmine Tea`, `Earl Grey`, `Matcha`; compute payment |
| 23 | F, then H | F has no dairy allergen; H is not in a set meal | add `Cheesecake`; compute nutrition |
| 24 | H, then U | H has no nut allergen; among `low_calories`, `Espresso` has the lowest sodium; sodium total is not <100 | add `Espresso`; compute nutrition |
| 25 | E, then F | E lacks low-calorie tag; F is not in a set meal; highest carbs is `Tiramisu` | add `F`; remove `Tiramisu`; compute nutrition |
| 26 | R, then F | R is not dairy-free; F is not in a combo | add `Espresso`; compute nutrition |
| 27 | E, then H | E lacks high-calcium tag; largest discount among `low_calories` ties at discount 0.8; non-set payment >50 | add `F`, `Cold Brew`, `White Tea`, `Green Tea`, `Matcha`, then `H` |
| 28 | T, then U | T sodium <50; tax total >15 | add `Cold Brew`, `White Tea`, `Green Tea`, `Matcha`, `U`; remove `Matcha` |
| 29 | U, then H | U is not bitter; H discount <0.9 | add `Cheesecake`, `H`; compute nutrition |
| 30 | F, then H | F is not in a combo; H discount <1.0 | add `Cheesecake`, `H`; compute tax |
| 31 | E, then F | E has high-protein tag; F price <25 | add `F`, then another `F`; compute nutrition |
| 32 | U, then E | U protein not >3; E has high-protein tag | add `Cheesecake`, `E`; compute nutrition |
| 33 | F, then R | F discounted price <25; among dairy-free `low_calories`, `Matcha` has the highest protein; R is not in a combo | add `Matcha`, `R`; compute tax |
| 34 | R, then E | R has no nut allergen; E x3 discounted total <60 | add `T` x2, `E` x3; compute tax |
| 35 | T, then E | T sugar not >30; E carbs-sugar difference is 10, not >10 | add `H`; compute payment |
| 36 | U, then U | U lacks no-additives tag; half of U calories is not <50 | add `Americano`, `Cold Brew`; compute nutrition |
| 37 | H, then R | H is not in a set meal; R x5 pre-tax total <100 | add `Tiramisu`, `R` x5; compute nutrition |
| 38 | F, then T/F | F calories <120; abs(price(T)-price(F)) <15 | add `H`, `T`, `F`; compute nutrition |
| 39 | T, then H | T contains dairy; H x2 total price <50 | add `White Tea` x2, `Oolong Tea` x2, `Jasmine Tea` x2, `H` x2; compute nutrition |
| 40 | R, then T | R price not >68; T saved amount not >5 | add `Tiramisu`; compute tax |
| 41 | E, then R | E is bitter; R single-item tax <2 | add `H`, `R`; compute payment and nutrition |
| 42 | F, then E | F protein not >10; E calories/protein ratio not <20 | add `Affogato`; compute tax |
| 43 | U, then H | U discount !=1.0; remaining budget is not enough for H x2 | add six 2-kcal teas; compute nutrition |
| 44 | F, then F | F is gluten-free; F price is below average of store min/max | add `Americano`, `F` x5; compute tax and payment |
| 45 | U, then U | U calories !=0; U*0.85 is not below actual discounted price | add `Espresso`; compute nutrition |
| 46 | U, then T | U calories >100; T has discount | add `Espresso`, `T`; compute payment |
| 47 | E, then T | E has low-sugar tag; T price <30 | add `Matcha`, `T`; compute payment |
| 48 | F, then T | F saved amount not >5; among `low_calories`, `Matcha` has the highest protein; T is not in a set meal | add `Matcha` x5; compute tax and payment |
| 49 | E, then H | E price not >60; floor((max price-min price)/10)=7 | add `Tiramisu`, `H` x7; compute payment |
| 50 | T, then R | T carbs not <5; abs(R protein-fat)=5.2, not <5 | add six 2-kcal teas; compute nutrition |

Backup:
- The official no-GT file was saved before overwrite at `/tmp/restaurant5.no_gt.backup.json`.
