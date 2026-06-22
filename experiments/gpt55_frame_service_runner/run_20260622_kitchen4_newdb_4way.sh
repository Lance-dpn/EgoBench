#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python}"
RUN_ID="${RUN_ID:-20260622-rerun-kitchen4-newdb-4way-$(date +%H%M%S)}"
SESSION="${SESSION:-kitchen4_newdb_4way_${RUN_ID##*-}}"
LOG_DIR="$ROOT/experiments/gpt55_frame_service_runner/cache/run_logs/$RUN_ID"

mkdir -p "$LOG_DIR"

run_part() {
  local part="$1"
  local task_ids="$2"
  local out_name="${RUN_ID}-kitchen4-fps0p5-${part}"
  local log_file="$LOG_DIR/${out_name}.log"

  {
    echo "run_name=$RUN_ID"
    echo "scenario=kitchen4"
    echo "part=$part"
    echo "task_ids=$task_ids"
    echo "task_count=$(awk -F, '{print NF}' <<< "$task_ids")"
    echo "frame_fps=0.5"
    echo "output_model_name=$out_name"
    echo "started_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
    "$PY" -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
      --scenario kitchen \
      --scenario_number 4 \
      --task_ids "$task_ids" \
      --output_model_name "$out_name" \
      --multi_agent_user \
      --summary_user \
      --service_reasoning_effort low \
      --enable_correction_agent \
      --resume \
      --continue_on_task_error \
      --frame_fps 0.5 \
      --frame_max_side 1920 \
      --frame_rotation none \
      --image_detail high \
      --frame_attach_policy auto
    echo "finished_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
  } 2>&1 | tee -a "$log_file"
}

start_window() {
  local window="$1"
  local part="$2"
  local task_ids="$3"
  local command="RUN_ID='$RUN_ID' SESSION='$SESSION' bash '$0' __run '$part' '$task_ids'"
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-window -t "$SESSION:" -n "$window" "cd '$ROOT' && source .env && $command"
  else
    tmux new-session -d -s "$SESSION" -n "$window" "cd '$ROOT' && source .env && $command"
  fi
}

if [[ "${1:-}" == "__run" ]]; then
  shift
  run_part "$@"
  exit 0
fi

echo "RUN_ID=$RUN_ID"
echo "SESSION=$SESSION"
echo "LOG_DIR=$LOG_DIR"

start_window "part1" "part1" "1,2,3,4,5,6,7,8,9,10,11,12,13"
start_window "part2" "part2" "14,15,16,17,18,19,20,21,22,23,24,25,26"
start_window "part3" "part3" "27,28,29,30,31,32,33,34,35,36,37,38"
start_window "part4" "part4" "39,40,41,42,43,44,45,46,47,48,49,50"

tmux list-windows -t "$SESSION"
