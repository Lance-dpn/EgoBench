#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/sda/dpn/egolink2026/code/track2/EgoBench"
SESSION="gt-instruction-tools-20260619-v7"
RUN_DIR="$ROOT/experiments/visual_observer_runner/eval/instruction_tool_runs/20260619_full_v7"
SCRIPT="experiments/visual_observer_runner/eval/generate_gt_from_instruction_with_tools.py"

mkdir -p "$RUN_DIR/logs"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already exists: $SESSION" >&2
  exit 1
fi

start_window() {
  local scenario="$1"
  local cmd
  cmd="cd '$ROOT' && python -u '$SCRIPT' --scenarios '$scenario' --max_steps 20 --timeout 120 --report '$RUN_DIR/$scenario.json' --jsonl_report '$RUN_DIR/$scenario.jsonl' 2>&1 | tee -a '$RUN_DIR/logs/$scenario.log'"
  if [[ "$scenario" == "retail6" ]]; then
    tmux new-session -d -s "$SESSION" -n "$scenario" "$cmd"
  else
    tmux new-window -t "$SESSION" -n "$scenario" "$cmd"
  fi
}

start_window retail6
start_window retail10
start_window restaurant5
start_window kitchen4
start_window order2

echo "started $SESSION"
echo "logs: $RUN_DIR/logs"
