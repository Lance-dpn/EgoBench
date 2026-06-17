#!/usr/bin/env bash
set -euo pipefail

cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

RUN_NAME="${1:-20260612-restaurant3-native-low-medium-repeat5}"
LOG_DIR="experiments/gpt55_frame_service_runner/cache/run_logs"
OUT_DIR="experiments/gpt55_frame_service_runner/cache/manual_reasoning_probe"
LOG_FILE="${LOG_DIR}/${RUN_NAME}.log"
OUT_FILE="${OUT_DIR}/${RUN_NAME}.json"

mkdir -p "${LOG_DIR}" "${OUT_DIR}"

conda run --no-capture-output -n egolink python -u \
  experiments/gpt55_frame_service_runner/visual_ablation_probe.py \
  --video videos/restaurant3.mp4 \
  --scenario restaurant \
  --scenario_number 3 \
  --frame_max_sides 1920 \
  --reasoning_efforts low,medium \
  --frame_fps 2 \
  --jpeg_quality 3 \
  --max_frames 0 \
  --image_detail high \
  --temperature 0 \
  --repeats 5 \
  --output "${OUT_FILE}" \
  2>&1 | tee "${LOG_FILE}"

echo "log=${LOG_FILE}"
echo "result=${OUT_FILE}"
