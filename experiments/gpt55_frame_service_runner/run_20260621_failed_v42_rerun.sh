#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/sda/dpn/egolink2026/code/track2/EgoBench"
PY="/home/dpn/miniconda3/envs/egolink/bin/python"
RUN_ID="${RUN_ID:-20260621-rerun-failed-v42-$(date +%H%M%S)}"
SESSION="${SESSION:-rerun_failed_v42_${RUN_ID##*-}}"
LOG_DIR="$ROOT/experiments/gpt55_frame_service_runner/cache/run_logs/$RUN_ID"

mkdir -p "$LOG_DIR"

run_scene() {
  local scenario="$1"
  local scenario_number="$2"
  local label="$3"
  local fps="$4"
  local task_ids="$5"
  local out_name="${RUN_ID}-${label}"
  local log_file="$LOG_DIR/${out_name}.log"

  {
    echo "run_name=$RUN_ID"
    echo "scenario=${scenario}${scenario_number}"
    echo "task_ids=$task_ids"
    echo "task_count=$(awk -F, '{print NF}' <<< "$task_ids")"
    echo "frame_fps=$fps"
    echo "output_model_name=$out_name"
    echo "started_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
    "$PY" -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
      --scenario "$scenario" \
      --scenario_number "$scenario_number" \
      --task_ids "$task_ids" \
      --output_model_name "$out_name" \
      --multi_agent_user \
      --summary_user \
      --service_reasoning_effort low \
      --enable_correction_agent \
      --resume \
      --continue_on_task_error \
      --frame_fps "$fps" \
      --frame_max_side 1920 \
      --frame_rotation none \
      --image_detail high \
      --frame_attach_policy auto
    echo "finished_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
  } 2>&1 | tee -a "$log_file"
}

start_window() {
  local window="$1"
  local command="$2"
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-window -t "$SESSION:" -n "$window" "cd '$ROOT' && source .env && $command"
  else
    tmux new-session -d -s "$SESSION" -n "$window" "cd '$ROOT' && source .env && $command"
  fi
}

if [[ "${1:-}" == "__run" ]]; then
  shift
  run_scene "$@"
  exit 0
fi

echo "RUN_ID=$RUN_ID"
echo "SESSION=$SESSION"
echo "LOG_DIR=$LOG_DIR"

start_window "retail6" "bash '$0' __run retail 6 retail6-fps1 1 '5,8,10,11,14,15,17,21,22,23,24,25,27,28,29,30,31,32,33,35,39,41,42,43,48,49'"
start_window "retail10" "bash '$0' __run retail 10 retail10-fps0p5 0.5 '4,5,12,19,26,28,36,48,49'"
start_window "kitchen4" "bash '$0' __run kitchen 4 kitchen4-fps0p5 0.5 '6,9,13,14,19,29,30,37,41,42,44,47'"
start_window "restaurant5" "bash '$0' __run restaurant 5 restaurant5-fps1 1 '9,10,12,14,16,18,27,31,43,44,46,47,50'"
start_window "order2" "bash '$0' __run order 2 order2-fps2 2 '4,5,9,13,16,21,25,27,37,39,41,48,53,63,69,71,72,73,81,91,96'"

tmux list-windows -t "$SESSION"
