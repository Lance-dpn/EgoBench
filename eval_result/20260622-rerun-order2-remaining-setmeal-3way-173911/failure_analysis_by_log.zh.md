# order2 剩余失败 task 三路复跑分析

## 基本信息

- 日志目录：`experiments/gpt55_frame_service_runner/cache/run_logs/20260622-rerun-order2-remaining-setmeal-3way-173911`
- 结果目录：
  - `results/20260622-rerun-order2-remaining-setmeal-3way-173911-order2-fps2-g1`
  - `results/20260622-rerun-order2-remaining-setmeal-3way-173911-order2-fps2-g2`
  - `results/20260622-rerun-order2-remaining-setmeal-3way-173911-order2-fps2-g3`
- 评估结果：`eval_result/20260622-rerun-order2-remaining-setmeal-3way-173911/eval_task_id_aligned.json`

## 总体结果

这轮复跑覆盖之前 order2 候选集中仍失败的 28 个 task。

| 指标 | 结果 |
|---|---:|
| Joint success | 4 / 28 = 14.29% |
| Tool success | 6 / 28 = 21.43% |
| Result success | 5 / 28 = 17.86% |
| Final reply | 28 / 28 = 100.00% |
| Micro tool accuracy | 38.98% |

按分组：

| 分组 | Task | Joint |
|---|---|---:|
| g1 | 5, 23, 33, 39, 54, 61, 69, 78, 87, 96 | 2 / 10 |
| g2 | 13, 28, 34, 41, 58, 63, 75, 82, 89 | 1 / 9 |
| g3 | 17, 32, 38, 48, 59, 64, 77, 86, 91 | 1 / 9 |

通过的 task：`23, 28, 38, 96`。

仍失败的 task：`5, 13, 17, 32, 33, 34, 39, 41, 48, 54, 58, 59, 61, 63, 64, 69, 75, 77, 78, 82, 86, 87, 89, 91`。

如果只把本轮 joint 通过的 4 个样本替换进当前候选集，order2 可从 69 / 97 提升到 73 / 97；五场景候选集整体 Joint 预计从 255 / 309 提升到 259 / 309。

## 逐 task 定位

### task 5

- Instruction 要求：先因下午茶甜点需求选择餐厅；识别第 3 展开页右下区域菜品营养。如果该菜 sodium < 400mg，则在 seafood 且 savory 的菜中按折后价最低添加；否则添加第 5 展开页右侧文本列表第 3 项两份；之后判断是否能组成 set meal，最后算含税总价和 fat。
- Service 行为：视觉识别为 `Greek Yogurt with Honey & Nuts`，sodium=50，因此进入 seafood/savory/lowest discounted price 分支，最后添加了 `fried calamari`。
- Correction 行为：第一次阻止了只查 Mediterranean 而直接比较 Butcher 的回复；之后又要求 lowest discounted price 必须用 `compute_total_payment` 验证。这些审核本身合理。
- GT 要求：添加 `Spaghetti Bolognese x2`，并按包含 `Mediterranean Feast Set` 的订单计算。
- 失败定位：核心是视觉锚点/分支进入不一致。Service 识别出的菜导致进入 sodium<400 分支；GT 进入了 else 分支。需要重新确认第 3 展开页右下区域真实菜品是不是 Greek Yogurt；若不是，则是视觉错误；若是，则 GT 明显可疑。

### task 13

- Instruction 要求：识别白盘上含乳制品、坚果和水果的菜品 allergen；如果含 nuts，则在 vegan plant-based 中选 protein 最高者加一份；否则在 high-calorie 中按最低价加两份；之后若订单内没有折扣菜，再加最低 sugar 菜；最后算 sodium 和 payable。
- Service 行为：识别为 `Greek Yogurt with Honey & Nuts`，allergens 为 dairy/nuts；进入 nuts 分支，枚举 vegan 菜营养，添加 `lentil soup x1`，再计算 sodium/payment。
- Correction 行为：只处理了一次 tool JSON 混入文本的问题，未导致主要偏移。
- GT 要求：添加 `Vanilla pudding x2` 和 `Loukoumades x2`，对应的是 else 分支。
- 失败定位：GT 可疑。按照 instruction 和工具结果，Greek Yogurt 明确含 nuts，应走 vegan/highest protein 分支；`lentil soup` protein=14，是 vegan 列表中最高。当前 GT 看起来走了“不含 nuts”的分支。

### task 17

- Instruction 要求：识别红色海鲜铜锅菜 allergen；若含 seafood，则在 high-protein 菜中找 fat 最低者加一份；之后若全单 sodium 按每 100g 计算超过 800mg，则删除非 set 菜中 sodium 最高者；最后算 payable 和 calories。
- Service 行为：识别为 `Grilled Octopus`，含 seafood；correction 纠正后添加了 `Tzatziki x1`。后续在 sodium 分支中没有稳定遵守 per-100g 口径，最终移除了 `Greek Village Roast Chicken Leg`，而 GT 需要移除 `Moussaka x2`。
- Correction 行为：先正确拒绝非最低 fat 的添加；之后围绕 per-serving 与 per-100g sodium 反复 reject，导致服务在多轮中摇摆，最终状态偏离。
- GT 要求：`add Tzatziki x1`，`remove Moussaka x2`，再 compute payment/nutrition。
- 失败定位：计算口径和 correction 反馈共同导致偏移。主要问题是 per-100g 聚合阈值与最终 compute 工具口径混用。

### task 32

- Instruction 要求：为肉食偏好选择餐厅；后续识别木板上烤蔬菜串菜品的隐藏/后台营养数据，并继续条件流程。
- Service 行为：选择并维持了 `Sunshine Bistro` 语境，但工具侧并不支持这个非完整餐厅名；后续在 Sunshine 上多次查 `Grilled Fish/Fish/Sea Bass` 失败，任务卡死，没有进入 GT 的后续分支。
- Correction 行为：持续要求不要把 Mediterranean 的数据当 Sunshine 数据，同时要求空结果后做 token retry。审核方向合理，但没有把任务拉回 GT 语境。
- GT 要求：基于 Mediterranean Greek Restaurant 的订单继续添加/移除/计算。
- 失败定位：餐厅选择和 DB 可用餐厅名冲突。这里可能是 service 餐厅选择错误，也可能是 instruction/GT 对“Sunshine Bistro”可用性的设计不一致，需要进一步核对官方 DB 中 Sunshine 的支持情况。

### task 33

- Instruction 要求：识别红色海鲜铜锅菜 allergen；若含 seafood，则在没有显式 allergen 的菜中找 carbs 最高者加一份；之后如果全单 sodium >1000mg，移除 sodium 最高的 item；最后算 sugar 和 payment。
- Service 行为：正确添加了 `Stuffed Bell Peppers x1`，但后续判断 sodium 时把 `Seafood Lover's Set` 作为最高 sodium 相关对象处理，移除了 set meal，而 GT 要求移除 `Santarini Seafood Rice x1`。
- Correction 行为：没有阻止 set meal 与单品边界混淆。
- GT 要求：添加 `Stuffed Bell Peppers x1`，移除 `Santarini Seafood Rice x1`，然后 compute。
- 失败定位：set meal 成分和 order item 边界处理错误。需要明确“remove item with highest sodium”在 GT 中按订单中的单品/可移除单品处理，而不是直接删除整个 set meal。

### task 34

- Instruction 要求：识别 dark blue seafood casserole 上方菜品价格；若价格在 98-198，找 low-calorie 中 fat 最低菜加两份；否则找 savory 中 sugar 最高菜加一份；然后若折前总价 >300，最贵 item 减半；最后算 fat/tax。
- Service 行为：进入了与 GT 不同的候选路径，添加 `Tzatziki x2` 和 `Dolmades x2`，随后移除了 `Mediterranean Feast Set`。
- Correction 行为：前面阻止了无证据餐厅推荐和无 price lookup 的回复，但后续没有校正候选集合与 GT 的差异。
- GT 要求：添加 `Moussaka x1`、`Stuffed Bell Peppers x1`，并移除 `Grilled Fish x1`。
- 失败定位：候选筛选和价格/low-calorie 分支判断错误，伴随 set meal 误删。需要复核视觉锚点对应菜品及 low-calorie tag 返回集合。

### task 39

- Instruction 要求：选择适合 cephalopod 偏好的餐厅；识别 dark grey plate with white sauce dish；若触发后续分支，最终只保留 `Lentil Soup` 并计算 calories 和 total discount amount。
- Service 行为：最终状态与 GT 过程基本一致：添加 `Greek Lamb Chops x2`、清空订单、添加 `Lentil Soup x1`，并计算 nutrition/payment。最终回答 calories=240，discount amount=11.6。
- Correction 行为：要求 discount 相关答案必须调用 `compute_total_payment`，service 随后执行。
- GT/评估：tool_success=True，但 result_success=False。
- 失败定位：疑似评估/GT result 口径问题。GT 工具只有 `compute_total_payment`，没有直接的“discount amount”工具；service 用 price/discount/payment 得到 11.6，语义上符合 final user 的 discount amount 请求。

### task 41

- Instruction 要求：识别 dark blue casserole seafood 菜 calories；若 <300，在 high-protein 中找 carbs 最低者加一份；之后如果全单 calories 按每 100g 超过 650，则删除非 set 菜中 calories 最高者；最后算 protein/tax。
- Service 行为：把 high-protein/lowest carbs 分支执行成添加 `Grilled Halloumi Cheese x1`，随后又移除该菜；最终保留了与 GT 不同的订单。
- Correction 行为：指出删除前必须先 compute total nutrition，并指出 per-100g 与 per-serving 口径混淆，但没有修正到 GT 的 `Greek Salad x2` 和 remove `Feta & Tomato Spaghetti`。
- GT 要求：添加 `Greek Salad x2`，移除 `Feta & Tomato Spaghetti x1`。
- 失败定位：ranking 指标和 per-100g 口径混乱。Service 没有稳定按“high-protein 集合中 carbs 最低”执行。

### task 48

- Instruction 要求：因同学喜欢 risotto 推荐餐厅；识别 dark grey plate with white sauce 菜的 fiber/high_fiber；再按 high_fiber 分支或 low-fat/discount 分支添加；如果全单 sugar 按每 100g 超过 15，则移除 sugar 最高 item，包括 set meal；最后算 calories/tax。
- Service 行为：实际进入 Annie Italian Restaurant 路径，枚举大量 Annie 菜，添加 `Australian imported m9+ grain-fed ribeye`，移除 `Italian Classic Set`，最终完全不是 GT 的 Greek 路径。
- Correction 行为：多次要求空结果后 retry、要求 per-100g sugar 口径，但没有纠正餐厅路径。
- GT 要求：Greek 路径：添加 `Grilled Octopus x2`，移除 `Greek Classic Set x1`。
- 失败定位：餐厅选择与 GT 不一致；该 task 需要复核 GT 是否合理。自然语义上“risotto”更容易引导到 Annie/Italian，当前 GT 走 Greek 需要有明确视觉/DB依据。

### task 54

- Instruction 要求：同事可吃 red meat 但一人 beef allergy，选餐厅；识别木碗乳制品菜 sugar；若 sugar>20，找 light sweetness 低价加两份，否则 mild 最高 calories 加一份；若全单 sugar 按 100g >50，移除非 set 最高 sugar；最后算 discount amount 和 tax。
- Service 行为：最终添加 `Hummus Dip x1`，但没有移除 `Greek Yogurt with Honey & Nuts x2`，最终 compute 范围仍包含该菜。
- Correction 行为：前半段围绕红肉/牛肉过度拉长验证；后半段明确指出 per-serving 与 per-100g sugar 不能混用，并阻止了移除。
- GT 要求：添加 `Hummus Dip x1`，移除 `Greek Yogurt with Honey & Nuts x2`，再 compute。
- 失败定位：per-100g sugar 阈值与 GT 不一致，需要复核。Correction 认为按 100g 不应移除；GT 要求移除，说明这里 GT 或 correction 的口径至少有一个有问题。

### task 58

- Instruction 要求：识别白盘奶制品/坚果/水果菜 allergen；若同时含 dairy 和 nuts，则找 high_calories 中 protein 最高者加一份；最后算 payable 和 sugar。
- Service 行为：添加 `Pork Gyro Plate x1`，调用 `compute_total_payment` 和 `compute_total_nutrition`，最终回答 payable=1241.66、sugar=61。
- Correction 行为：要求验证 set meal 边界和使用 compute，service 已执行。
- GT/评估：tool_success=True，但 result_success=False；实际 compute 输入和 GT 项目一致，只是 set meal 与新增 dish 的顺序不同。
- 失败定位：高度疑似 eval/result 假阴性或 canonical/order 口径问题。该样本应优先人工复核，可能可以作为正确样本使用。

### task 59

- Instruction 要求：识别第 1 展开页右页上方菜品 price；若 price<150，找无 seafood allergen 中 calories 最低者加两份；否则 fresh+savory 低价加一份；若当前菜属于 set meal，则替换成 set meal；最后算 cost/sodium。
- Service 行为：添加 `Tzatziki x2` 后，只检查了 `Dessert Pairing Set`，没有清空并替换为 `Mediterranean Feast Set`。
- Correction 行为：要求 all dishes 全量枚举无 seafood allergen，导致流程很长，但没有保证最终 set meal 替换逻辑正确。
- GT 要求：`add Tzatziki x2` 后 `clear_user_order`，再 `add_set_meal_to_order(Mediterranean Feast Set)`。
- 失败定位：set meal 替换目标错误。Service 只围绕当前新增/vanilla 相关 set meal 检查，未按 GT 找到完整订单可替换的 `Mediterranean Feast Set`。

### task 61

- Instruction 要求：识别第 5 展开页右侧文本列表第 1 项 sugar；若 sugar>10，在 sweet-flavored 中找 sugar 最低者加一份；否则在 savory 中找 calories 最高者加两份；之后若订单无折扣项，再加 high-fiber 最低价；最后算 tax/fat。
- Service 行为：将目标识别/分支执行成添加 `Mediterranean Grilled Prawns x1`，而 GT 需要 `Pork Gyro Plate x2`。
- Correction 行为：只要求先查两家 dessert 类别，并未校正核心视觉锚点和分支。
- GT 要求：添加 `Pork Gyro Plate x2`，再 compute。
- 失败定位：视觉文本列表定位或 sweet/savory 分支错误。需要重新核对第 5 展开页右侧文本列表第 1 项到底是哪道菜及其 sugar。

### task 63

- Instruction 要求：识别红色海鲜铜锅菜 price/protein；若 price 在 98-198，则在 fresh+savory 中找 protein 最高者加两份；否则 mild 低价加一份；若非 set meal 总额 >280，则把最贵非 set meal 清零；最后算 tax/carbs。
- Service 行为：识别为 `Grilled Octopus` 后，没有添加 GT 的 `Chicken Souvlaki x2` 和 `Mediterranean Seafood Stew x2`，而是基于当前订单直接移除了 `Grilled Fish`。
- Correction 行为：没有有效纠正 fresh+savory 候选和非 set meal 总额范围。
- GT 要求：添加 `Chicken Souvlaki x2`、`Mediterranean Seafood Stew x2`，再移除 `Mediterranean Seafood Stew x2`。
- 失败定位：fresh+savory 候选枚举和非 set meal 范围均错误。

### task 64

- Instruction 要求：识别木板烤蔬菜串的 flavor；后续按 flavor 分支执行。
- Service 行为：一开始错误使用 `Grilled Fish`，用户明确纠正“不要当成 fish dish”；service 后续尝试 `Chicken Souvlaki`、`Vegetable Souvlaki` 等，但没有稳定 canonical 到 GT 路径。
- Correction 行为：多次拒绝继续用 Grilled Fish，要求根据当前帧重新定位；这里审核方向合理，但 service 仍未完成 canonical。
- GT 要求：添加 `Greek Lemon Potatoes x1`，移除 `Feta & Tomato Spaghetti x1`，再 compute。
- 失败定位：视觉锚点 canonical 失败。该 task 主要是视觉识别和 DB 字段映射问题。

### task 69

- Instruction 要求：识别 dark grey plate with white sauce 菜 protein/fat；若 protein>fat，找 gluten-free 最低 calories 加两份；之后若订单中有 dairy，移除并用最低价 vegan 替换；最后算 calories/tax。
- Service 行为：最终状态与 GT 一致：移除 `Vanilla pudding x1`、`Tzatziki x3`、`Greek Classic Set x2`，添加 `Pita Bread x3`，并 compute calories/tax。
- Correction 行为：要求全量枚举 gluten-free，并要求 dairy replacement 数量按被移除 dairy item/line 对应；最终帮助 service 得到正确状态。
- GT/评估：result_success=True，但 tool_success=False。原因是 service 将多次移除和 `Pita Bread x3` 聚合在一个 mutation batch 中，而 GT 记录为逐步多次添加/移除。
- 失败定位：过程等价但工具序列不等价。该样本不应简单视为业务失败，但 joint 无法通过。

### task 75

- Instruction 要求：因同学喜欢 Italian risotto 推荐餐厅；识别第 5 展开页右侧文本列表第 2 项 discount；若 discount<0.9，找 Fresh Fragrant 折后总价最低加两份；否则 high-calorie carbs 最高加一份；若订单能匹配 set meal，则替换；最后算 calories/tax。
- Service 行为：进入 Annie Italian Restaurant 路径，添加 `Tiramisu' x1`，并按 Annie set meal 计算。
- Correction 行为：只处理了 tool JSON 格式问题，没有纠正餐厅选择。
- GT 要求：Greek 路径：添加 `Feta & Tomato Spaghetti x1`，按 Greek order compute。
- 失败定位：餐厅选择/GT 可疑。和 task 48 类似，instruction 明确提到 Italian risotto，service 选择 Annie 并非明显不合理；需要复核 GT 为何选择 Greek。

### task 77

- Instruction 要求：因家人不喜欢 Italian cuisine 选择餐厅；识别木碗奶制品价格；若含税价>88，找 vegan lowest calories 加两份；否则 seafood allergen 中 protein 最高加一份；若含税总额超过 500，则持续减少最贵非 set meal；最后算 protein/tax。
- Service 行为：进入 seafood allergen/highest protein 分支，添加 `Mediterranean Seafood Stew x1`，随后又正确移除它；但为了预算继续移除了 `Greek Lamb Chops x1`，GT 不要求这一步。
- Correction 行为：多次要求全量枚举 seafood allergen 候选，后续没有阻止预算循环过度执行。
- GT 要求：添加并移除 `Mediterranean Seafood Stew x1` 后直接 compute。
- 失败定位：预算 while 条件范围错误。Service 继续用当前 total 判断并多删了 `Greek Lamb Chops`。

### task 78

- Instruction 要求：识别第一展开页右上 chicken and potatoes 的 carbs；若 carbs>15 且 sugar<5，则找 sour 中最低价加两份；之后若全单 carbs>100，删除非 set meal 中 carbs 最高者；最后取 flavor profiles 并算 tax。
- Service 行为：正确添加 `Tzatziki x2` 和 `Greek Lemon Potatoes x2`，但后续删除了 `Vanilla pudding x1`，而 GT 要求删除 `Spaghetti Bolognese x2`。
- Correction 行为：要求删除前先 compute 全单 nutrition；合理，但没有校正“非 set meal 中 carbs 最高者”的选择。
- GT 要求：删除 `Spaghetti Bolognese x2`。
- 失败定位：最高 carbs 候选选择错误，可能混用了总 carbs、per-serving carbs、per-100g carbs 或 set meal 展开后的范围。

### task 82

- Instruction 要求：识别 seafood cocotte sugar；若 sugar<3，找 sweet 中 fat 最高者加一份；之后若全单 sugar 按每 100g 超过 40，则移除非 set sweet dish；最后算 price/fat。
- Service 行为：添加并移除了 `Baklava x1`，payment 与 GT 一致；但 compute nutrition 展开了 `Pasta Lovers Set` 成分，最终输入不是 GT 中的 set meal 表达。
- Correction 行为：要求 per-100g sugar 口径，并拒绝把 serving-based sugar 当成请求值。
- GT 要求：`add Baklava x1`、`remove Baklava x1`，compute 中保留 `Pasta Lovers Set x2`。
- 失败定位：set meal 在 nutrition compute 中是保留 set meal 还是展开成成分的口径不一致。工具状态可能等价，但 GT 序列不等价。

### task 86

- Instruction 要求：识别木碗乳制品是否属于 set menu；若属于，找 slightly sour 低价加一份；否则 high-carbohydrate 最高 protein 加三份；如果折前总价>250，则把最贵 item 数量降为 0；最后算 payment/calories。
- Service 行为：添加 `Tzatziki x1` 和 `Greek Lemon Potatoes x1`，但 correction 认定当前最贵 item 是 `Pasta Lovers Set`，于是移除了 set meal；GT 要求移除 `Grilled Octopus x2`。
- Correction 行为：直接推动了 set meal removal。
- GT 要求：移除 `Grilled Octopus x2`，保留 `Pasta Lovers Set`。
- 失败定位：set meal 是否参与“most expensive item”判断存在语义/GT疑点。按照自然语言 item 可以包含 set meal；按照我们之前希望区分 dish/item 与 set meal，GT 选择非 set dish。该 task 需要进一步统一规则。

### task 87

- Instruction 要求：识别第一展开页右上 chicken and potatoes allergen；若含 dairy，则 vegan lowest calories 加两份；否则 mild 且 price<100 中 sugar 最高加一份；之后若订单仍含 dairy，则清空并只保留一个 sweet-and-savory dish；最后算 nutrition/tax。
- Service 行为：最终清空后只保留 `Mediterranean Grilled Prawns x1`，没有添加 GT 的 `Greek Salad x1` 和最终 `Stuffed Bell Peppers x1`。
- Correction 行为：认为 `Stuffed Bell Peppers` 是任意选择，因为 sweet-and-savory 有多个匹配，要求用户选择；随后推动清空，但未完成 GT 的保留项。
- GT 要求：先添加 `Greek Salad x1`，清空，再添加 `Mediterranean Grilled Prawns x1` 和 `Stuffed Bell Peppers x1`。
- 失败定位：correction 对“keep only one sweet-and-savory dish”的歧义处理与 GT 冲突。这里 GT 也需复核，因为 instruction 写的是 one dish，但 GT 最终保留两个菜。

### task 89

- Instruction 要求：识别亮蓝盘炸物柠檬 wedge 菜，查询单品价格和潜在 set meal；判断是否属于 Seafood Lover's Set 且 set price 低于单品和；若是，找 fresh+savory 中最大折扣且最低价菜加一份；否则 high-calories 低 fat 加两份；之后若订单有 nuts，移除非 set nut item；最后算 amount/fiber。
- Service 行为：没有添加 GT 的 `Grilled Fish x1`，只移除了 `Greek Yogurt with Honey & Nuts x2` 并 compute。
- Correction 行为：要求查询 set meal details，合理；但没有推动完成 fresh+savory 最大折扣/最低价分支。
- GT 要求：添加 `Grilled Fish x1`，移除 `Greek Yogurt with Honey & Nuts x2`。
- 失败定位：set meal price 比较后的分支没有完整执行，漏加目标菜。

### task 91

- Instruction 要求：识别 dark blue seafood casserole protein；若 protein>30，则在 savory 中找 carbs 最低菜加两份；否则 high-fiber 最高价加一份；之后若全单 calories<400，再加最低 sugar；最后算 calories/tax。
- Service 行为：识别为 `Mediterranean Grilled Prawns` protein=32，进入 savory/lowest carbs 分支，但添加了 `Grilled Halloumi Cheese x2`；GT 要求 `Stuffed Bell Peppers x1`。
- Correction 行为：没有阻止候选选择错误。
- GT 要求：添加 `Stuffed Bell Peppers x1`，再 compute。
- 失败定位：savory 候选 carbs 排序错误或 GT 可疑。根据工具数据，`Grilled Halloumi Cheese` carbs=2 且 savory，确实可能是最低 carbs；GT 的 `Stuffed Bell Peppers` carbs=45。需要复核 GT。

## 问题分桶

### 1. 本轮可直接使用的正确样本

`23, 28, 38, 96` joint 通过，可以作为替换候选。

### 2. 疑似 GT 或 eval 假阴性

- `13`：instruction 和工具结果支持 nuts 分支，GT 却走 else 分支。
- `39`：工具链通过，final 计算 discount amount 合理，但 result 判 false。
- `58`：工具链与 compute 结果均对齐，result 判 false，疑似 canonical/order 评估问题。
- `69`：最终状态正确，result 通过；joint 失败来自聚合 mutation 与 GT 逐步调用不一致。
- `87`：instruction 说保留 one sweet-and-savory dish，但 GT 最终保留两个菜，且 correction 认为需要 disambiguation。
- `91`：service 选择 `Grilled Halloumi Cheese` 作为 savory/lowest carbs 可能比 GT 的 `Stuffed Bell Peppers` 更符合工具数据。

### 3. 餐厅选择/官方 DB 覆盖问题

`32, 48, 75, 89` 都涉及非 Greek 餐厅名、菜单选择或 restaurant name 支持问题。尤其 `48/75` 的 instruction 都强调 risotto/Italian，service 选择 Annie 并不明显错误，但 GT 走 Greek 路径，需要进一步复核。

### 4. set meal 与单品边界问题

`33, 59, 82, 86, 87, 89` 都涉及 set meal 是否作为可移除 item、是否展开成成分计算、是否可替换当前订单。当前 prompt/correction 仍会在“item/dish/set meal”边界上与 GT 不一致。

### 5. per-100g 与 per-serving 计算口径问题

`17, 41, 48, 54, 78, 82` 都出现了按每 100g 的条件判断与 compute 工具 per-serving 输出之间的冲突。Correction 有时正确指出口径问题，但也会使流程反复修正而跑偏。

### 6. 视觉锚点 canonical 问题

`5, 61, 64` 明显受视觉锚点或文本位置定位影响。`64` 中用户明确纠正“不是 fish dish”，service 仍无法稳定 canonical 到 GT 菜名。

## 下一步建议

1. 先不要把 24 个失败样本批量合入候选集；只合入 joint 通过的 `23, 28, 38, 96`。
2. 对 `13, 39, 58, 69, 87, 91` 做人工 GT/评估复核；其中 `58` 最像假阴性，`13/91` 最像 GT 错误。
3. 对 order prompt 继续强化：set meal 与 dish/item 的边界、per-100g 条件判断、final compute 工具口径三者必须明确区分。
4. 对 correction 降低“要求全量枚举所有 category”的触发频率；它在 `69/77` 等任务中显著拉长流程，虽然有时能纠正，但也增加跑偏机会。
5. 对 `48/75` 这类 restaurant selection 与 GT 冲突任务，先人工确认 GT 选择餐厅的依据，再决定是否修改 GT 或继续优化 service。
