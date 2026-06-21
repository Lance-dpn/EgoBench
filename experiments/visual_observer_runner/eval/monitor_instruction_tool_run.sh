#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:-experiments/visual_observer_runner/eval/instruction_tool_runs/20260619_full_v8}"

python experiments/visual_observer_runner/eval/summarize_instruction_tool_run.py \
  "$RUN_DIR" \
  --output "$RUN_DIR/summary_latest.json"

python experiments/visual_observer_runner/eval/classify_instruction_tool_run.py \
  "$RUN_DIR" \
  --output "$RUN_DIR/classification_latest.json"

python - "$RUN_DIR/classification_latest.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
records = data.get("records", {})
bad = []
for scenario, items in sorted(records.items()):
    for item in items:
        if item.get("label") != "exact_match":
            bad.append(item)
if not bad:
    print("non_exact: none")
else:
    print("non_exact:")
    for item in bad:
        print(
            f"- {item.get('scenario')} task {item.get('task_id')}: "
            f"{item.get('label')} first_diff={item.get('first_diff')}"
        )
PY
