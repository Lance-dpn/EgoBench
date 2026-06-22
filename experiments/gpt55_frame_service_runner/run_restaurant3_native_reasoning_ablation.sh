#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python}"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

RUN_NAME="${1:-20260612-restaurant3-native-reasoning-ablation}"
LOG_DIR="experiments/gpt55_frame_service_runner/cache/run_logs"
OUT_DIR="experiments/gpt55_frame_service_runner/cache/manual_reasoning_probe"
LOG_FILE="${LOG_DIR}/${RUN_NAME}.log"
OUT_FILE="${OUT_DIR}/${RUN_NAME}.json"

mkdir -p "${LOG_DIR}" "${OUT_DIR}"

"$PY" -u \
  experiments/gpt55_frame_service_runner/visual_ablation_probe.py \
  --video videos/restaurant3.mp4 \
  --scenario restaurant \
  --scenario_number 3 \
  --frame_max_sides 1920 \
  --reasoning_efforts none,low,medium,high \
  --frame_fps 2 \
  --jpeg_quality 3 \
  --max_frames 0 \
  --image_detail high \
  --temperature 0 \
  --repeats 1 \
  --output "${OUT_FILE}" \
  2>&1 | tee "${LOG_FILE}"

echo "log=${LOG_FILE}"
echo "result=${OUT_FILE}"
