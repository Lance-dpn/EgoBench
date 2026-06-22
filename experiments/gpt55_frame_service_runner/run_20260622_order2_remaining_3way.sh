#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/sda/dpn/egolink2026/code/track2/EgoBench"
PY="/home/dpn/miniconda3/envs/egolink/bin/python"
RUN_ID="${RUN_ID:-20260622-rerun-order2-remaining-setmeal-3way-$(date +%H%M%S)}"
SESSION="${SESSION:-order2_remaining_3way_${RUN_ID##*-}}"
LOG_DIR="$ROOT/experiments/gpt55_frame_service_runner/cache/run_logs/$RUN_ID"

mkdir -p "$LOG_DIR"

run_part() {
  local part="$1"
  local task_ids="$2"
  local out_name="${RUN_ID}-order2-fps2-${part}"
  local log_file="$LOG_DIR/${out_name}.log"

  {
    echo "run_name=$RUN_ID"
    echo "scenario=order2"
    echo "part=$part"
    echo "task_ids=$task_ids"
    echo "task_count=$(awk -F, '{print NF}' <<< "$task_ids")"
    echo "frame_fps=2"
    echo "output_model_name=$out_name"
    echo "started_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
    "$PY" -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
      --scenario order \
      --scenario_number 2 \
      --task_ids "$task_ids" \
      --output_model_name "$out_name" \
      --multi_agent_user \
      --summary_user \
      --service_reasoning_effort low \
      --enable_correction_agent \
      --resume \
      --continue_on_task_error \
      --frame_fps 2 \
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

# Remaining joint-failed order2 tasks after set-meal allergen GT recheck.
start_window "order2-g1" "g1" "5,23,33,39,54,61,69,78,87,96"
start_window "order2-g2" "g2" "13,28,34,41,58,63,75,82,89"
start_window "order2-g3" "g3" "17,32,38,48,59,64,77,86,91"

tmux list-windows -t "$SESSION"
