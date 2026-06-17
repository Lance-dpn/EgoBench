#!/usr/bin/env bash
set -euo pipefail

cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

LOG_DIR="experiments/gpt55_frame_service_runner/cache/run_logs"
mkdir -p "${LOG_DIR}"

run_task() {
  local scenario="$1"
  local scenario_number="$2"
  local task_id="$3"
  local output_name="$4"
  local log_file="${LOG_DIR}/${output_name}.log"

  echo "===== START ${output_name} $(date '+%Y-%m-%d %H:%M:%S') ====="
  echo "scenario=${scenario}${scenario_number} task_id=${task_id}"
  echo "log=${log_file}"

  conda run --no-capture-output -n egolink python -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
    --scenario "${scenario}" \
    --scenario_number "${scenario_number}" \
    --task_ids "${task_id}" \
    --output_model_name "${output_name}" \
    --enable_correction_agent \
    --correction_api_type responses \
    --correction_on_max_rounds stop \
    --multi_agent_user \
    --summary_user \
    --frame_fps 2 \
    --frame_max_side 1536 \
    --image_detail high \
    --frame_attach_policy auto \
    2>&1 | tee "${log_file}"

  echo "===== END ${output_name} $(date '+%Y-%m-%d %H:%M:%S') ====="
}

run_task retail 3 7 20260609-gpt55-correction-retail3-t7
run_task restaurant 3 10 20260609-gpt55-correction-restaurant3-t10
run_task order 1 1 20260609-gpt55-correction-order1-t1
run_task kitchen 2 13 20260609-gpt55-correction-kitchen2-t13
