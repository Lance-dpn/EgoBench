# 候选集评估摘要：替换 kitchen4 新 DB 结果后

## 候选集路径

- 结果目录：`results/20260622-full-v51-plus-v53-userissue-retail6-order2full-five`
- 本次评估：`eval_result/20260622-full-v51-plus-v53-userissue-retail6-order2full-five/eval_after_kitchen4_newdb_replacement.json`
- 旧 kitchen4 备份：`results/20260622-full-v51-plus-v53-userissue-retail6-order2full-five/kitchen4_easy.before_newdb_4way_replacement.json`

## 本次替换内容

已将候选集中的旧 `kitchen4_easy.json` 替换为新 Kitchen DB 下 4-way rerun 的完整 50 个 task 结果。

来源分片：

- `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part1/kitchen4_easy.json`
- `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part2/kitchen4_easy.json`
- `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part3/kitchen4_easy.json`
- `results/20260622-rerun-kitchen4-newdb-4way-152929-kitchen4-fps0p5-part4/kitchen4_easy.json`

合并后覆盖 `task_id=1..50`，没有缺失或重复。

## 整体结果

| 指标 | 数值 |
|---|---:|
| Task 总数 | 309 |
| Joint success | 255 / 309 = 82.52% |
| Tool success | 260 / 309 = 84.14% |
| Result success | 261 / 309 = 84.47% |
| Final reply | 309 / 309 = 100.00% |
| Micro tool accuracy | 89.55% |

## 分场景结果

| 场景 | Joint | Tool | Result | Micro tool accuracy | 失败 task |
|---|---:|---:|---:|---:|---|
| kitchen4 | 48 / 50 = 96.00% | 48 / 50 = 96.00% | 48 / 50 = 96.00% | 97.48% | 46, 50 |
| order2 | 69 / 97 = 71.13% | 72 / 97 = 74.23% | 70 / 97 = 72.16% | 81.15% | 5, 13, 17, 23, 28, 32, 33, 34, 38, 39, 41, 48, 54, 58, 59, 61, 63, 64, 69, 75, 77, 78, 82, 86, 87, 89, 91, 96 |
| restaurant5 | 46 / 50 = 92.00% | 48 / 50 = 96.00% | 46 / 50 = 92.00% | 97.65% | 13, 20, 31, 49 |
| retail10 | 57 / 63 = 90.48% | 57 / 63 = 90.48% | 57 / 63 = 90.48% | 94.12% | 4, 5, 48, 49, 51, 61 |
| retail6 | 35 / 49 = 71.43% | 35 / 49 = 71.43% | 40 / 49 = 81.63% | 85.26% | 10, 14, 24, 25, 27, 30, 31, 32, 33, 41, 42, 43, 46, 47 |

## 与替换前相比

替换前候选集整体 Joint 为 236 / 309 = 76.38%。

替换后候选集整体 Joint 为 255 / 309 = 82.52%。

本次替换使整体 Joint 提升 19 个 task，约 +6.15 个百分点。提升来自 kitchen4 从 29 / 50 提升到 48 / 50。

## 当前主要剩余风险

1. `order2` 仍是当前候选集中最大的错误来源，剩余 28 个 joint failed task。之前启动的 order2 失败 task 3-way rerun 尚未合并到候选集。
2. `retail6` 的 Result 明显高于 Joint，说明部分任务最终状态或回答接近正确，但工具调用链和 GT 仍有不匹配，需要继续从日志定位。
3. `kitchen4` 替换后只剩 task 46 和 task 50 两个失败，之前定位分别偏向视觉识别错误和数量单位理解错误。
