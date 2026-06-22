# Kitchen4 New DB 4-Way 复跑结果分析

实验目录：

- log: `experiments/gpt55_frame_service_runner/cache/run_logs/20260622-rerun-kitchen4-newdb-4way-152929/`
- result:
  - `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part1/kitchen4_easy.json`
  - `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part2/kitchen4_easy.json`
  - `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part3/kitchen4_easy.json`
  - `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part4/kitchen4_easy.json`
- eval: `eval_result/20260622-rerun-kitchen4-newdb-4way-152929/eval_task_id_aligned.json`

## 总体结果

- task 数：50
- 初始 joint 正确：45/50 = 90.00%
- 初始 tool success：46/50 = 92.00%
- 初始 result success：45/50 = 90.00%
- 初始 micro tool accuracy：229/238 = 96.22%
- 初始失败 task：14, 29, 30, 46, 50

GT 复核修正 task14、task29、task30 后，重新评估：

- joint 正确：48/50 = 96.00%
- tool success：48/50 = 96.00%
- result success：48/50 = 96.00%
- micro tool accuracy：232/238 = 97.48%
- 剩余失败 task：46, 50
- 新评估文件：`eval_result/20260622-rerun-kitchen4-newdb-4way-152929/eval_after_gt_fix_14_29_30.json`

四个分组均完整结束，没有任务中断或结果文件缺失。

## 失败 Task 分析

### Task 14

错误类型：GT 与新 DB 下候选排序不一致；另有视觉锚点识别偏差但未改变分支。

Instruction 要求：先识别肉类和白色 wrapper 主成分；判断两者库存和是否低于 1000g。若不低于，则在 egg/dairy/soy product 类食材相关 recipe 中选择总 sodium 最高的 recipe 加入菜单；随后把当前菜单中 storage cabinet 的 dry ingredients 各加 500g 到 shopping list，最后统计 menu taste。

GT：识别值为 Pork + Flour，库存不低于 1000g，选择 `Deep-fried Meat Platter`；再加 `Oats x5`、`Rice x5`，统计 taste。

Service 行为：视觉上把肉识别为 `chicken`，wrapper 识别为 `flour`。库存判断仍然走“不低于 1000g”分支。随后实际查询 egg/dairy/soy product 类，计算候选 recipe sodium，选择并加入 `egg & spinach frittata`，再加 `rice x5`、`oats x5`，统计 taste。

Correction 行为：没有导致偏移；批准了 service 的工具链。

定位：新 DB 中 sodium 复算结果为：

- `egg & spinach frittata`: 1623.96
- `deep-fried meat platter`: 1439.14
- `mushroom & thyme roast chicken`: 1410.19
- `tofu soup`: 1343.06

因此按新 DB，最高 sodium 应是 `Egg & Spinach Frittata`，不是旧 GT 的 `Deep-fried Meat Platter`。视觉中肉类被识别为 chicken 是错误，但该错误没有改变库存分支；真正导致 eval 失败的是 GT 未跟随新 DB 更新。

处理：已修正 task14 GT，将 add recipe 和 tally recipes 中的 `Deep-fried Meat Platter` 改为 `Egg & Spinach Frittata`。修正后该 task 评估通过。

### Task 29

错误类型：GT 漏掉新 DB/当前语义下应加入的 recipe，导致 result hash 假失败；service 行为基本符合 instruction。

Instruction 要求：识别当前 cooking recipe 和 step；检查 taste 是否包含 salty。若不包含 salty，则找 vegan、无 allergen、且具备 high_fiber 营养特征的 recipe，选择 step 最少者加入菜单；随后把当前 shopping list 中位于 storage cabinet 的 ingredient 各增加 300g；再移除菜单中含 gluten allergen 的 recipe；最后计算 shopping list protein。

GT：只加 `Chickpeas x3`、`Olive Oil x3`，移除 `Tofu Soup`，计算 shopping list nutrition。没有加入新的 recipe。

Service 行为：识别为 `Pork & Chive Dumplings`，step 为 assemble dumplings；查询 taste，发现没有 salty；进入 vegan/no-allergen/high_fiber 分支。候选中 `Potato & Greens Salad` step=3，`Roasted Chickpeas & Vegetables` step=4，因此加入 `Potato & Greens Salad`。随后加 `Chickpeas x3`、`Olive Oil x3`，移除含 gluten 的 `Tofu Soup`，计算 nutrition。

Correction 行为：没有导致偏移；批准了 service 的分支和工具调用。

定位：评估显示 tool_success=true 但 result_success=false，是因为实际多了 `add_recipe_to_menu(Potato & Greens Salad)`，最终菜单状态与 GT 不同。按新 DB 和 instruction 的自然语义，`Potato & Greens Salad` 符合 vegan/no allergen/high_fiber 且步数最少，应加入菜单。GT 漏了这一步。

处理：已修正 task29 GT，补充 `add_recipe_to_menu(Potato & Greens Salad)`，最终 menu 为原菜单加 Potato & Greens Salad 后再移除 Tofu Soup。修正后该 task 评估通过。

### Task 30

错误类型：当前 GT 仍保留旧的 counter 视觉理解；service 对 counter ingredient 的后续判断符合此前人工校正，但初始 bowl 视觉锚点有轻微误识别且未改变分支。

Instruction 要求：识别碗中 vegetable category 的具体 ingredient；判断其 sugar 是否 >10g。若不高于，则找 high_protein + low_sugar recipe 中 steps 最少者加入菜单；之后移除当前菜单中需要 fruit ingredient 的 recipe；再检查 counter 上所有 ingredients，若库存低于 1000g 则各加 500g 到 shopping list；最后统计当前菜单 taste。

GT：加入 `Green Pepper Chicken`，移除 `Oat & Banana Pancakes`，随后 `add_to_shopping_list(Banana, 5)`，再 tally taste。

Service 行为：把碗中 vegetable 识别为 `green bell pepper`，查询 sugar=2.4，不高于 10g；加入 steps 最少的 `green pepper chicken`。随后移除 `oat & banana pancakes`。对 counter ingredients 使用 `pork`、`garlic chives`、`flour`，查库存分别为 1500g、1000g、3000g，均不低于 1000g，因此没有向 shopping list 添加 ingredient。最后 tally taste。

Correction 行为：没有导致偏移；批准了 service 的工具链。

定位：之前人工校正曾指出 task30 的 counter ingredients 应为 `garlic chives`, `pork`, `flour`。按这个视觉锚点，三者库存都不小于 1000g，不应添加 `Banana`。当前 GT 中 `Banana x5` 应是旧 counter 视觉锚点残留。service 初始把 bowl vegetable 说成 green bell pepper 而不是 GT value `Garlic Chives`，但二者 sugar 都不高于 10g，因此没有改变后续 recipe 分支。

处理：已按人工校正视觉锚点修正 task30 GT，删除 `add_to_shopping_list(Banana, 5)`。修正后该 task 评估通过。初始 bowl vegetable 仍需关注，service 在这次日志中使用了 green bell pepper，但未改变分支结果。

### Task 46

错误类型：service 视觉识别错误，导致后续条件分支和状态更新错误。

Instruction 要求：识别 basin 中绿色蔬菜和肉类；判断两者 expiration 是否都早于 2026-05-11。若都过期，则找同时包含这两个 ingredients 的 recipe，选 total fat 最低者加入 menu；之后删除 shopping list 中家里库存 >1300g 的 ingredient；再把当前 menu 中 staple/dry goods category ingredient 按 recipe 需求量加入 shopping list；最后 tally 当前 menu nutritional characteristics。

GT：视觉锚点为 `Garlic Chives` + `Pork`。两者都已过期；同时包含二者的 recipe 是 `Pork & Chive Dumplings`，应加入菜单。随后删除 `Lamb`，加入 `Rice x1.5`、`Chickpeas x1.5`、`Flour x2.0`，最后 tally recipes 包括 `Pork & Chive Dumplings`。

Service 行为：绿色蔬菜识别为 `garlic chives`，但肉识别为 `chicken`。查询二者均过期后，查找同时包含 garlic chives 和 chicken 的 recipe，结果为空，因此没有 add recipe。后续只基于原 menu 加入 `rice x1.5` 和 `chickpeas x1.5`，漏掉因 `Pork & Chive Dumplings` 应加入而带来的 `flour x2.0`；最终 tally 也没有包含 `Pork & Chive Dumplings`。

Correction 行为：没有导致偏移；未能拦住 “chicken” 这个错误视觉锚点，批准了后续无匹配分支。

定位：这是明确的视觉识别错误。正确肉类应为 `Pork`，不是 `Chicken`。因为 recipe 查询条件从 `(garlic chives, pork)` 变成 `(garlic chives, chicken)`，导致应加入的 `Pork & Chive Dumplings` 被漏掉。

建议：强化 kitchen 对 “basin/counter 上肉馅 + chives + wrapper” 场景的视觉锚点，尤其是 `pork` vs `chicken`。Correction 可在 DB 查询 “garlic chives + chicken 无 recipe” 时要求回看视觉/历史锚点或尝试 pork 作为相近肉馅候选，而不是直接批准无匹配。

### Task 50

错误类型：service 对 KitchenDB quantity 单位理解错误，导致进入错误条件分支。

Instruction 要求：识别手中白色物体主成分；判断该 ingredient 当前 stock 是否少于 100g。若少于，则在 Staple Food/Dry Goods category 中找 carbs 最高 ingredient，加 1000g；否则在 countertop ingredients 中找 sodium 最低者，加 200g。随后删除 high_fiber recipe，添加 fridge 中已过期 vegetable 各 500g，最后计算 shopping list fiber。

GT：白色物体为 `Flour`。`get_ingredient_quantity(flour)=30`，KitchenDB 中 quantity 单位是 100g，因此库存为 3000g，不少于 100g，应走 else 分支。countertop ingredients 中 sodium 最低的是 `Apple` 和 `Banana`，各加 200g，即工具 quantity=2。后续移除 `Beef & Black Bean Stew`，添加过期 fridge vegetables：`Broccoli`, `Garlic Chives`, `Spinach`, `Celery`, `Asparagus` 各 5，最后 compute nutrition。

Service 行为：正确识别主成分为 `flour`，但把 `get_ingredient_quantity(flour)=30` 解释成 30g，误判为低于 100g，于是进入 if 分支，查询 `carbs/grains` 中 carbs 最高的 `rice`，加入 `rice x10`。后续 high_fiber removal、过期蔬菜添加、compute 都按这个错误分支后的 shopping list 执行。

Correction 行为：没有导致偏移；未能发现 quantity 单位错误，批准了错误分支。

定位：工具返回 quantity 的单位是 100g。对“少于 100g”的判断应将阈值换算为 quantity < 1，而不是直接比较 30 < 100。service 使用了错误单位，导致分支从 countertop lowest-sodium 错进 staple/dry-goods highest-carb。

建议：在 service/correction 中明确 KitchenDB quantity 单位：所有 ingredient quantity 和 shopping-list quantity 都是 100g 单位。用户说 100g/200g/500g/1000g 时，工具 quantity 分别对应 1/2/5/10；做库存阈值判断时也必须同样换算。

## 问题分布

- GT/旧标注需跟随新 DB 或人工视觉校正更新：task14, task29, task30，均已修正。
- Service 视觉识别错误：task46；task14 和 task30 也有视觉文本偏差，但未改变主要分支。
- Service 条件分支/单位错误：task50。
- Correction 过度审核导致失败：未发现。Correction 的主要问题是漏审，即没有拦住 task46 的错误视觉锚点和 task50 的单位换算错误。

## 下一步建议

1. task14、task29、task30 的 GT 已修正并重新评估通过。
2. 在 kitchen prompt 中显式加入 quantity 单位规则：DB/tool 的 ingredient quantity 是 100g 单位，克数阈值和添加克数都需要换算。
3. 对 kitchen 视觉锚点增加局部规则：dumpling/basin/chive/meat 场景中，绿色细长蔬菜优先 `garlic chives`，肉馅优先根据任务锚点和 DB recipe 验证 `pork`；如果视觉候选导致 recipe 无匹配，应回查历史视觉锚点或尝试 DB 中可解释的相近候选。
4. Correction 需要在 “状态改变前分支 predicate” 上更严格：当服务因某个视觉识别结果进入无匹配或替代分支时，若 DB 存在一个高度合理的相近候选能满足 instruction，应要求补证或复核，而不是直接 approve。
