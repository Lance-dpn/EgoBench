#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/sda/dpn/egolink2026/code/track2/EgoBench"
PY="/home/dpn/miniconda3/envs/egolink/bin/python"
RUN_ID="20260621-local50-v42-002837"
SESSION="local50_v42_002837"
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

start_window "retail6" "bash '$0' __run retail 6 retail6-fps1 1 '1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49'"
start_window "retail10" "bash '$0' __run retail 10 retail10-fps0p5 0.5 '1,3,4,5,6,7,8,9,10,11,12,13,14,15,17,19,20,22,23,24,25,26,27,28,29,31,33,34,36,37,38,39,40,41,43,44,45,46,48,49,52,53,54,56,57,58,59,60,61,62'"
start_window "kitchen4" "bash '$0' __run kitchen 4 kitchen4-fps0p5 0.5 '1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50'"
start_window "restaurant5" "bash '$0' __run restaurant 5 restaurant5-fps1 1 '1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50'"
start_window "order2" "bash '$0' __run order 2 order2-fps2 2 '2,4,5,6,8,9,11,12,13,15,16,21,24,25,27,29,30,31,35,37,39,41,42,45,47,48,49,50,52,53,56,57,58,62,63,65,69,71,72,73,79,81,82,83,85,90,91,94,95,96'"

tmux list-windows -t "$SESSION"
