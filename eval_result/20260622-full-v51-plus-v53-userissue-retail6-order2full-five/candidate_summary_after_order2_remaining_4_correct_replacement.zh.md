# 候选集评估摘要：替换 order2 四个正确复跑样本后

## 替换内容

已将本轮 order2 失败 task 三路复跑中 joint 通过的 4 个样本替换进候选集：

- `task_id=23`
- `task_id=28`
- `task_id=38`
- `task_id=96`

候选集文件：

- `results/20260622-full-v51-plus-v53-userissue-retail6-order2full-five/order2_easy.json`

替换前备份：

- `results/20260622-full-v51-plus-v53-userissue-retail6-order2full-five/order2_easy.before_order2_remaining_4_correct_replacement.json`

替换来源：

- `results/20260622-rerun-order2-remaining-setmeal-3way-173911-order2-fps2-g1/order2_easy.json`
- `results/20260622-rerun-order2-remaining-setmeal-3way-173911-order2-fps2-g2/order2_easy.json`
- `results/20260622-rerun-order2-remaining-setmeal-3way-173911-order2-fps2-g3/order2_easy.json`

## 最新整体评估

评估结果：

- `eval_result/20260622-full-v51-plus-v53-userissue-retail6-order2full-five/eval_after_order2_remaining_4_correct_replacement.json`

| 指标 | 数值 |
|---|---:|
| Task 总数 | 309 |
| Joint success | 259 / 309 = 83.82% |
| Tool success | 262 / 309 = 84.79% |
| Result success | 265 / 309 = 85.76% |
| Final reply | 309 / 309 = 100.00% |
| Micro tool accuracy | 89.81% |

## 分场景结果

| 场景 | Joint | 剩余失败 task |
|---|---:|---|
| kitchen4 | 48 / 50 = 96.00% | 46, 50 |
| order2 | 73 / 97 = 75.26% | 5, 13, 17, 32, 33, 34, 39, 41, 48, 54, 58, 59, 61, 63, 64, 69, 75, 77, 78, 82, 86, 87, 89, 91 |
| restaurant5 | 46 / 50 = 92.00% | 13, 20, 31, 49 |
| retail10 | 57 / 63 = 90.48% | 4, 5, 48, 49, 51, 61 |
| retail6 | 35 / 49 = 71.43% | 10, 14, 24, 25, 27, 30, 31, 32, 33, 41, 42, 43, 46, 47 |

## 与上一步相比

替换 order2 4 个正确样本前：

- Joint：255 / 309 = 82.52%
- order2：69 / 97 = 71.13%

替换后：

- Joint：259 / 309 = 83.82%
- order2：73 / 97 = 75.26%

本次替换使整体 Joint 提升 4 个 task，约 +1.29 个百分点。
