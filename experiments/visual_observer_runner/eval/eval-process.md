# 用户评估observer能力的数据集制作流程及要求

本文档是重新构建四个场景 `order / restaurant / retail / kitchen`
observer 评估数据集时必须遵守的流程。目标是形成稳定、可复核、可复现
的数据集，避免因不同轮次理解标准不同导致聚类数量和 GT 结果大幅波动。

核心原则：

1. `visual_query_v1` 是视觉问题的统一标准表示。
2. 聚类只基于规范化后的 `visual_query_v1`，不基于 final value、DB 数据或完整 raw instruction。
3. GT 以每个问题内联保存为主格式，避免人工维护多套索引。
4. raw instruction、抽取过程、聚类过程、GT 过程都必须可追溯。

## 关键信息提取
从 scenario 中每个场景提取 `instruction`、`task_id`、`image_name`、
`image_path`、`scenario_key` 等基础信息，形成过程文件。

然后根据每条 instruction 提取其中包含的视觉问题。这里必须充分理解
instruction 的含义，因为可能存在：

- 先识别一个视觉对象，再基于该对象执行工具查询。
- 先识别一个视觉对象，再根据该对象所在 category/region 继续查询。
- 一个 task 中包含多个彼此独立的视觉问题。
- 一个 task 中包含条件分支，只有分支中的某个视觉问题会被实际使用。

提取时要保留所有可能需要 observer 解决的视觉问题，形成未去重问题全集。
未去重问题全集中的每条记录至少应包含：

- `scenario_key`
- `task_id`
- `video_id` / `image_path`
- `instruction`
- `visual_problem_raw_text`
- `source_clause`
- `branch`，例如 `initial`、`if_true`、`if_false`、`follow_up`
- `extraction_notes`

注意：

- 不要把价格、税、营养、库存、折扣、推荐、购物车/order 操作等业务任务
  当成视觉问题。
- observer 只解决“视频中可见对象/区域/文字/动作状态是什么”的问题。
- final value、DB 数据、官方 grounding 不能用于视觉问题抽取。

## visual_query 标准化

每个未去重视觉问题都必须转换为一份 `visual_query_v1`。后续聚类、
observer 调用、eval case 都以这份结构化 query 为准。

转换链路必须是：

```text
instruction -> raw visual problem -> visual_query_v1 -> cluster -> GT -> eval
```

不允许直接基于 raw instruction、final value 或 DB 结果进行聚类。

`visual_query_v1` schema 如下：

```json
{
  "schema_version": "visual_query_v1",
  "scenario": "order|restaurant|retail|kitchen",
  "surface": "menu|shelf|table|kitchen_workspace",

  "target": {
    "kind": "dish_name|product_name|category|ingredient_name|recipe_name|set_meal_name|visible_text|visible_region",
    "selection_unit": "menu_item|menu_category|product_package|shelf_label|served_dish|ingredient|recipe_scene",
    "cardinality": "single"
  },

  "referent": {
    "type": "pointing_sequence|selected_pointing_event|static_region|relative_region|object_action_state|composite_scene",
    "action": "pointing|holding|picking|placing|sprinkling|pouring|cutting|cooking|served|null",
    "ordinal": "first|second|third|last|null",

    "region": {
      "side": "left|right|center|null",
      "vertical": "top|middle|bottom|null",
      "container": "fold|page|panel|shelf|tray|pot|wok|cutting_board|table|null"
    },

    "relation": {
      "type": "above|below|left_of|right_of|inside|containing|next_to|null",
      "anchor": {}
    },

    "appearance": {
      "color": null,
      "style": null,
      "size": null,
      "shape": null,
      "content_hint": null
    }
  },

  "scope": {
    "video_id": null,
    "menu_label": "menu_1|menu_2|null",
    "time_hint": null
  }
}
```

字段解释：

- `scenario`: 当前场景，只能是 `order`、`restaurant`、`retail`、`kitchen`。
- `surface`: 视觉目标所在载体。菜单用 `menu`，货架用 `shelf`，桌面已上菜品用
  `table`，厨房操作区用 `kitchen_workspace`。
- `target.kind`: observer 最终要读出的视觉值类型。
- `target.selection_unit`: 视觉上要被选中的对象单位。
- `referent.type`: 目标如何被定位。
- `referent.action`: 可见动作，没有动作填 `null`。
- `referent.ordinal`: 只用于时间序列，例如 first/second/last pointing。
  空间上的 leftmost/top/bottom 不应填在这里。
- `referent.region`: 绝对空间位置。
- `referent.relation`: 相对空间关系，anchor 必须是结构化视觉锚点，不能是
  DB 名称或 final value。
- `referent.appearance`: 只放可见外观约束，例如颜色、背景、大小、形状。
  不允许放高蛋白、低价、含税、库存等业务条件。
- `scope.menu_label`: 多菜单视频中必须尽量解析为 `menu_1` 或 `menu_2`。

`visual_query` 中禁止出现：

- final value / 官方答案
- DB 查询结果
- 价格、税、营养、折扣、库存、过敏原等数据库事实
- ranking / filtering / recommendation 条件
- cart/order/shopping-list 状态修改意图
- 对工具参数的猜测结果

## 问题聚类分析

根据标准化后的所有 `visual_query_v1`，将问题聚类为 observer 评估问题集。
聚类目标是去掉重复视觉问题，而不是去掉重复答案。

### 可以合并的条件

两个问题只有同时满足以下条件时，才可以合并为一个 eval problem：

- 同一个 `scenario`
- 同一个 `video_id`
- 同一个 `surface`
- 同一个 `target.kind`
- 同一个 `target.selection_unit`
- 同一个 `target.cardinality`
- 同一个 `referent.type`
- 同一个 `referent.action`
- 同一个 `referent.ordinal`
- 同一个 `referent.region`
- 同一个 `referent.relation`
- 同一个 `referent.appearance`
- 同一个 `scope.menu_label`

### 必须保留为不同问题的情况

以下情况即使答案相同，也必须保留为不同问题：

- 不同视频。
- 同视频中不同视觉定位方式，例如“右侧菜品”和“第一次指向的菜品”。
- 同视频中不同空间区域，例如“右下角小区域”和“深色背景区域上方”。
- 同视频中不同 target，例如同一区域的 `category` 和其中某个 `dish_name`。
- 同视频中同一对象但不同视觉 referent，例如“含水果的菜品”和“第二次指向的菜品”。
- raw instruction 相似但规范化 `visual_query` 不同。

### 禁止的聚类依据

聚类时禁止使用以下信息：

- scenario final value
- DB 数据
- tool 查询结果
- 官方 grounding 中的 detail 答案
- raw instruction 的完整文本相似度
- 业务条件相似度，例如都在查价格或都在查营养

这些信息只能用于后续复核，不得作为合并依据。

### 聚类输出

聚类完成后形成去重问题文件。每个问题至少包含：

- `problem_id`
- `scenario`
- `video_id`
- `visual_query`
- `problem_type`
- `source_task_ids`
- `source_problem_ids`
- `source_instruction_snippets`
- `dedupe_rationale`
- `review_notes`

聚类结果必须能追溯到去重前的每一个 raw visual problem。

## 欠指定与排除规则

以下问题不能进入 strict eval，应进入 `excluded_cases` 或
`review_required_cases`：

- 同一个 `visual_query` 对应多个不同 detail GT value。
- instruction 中只有 “this item”、“that dish”、“it” 等指代，但无法追溯到
  明确视觉 referent。
- 需要先完成业务推理或 DB 查询才能确定视觉目标。
- 视频中目标不可见、严重遮挡、只出现在过场帧，无法稳定标注。
- event 时间无法稳定定位。
- detail 无法给出唯一值，只能给多个候选。
- 视觉问题本身需要读取数据库事实，而不是视觉内容。

排除的问题也必须保留记录，并说明排除原因。不能直接删除。

## 四个场景的视觉问题类型

### order

常见视觉问题：

- `menu_1` / `menu_2` 上第 N 次 pointing 的 dish。
- 菜单固定区域的 category / dish。
- 菜单相对区域的 category，例如某区域上方/下方/左侧/右侧。
- category containing pointed dish。
- 可见 set meal label。

注意：

- `menu_label` 对 order 很重要，应尽量解析为 `menu_1` 或 `menu_2`。
- set meal 的业务展开由 service agent 调工具完成，observer 只识别可见 label 或
  可见 dish/category。

### restaurant

常见视觉问题：

- 菜单上的 dish/category。
- 桌面已上菜品，例如 left/right/center served dish。
- 服务员端上来的菜品。
- 可见菜单区域、招牌、桌面物体。

注意：

- table 上的 served dish 应使用 `surface=table` 和 `selection_unit=served_dish`。
- menu 上的问题仍使用 `surface=menu`。

### retail

常见视觉问题：

- 货架固定区域商品。
- 相邻/上下/左右商品。
- 包装外观、可见 label、货架标签。
- 指向或拿起的商品。

注意：

- 商品价格、库存、营养、推荐等必须由工具查询，不能放入 `visual_query`。
- package OCR 结果需要后续通过 DB/tool 候选验证。

### kitchen

常见视觉问题：

- 正在拿、夹、撒、倒、切、煮的 ingredient。
- 锅、托盘、砧板、盘子中的 ingredient。
- 由多个食材/动作构成的 recipe scene。
- picked ingredient / remaining ingredient / current cooking state。

注意：

- recipe facts、步骤数量、库存、用量等由工具查询。
- observer 只识别可见 ingredient、recipe scene、动作状态或可见区域。

## GT的预标注

获得问题集后，必须实际识别视频，对每个问题进行 GT 标注。GT 直接添加在每个
问题后面，不要人工维护第二套 event/detail 索引。

每个问题内联 GT 建议结构如下：

```json
{
  "event_gt": {
    "primary_content_range": [0.0, 0.0],
    "expected_time_range": [0.0, 0.0],
    "allowed_transition_range": null,
    "key_frame_time": 0.0,
    "expected_region": {
      "description": "",
      "coarse_region": "",
      "notes": ""
    },
    "confidence": "high|medium|low",
    "evidence": ""
  },
  "detail_gt": {
    "target_kind": "",
    "canonical_value": "",
    "acceptable_aliases": [],
    "negative_neighbors": [],
    "confidence": "high|medium|low",
    "evidence": ""
  }
}
```

GT 标注要求：

- event GT 必须来自实际视频识别，不得直接从 final value 推断。
- detail GT 必须来自视频可见内容或明确视觉推断。final value 只能用于复核。
- `primary_content_range` 表示最核心、最适合识别该视觉问题的时间段。
- static region 的 event 范围应是最佳可识别窗口，不是整个可见区间。
- static menu/shelf/region 任务优先选择完整上下文画面，避免只给局部裁切画面。
- event 窗口建议控制在 2 秒左右。
- `key_frame_time` 必须落在 `primary_content_range` 内。
- detail GT 应使用 `canonical_value`，不要混用 `expected_answer`。
- 相近但错误的可见候选应写入 `negative_neighbors`，便于错误分析。
- 如果 GT 不确定，应标记 `confidence=medium|low` 并进入 review。

### inline GT 与 eval 导出

内联 GT 是数据集的 source of truth。

如果当前 eval 脚本仍需要：

```json
{
  "eval_cases": [],
  "event_ground_truths": [],
  "detail_ground_truths": []
}
```

则应由导出脚本从内联 GT 自动生成这些数组。禁止人工同时维护两套 GT，
避免 inline GT 与 indexed GT 不一致。

## eval脚本

当前已经有评估脚本。重新构建完数据集和 GT 后，应验证 eval 脚本是否还能正常工作，
并进行必要适配。

eval 脚本至少应支持：

- 通过参数选择 `order / restaurant / retail / kitchen`。
- 通过参数选择 sample size 或 all cases。
- 读取每个 case 的 `visual_query` 并传给 observer。
- 评估 event 预测时间段覆盖 GT `primary_content_range` 的比例。
- 评估 event 第一 keyframe 是否落在 GT `primary_content_range` 内。
- 评估 detail 结果是否匹配 `canonical_value` 或 `acceptable_aliases`。
- 输出每个 case 的 event/detail/end-to-end 结果。
- 输出按 `problem_type`、`scenario`、`video_id` 的汇总。
- 输出错误 case 的 trace 路径，方便后续分析。

event 评估建议：

- 主要指标是 GT 时间段被预测时间段覆盖的比例。
- 不应只用预测中心点是否落在 GT 内。
- keyframe 单独评估，检查 detail 实际收到的关键帧是否可用。

detail 评估建议：

- 默认大小写不敏感。
- 规范空白字符。
- 支持 alias。
- 不允许用 DB 推理修正 observer 输出。

## 相关要求
### 我们要保留的可追溯的文件
1. scenario文件中提取的所有信息文件
2. 从instruction中提取出来的没有经过去重的问题文件
3. 去重过后的问题文件
4. 完整的问题集和GT集

建议固定目录结构如下，四个场景保持一致：

```text
observer_problem_set_<scenario>/
  01_scenario_tasks.jsonl
  02_visual_questions_raw.jsonl
  03_visual_queries_raw.jsonl
  04_visual_query_clusters.json
  05_observer_dataset_with_gt.json
  excluded_cases.json
  review_required_cases.json
  summary.md
```

其中：

- `01_scenario_tasks.jsonl`: 从 scenario 文件提取的基础 task 信息。
- `02_visual_questions_raw.jsonl`: 未去重视觉问题。
- `03_visual_queries_raw.jsonl`: 每个未去重视觉问题对应的 `visual_query_v1`。
- `04_visual_query_clusters.json`: 聚类后的问题集，未填 GT。
- `05_observer_dataset_with_gt.json`: 完整问题集和内联 GT。
- `excluded_cases.json`: 不进入 strict eval 的问题。
- `review_required_cases.json`: 需要人工重点复核的问题。
- `summary.md`: 人类可读摘要。

### 场景的处理
对于某个场景下多个分支，可以为每个分支单独创建过程文件，最后的问题集进行归拢。

归拢时必须保证：

- 不同视频不合并。
- 不同分支中相同 `visual_query` 可以合并，但必须保留 source branch。
- 分支专属视觉问题必须保留 branch 信息。
- 如果某个分支实际不会被触发，但 instruction 中存在视觉问题，可以进入
  review 或保留为 branch-specific case，不能无说明删除。

## 构建完成后的质量检查

每次完成一个场景的数据集构建后，必须执行质量检查，并在 `summary.md`
中记录结果。

检查项：

- 所有 task 是否被覆盖，或者明确进入 excluded/review。
- 每个 eval case 是否有 `visual_query`。
- 每个 eval case 是否有 inline `event_gt` 和 `detail_gt`。
- 是否存在跨视频合并。
- 是否存在 final value、DB 数据、tool result 参与聚类。
- 是否存在同一 cluster 对应多个 `canonical_value`。
- 是否存在 `key_frame_time` 缺失或不在 `primary_content_range` 内。
- 是否存在 detail GT 字段不统一，例如 `expected_answer` 和 `canonical_value` 混用。
- 是否存在 raw instruction 直接进入 observer query 而没有结构化 `visual_query`。
- eval 脚本是否能跑通 sample。
- 各 `problem_type` 的数量是否可解释。
- 与上一版数量变化是否可解释。

质量检查未通过时，不得将数据集标记为 ready。

## 状态标记

建议每个 case 使用明确状态：

- `draft_extracted`: 已抽取视觉问题，未聚类。
- `clustered_pending_gt`: 已聚类，未填 GT。
- `gt_bootstrap_pending_review`: 已填第一版 GT，待人工复核。
- `reviewed_ready`: 已人工复核，可进入 strict eval。
- `excluded_under_specified`: 欠指定或多值，不进入 strict eval。
- `excluded_not_visible`: 视频不可见或无法稳定识别。

场景级数据集也应有状态：

- `draft`
- `gt_bootstrap`
- `human_reviewed`
- `ready_for_eval`
