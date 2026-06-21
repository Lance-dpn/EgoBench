### 手排 key, value 发现的错误

都已经修改

| Task |             应该是              |
| :--: | :-----------------------------: |
|  9   |  mediterranean grilled prawns   |
|  12  |          grilled fish           |
|  13  |         vanilla pudding         |
|  14  | Greek Village Roast Chicken Leg |
|  42  |         Vanilla pudding         |
|  57  |  Mediterranean Grilled Prawns   |
|  58  |         Vanilla pudding         |
|  68  |         Vanilla pudding         |
|  89  |         Fried calamari          |
|  93  |        Octopus Spaghetti        |
|  96  |         Vanilla pudding         |

**1、有一道菜我感觉不是特别清楚**，一般 Instruction 会这样描述

> the dish served on a dark gray plate paired with a small dish of white sauce
>
> 装在深灰色盘子里、搭配一小碟白酱的菜肴

出现这道菜的 task 里面，我看 codex 都是选的 Greek Lamb Chops 烤羊排，深灰色盘子是对的，但是酱料很明显是红色

**然后其他菜品也都不太符合这个描述，最接近的是 Fried calamari 炸鱿鱼，但是盘子颜色是亮蓝色**，而且一般对于这道菜，Instruction 都会这样描述

> the dish on a bright blue plate that has some fried items and a lemon wedge
>
> 亮蓝色盘子上的那道菜，上面有些油炸物和一片柠檬角

考虑到

- 不同 task 里面，对于相同的 key value 菜品，Instruction 给出的描述是相近的
- 其他菜品都有对应更合适的描述了

因此我就直接把这个描述对应到 Greek Lamb Chops，没有判错

**2、task 57, 82**

> deep blue **cocotte** containing seafood

codex 给的是 Santarini Seafood Rice，我搜了下 cocotte 的图片，感觉是更符合 Mediterranean Grilled Prawns

### Codex review 发现的错误

都已经修改，修改后还不能很确定的 task 有

- **task42**，题目说 "当前选定的甜品组成带折扣的套餐"。

#### task1

该 ground_truth 语义不正确。已确认初始订单为空，可信视觉答案对应的 Greek Village Roast Chicken Leg 蛋白质为 35g，超过 20g，因此应添加全菜单中最低标价且带 vegan 标签的开胃菜 Hummus Dip 和 Melitzanosalata。之后必须用 compute_total_payment 对当前非套餐订单进行分支判断，两个菜的实际应付总额为 98.6 元，不超过 100 元，所以不应执行海鲜替换。原答案错误地按标价或未计算付款分支进入替换流程，移除了两个开胃菜并加入 Grilled Octopus 和 Grilled Fish，导致最终订单、总碳水和税费计算对象都错误；同时缺少用于蛋白质分支和付款分支的必要 compute_* 调用。

#### task4

可信视觉字段已确定木板烤蔬菜串对应的菜品是 Grilled Fish。查询口味后确认 Grilled Fish 包含 umami，因此应走高蛋白菜品中钠含量最低的分支；高蛋白菜品里 greek yogurt with honey & nuts 的钠含量最低，为 50 mg，且没有并列项，所以应添加 2 份该菜。添加后对完整当前订单计算总支付金额为 81.2 元，不超过 200 元，因此不应删除任何菜品。最终需要计算该最终订单的碳水合计，应对 2 份 greek yogurt with honey & nuts 调用 compute_total_nutrition，碳水为 70 g。原 ground_truth 错误地走了 sweet fallback，添加并计算 Baklava，因此语义不正确。

#### task13

受信字段确认视觉目标菜品为 Vanilla pudding。环境查询显示该菜品过敏原为 dairy 和 eggs，不含 nuts，因此应走“不含坚果过敏原”的分支：在 high_calories 菜品中选择最低价格菜品并各加 2 份。价格查询确认最低价为 58，且由 loukoumades 与 vanilla pudding 并列。加入这两项后，两者折扣均为 0.9，所以“不存在享受折扣的菜品”条件不成立，不能再额外添加低糖菜品。最终应对 loukoumades x2 与 vanilla pudding x2 计算总钠和折后应付金额，环境计算结果为 sodium_mg 520.0、total_payment 208.8。待审 GT 错误地添加了 Octopus Spaghetti x1，并只对该单品计算总额和营养，分支目标、最终订单和最终计算对象均不正确。

#### task14

可信视觉字段已确定圈出的菜品是 Greek Village Roast Chicken Leg，且该菜只能在 Mediterranean Greek Restaurant 中查询到。环境查询显示该菜当前价格为 108 元，不大于 150 元，因此应走 otherwise 分支；按本数据集中“fresh and savory”作为鲜香/咸鲜口味条件的用法，应在 savory 口味菜品中选择单价最高者，Grilled Octopus 价格 198 元，为唯一最高，应添加 2 份。添加后对当前订单计算总营养，蛋白质为 60g，不低于 50g，因此不应删除任何菜品。最终只需要计算订单总金额，应对 Grilled Octopus x2 调用 compute_total_payment，结果为 277.2 元。待审 ground_truth 错误地添加了 Santarini Seafood Rice x1，并只对该单品计算总金额和营养；其中 compute_total_nutrition 也不是最终要求输出的聚合结果，因此语义不正确。环境中还存在一个名为 Greek Village Roast Chicken Leg 的异常订单命名空间，但该命名空间没有目录，不能作为可添加菜品的目标餐厅。

#### task15

已按环境工具核验：customer_005 在已选的 Mediterranean Greek Restaurant 初始订单为空，Meraki Kitchen 在该环境中没有可用目录；可信视觉菜品 Fried calamari 的钠含量为 500mg，并未超过 500mg，因此应走酸味菜品中膳食纤维最高的分支。Greek Salad 和 Greek Lemon Potatoes 都是 4g fiber，并列最高，所以 GT 的前两次添加是正确的。随后必须用当前完整订单计算非套餐折后总价，compute_total_payment 返回 90.8 元，低于 100 元，因此会触发“下方铜色双耳锅红色海鲜菜品”这一第二视觉识别并添加 1 份。trusted_fields 没有给出该第二视觉菜名，需要人工补充；无论具体菜名是什么，当前 GT 都缺少这次添加，并且最终 compute_total_nutrition 与 compute_total_tax 只计算了前两道菜，未包含被触发的第二视觉菜品，所以语义不正确。

#### task42

GT 选择的餐厅为 Mediterranean Greek Restaurant 是合理的，且初始订单为空；但根据工具查询，Vanilla pudding 的过敏原是 dairy 和 eggs，不包含 nuts，因此应走低脂菜品中钠含量最高的分支，而不是甜味菜品中热量最高的分支。低脂候选中 mediterranean seafood stew 的 sodium_mg 最高，为 800，应添加 1 份。Vanilla pudding 可以组成带折扣的 dessert pairing set，因此还应添加该套餐。最终汇总应基于 mediterranean seafood stew 与 dessert pairing set 的完整当前订单计算。现有 GT 错误添加了 Baklava 2 份，并对 Baklava + Dessert Pairing Set 计算总价和营养，语义不正确。

#### task78

已按流程重置环境并使用 CLI 核验。按显式 desserts 类别比较，Mediterranean Greek Restaurant 有 Greek Yogurt with Honey & Nuts、Vanilla Pudding、Baklava、Loukoumades 四个甜品，而 Annie Italian Restaurant 在 desserts 类别下为空，因此所选餐厅应为 Mediterranean Greek Restaurant。customer_003 在该精确餐厅命名空间下初始订单为空；受信任视觉菜品 Greek Village Roast Chicken Leg 在该餐厅的 carbs_g 为 15，不超过 20，因此应走 slightly sour/sour 口味最低单价分支。sour 候选中 Tzatziki 与 Greek Lemon Potatoes 均为 48 元并列最低，应各添加 2 份。对添加后的完整当前订单执行 compute_total_nutrition 得到 carbs_g=86，超过 20，所以应移除非套餐菜品中碳水最高的 Greek Lemon Potatoes。最终订单只剩 Tzatziki x2，最终要求计算整个订单税费，应对 Tzatziki x2 调用 compute_total_tax，结果为 3.8。ground_truth 的加菜、删菜和最终税费计算目标正确，但它额外包含了移除后的 compute_total_nutrition(Tzatziki x2)。该聚合营养计算不是最终输出要求；若作为中间碳水分支检查，也应发生在删除前并覆盖 Tzatziki x2 + Greek Lemon Potatoes x2。因此该 GT 工具序列在宽松策略下仍不完全正确。

**注**：这里的意思是多了一个 compute_total_nutrition，我把它删去了

#### task80

该 ground_truth 的分支结果错误。应选择 Mediterranean Greek Restaurant；customer_006 在该餐厅下的初始订单为空。可信视觉识别给出的菜品是 Grilled Octopus，其热量为 280 kcal，大于 250 kcal，因此应进入 fresh 口味最低热量分支；**但该餐厅没有 fresh 口味菜品**，所以该步不应添加 Grilled Octopus。随后当前订单中没有 fresh 口味菜品，应额外添加最低价 vegan 菜品 pita bread 1 份，并对完整当前订单计算总税费。原 GT 错误地添加了 Grilled Octopus 2 份，并且只对 Grilled Octopus 计算税费。

**注**：原始数据 Mediterranean Greek Restaurant 确实没有 taste 包含 fresh 的菜品，所以这里什么也加不了

#### task83

选择的餐厅应为 Mediterranean Greek Restaurant，且 customer_009 在该餐厅的初始订单为空。已知视觉目标菜品为 Feta & Tomato Spaghetti，其营养为 600 kcal、20 g 蛋白质，热量/蛋白质比值为 30，不小于 20，因此应进入 savory 菜品中选择最高价菜品的分支。菜单中最高价 savory 菜品是 Grilled Octopus，应添加 1 份。添加后用 compute_total_payment 计算当前非套餐订单总额为 138.6 元，未超过 150 元，所以不应删除 Grilled Octopus。原 ground_truth 错误地删除了 Grilled Octopus，并对空订单计算营养和税费，导致最终订单和最终汇总目标均错误。

#### task93

环境查询确认应选择 Mediterranean Greek Restaurant，且 customer_001 在该精确餐厅命名空间下初始订单为空。可信视觉目标 Octopus Spaghetti 的价格为 88，关联套餐为 pasta lovers set；该套餐按 compute_total_payment 计算为 180.88，低于其包含菜品单点合计 212.8，因此应进入 gluten 过敏原菜品中折扣最大分支。gluten 候选中折扣因子最低为 0.8，Santarini Seafood Rice、Feta & Tomato Spaghetti、Moussaka 三项并列，GT 的三次加菜是正确的。但加菜后订单没有任何套餐折扣，按指令应将这些单品分别转换为对应套餐：seafood lover's set、pasta lovers set、greek classic set。现有 GT 缺少清空单品并加入套餐的步骤，且最终 compute_total_payment 与 compute_total_nutrition 仍针对三道单品，得到的是单品订单的 243.2 元和糖 16g；预期最终套餐订单应计算 789.82 元和糖 37g。因此 ground_truth 的最终订单和最终计算目标错误。

**注**：我检查了 order_init.py，set_meals 套餐定义中，每个套餐包含的菜品是完全不同的，每个菜品最多对应一个包含它的套餐

#### task96

已按环境重置并核查：应选择 Mediterranean Greek Restaurant，且 customer_004 在该餐厅下初始订单为空。可信视觉识别为 Vanilla pudding，其口味标签包含 sweet，因此进入糖分大于 20g 且单价最低的分支。菜单中符合糖分条件的最低价菜品是 vanilla pudding 和 loukoumades，均为 58 元，应各加入 2 份。加入后订单中最贵菜品原价仍为 58 元，不高于 150 元，因此不应删除任何菜品。最终需要计算的是总税额，compute_total_tax 对这两道菜各 2 份的结果为 24.02。原 ground_truth 的最终订单和税额目标正确，但额外调用了 compute_total_nutrition；指令没有要求计算、汇总或报告总营养，按宽松 GT 策略该聚合计算不应出现在正确答案中，因此判为失败。

**注**：

- 多了 compute_total_nutrition；
- Instrurction 明确要求 "最后，请AI服务代理提供最终订单的完整摘要"，对应 get_user_order_summary。我看了 order1.json，确实有 ground truth 是有这个 tool 的，所以要加上。

#### task97

该 ground_truth 语义错误。已确认选定餐厅应使用 Mediterranean Greek Restaurant，且 customer_005 在该精确餐厅命名空间下初始订单为空。可信视觉目标菜品 Greek Village Roast Chicken Leg 在该餐厅目录中，4 份按 compute_total_payment 计算为 302.4 元，低于 400 元，因此应进入“在所有 savory 菜品中选择碳水最高者”的分支。经查询 savory 菜品营养，feta & tomato spaghetti 的碳水为 90g，为最高且无并列，应添加 4 份该菜。原 GT 错误地进入了 seafood allergens 的备选分支，添加了 Fried calamari 和 Octopus Spaghetti 各 2 份；后续清空购物车以及清空后的税费和营养计算本身是正确的，但前置分支和添加目标错误。