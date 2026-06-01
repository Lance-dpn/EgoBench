#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

declare -A EXTERNAL_ENV=()
for key in ${!OBSERVER_@}; do
  EXTERNAL_ENV["$key"]="${!key}"
done

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

for key in "${!EXTERNAL_ENV[@]}"; do
  export "$key=${EXTERNAL_ENV[$key]}"
done

HOST="${OBSERVER_HOST:-127.0.0.1}"
PORT="${OBSERVER_PORT:-18082}"
SESSION="${OBSERVER_TMUX_SESSION:-visual_observer}"
CONDA_ENV="${OBSERVER_CONDA_ENV:-egolink}"

MODE="${OBSERVER_MODEL_PROVIDER:-local}"
EVENT_PROVIDER="${OBSERVER_EVENT_PROVIDER:-$MODE}"
DETAIL_PROVIDER="${OBSERVER_DETAIL_PROVIDER:-$MODE}"

LOCAL_BASE_URL="${OBSERVER_LOCAL_BASE_URL:-http://127.0.0.1:8000/v1}"
LOCAL_MODEL="${OBSERVER_LOCAL_MODEL:-qwen3.6-27b-fp8}"
ONLINE_BASE_URL="${OBSERVER_ONLINE_BASE_URL:-${QWEN_VL_API_BASE_URL:-${QW_SERVICE_API_BASE_URL:-${SERVICE_API_BASE_URL:-}}}}"
ONLINE_API_KEY="${OBSERVER_ONLINE_API_KEY:-${QWEN_VL_API_KEY:-${QW_SERVICE_API_KEY:-${SERVICE_API_KEY:-${API_KEY:-}}}}}"
ONLINE_MODEL="${OBSERVER_ONLINE_MODEL:-${QWEN_VL_MODEL:-${QW_SERVICE_MODEL_NAME:-qwen3-vl-225b}}}"

EVENT_THINKING="${OBSERVER_EVENT_THINKING:-on}"
DETAIL_THINKING="${OBSERVER_DETAIL_THINKING:-off}"
INCLUDE_REASONING="${OBSERVER_INCLUDE_REASONING:-off}"
EVENT_HIGH_RESOLUTION_IMAGES="${OBSERVER_EVENT_HIGH_RESOLUTION_IMAGES:-off}"
DETAIL_HIGH_RESOLUTION_IMAGES="${OBSERVER_DETAIL_HIGH_RESOLUTION_IMAGES:-on}"

EVENT_MAX_TOKENS="${OBSERVER_EVENT_MAX_TOKENS:-4096}"
DETAIL_MAX_TOKENS="${OBSERVER_DETAIL_MAX_TOKENS:-1024}"
QWEN_TIMEOUT="${OBSERVER_QWEN_TIMEOUT:-300}"
EVENT_THINKING_BUDGET="${OBSERVER_EVENT_THINKING_BUDGET:-}"
DETAIL_THINKING_BUDGET="${OBSERVER_DETAIL_THINKING_BUDGET:-}"
EVENT_TEMPERATURE="${OBSERVER_EVENT_TEMPERATURE:-0.3}"
DETAIL_TEMPERATURE="${OBSERVER_DETAIL_TEMPERATURE:-0.0}"
SEQUENCE_FRAMES="${OBSERVER_SEQUENCE_FRAMES:-8}"
if [[ "$EVENT_PROVIDER" == "local" ]]; then
  DEFAULT_TEMPORAL_EVENT_BACKEND="qwen_video"
  DEFAULT_EVENT_FRAME_FPS="1"
  DEFAULT_EVENT_MAX_FRAMES="16"
else
  DEFAULT_TEMPORAL_EVENT_BACKEND="qwen_video"
  DEFAULT_EVENT_FRAME_FPS="2"
  DEFAULT_EVENT_MAX_FRAMES="32"
fi
TEMPORAL_EVENT_BACKEND="${OBSERVER_TEMPORAL_EVENT_BACKEND:-$DEFAULT_TEMPORAL_EVENT_BACKEND}"
EVENT_FRAME_FPS="${OBSERVER_EVENT_FRAME_FPS:-$DEFAULT_EVENT_FRAME_FPS}"
EVENT_MAX_FRAMES="${OBSERVER_EVENT_MAX_FRAMES:-$DEFAULT_EVENT_MAX_FRAMES}"
FRAME_MAX_SIDE="${OBSERVER_FRAME_MAX_SIDE:-1024}"
DETAIL_SAMPLE_FPS="${OBSERVER_DETAIL_SAMPLE_FPS:-2}"
DETAIL_BOUNDARY_OFFSET="${OBSERVER_DETAIL_BOUNDARY_OFFSET:-0.25}"
SEQUENCE_WINDOW_SECONDS="${OBSERVER_SEQUENCE_WINDOW_SECONDS:-1.5}"
TRACE_DETAIL="${OBSERVER_TRACE_DETAIL:-compact}"
QWEN_VIDEO_URL_MODE="${OBSERVER_QWEN_VIDEO_URL_MODE:-auto}"
QWEN_VIDEO_FPS="${OBSERVER_QWEN_VIDEO_FPS:-2}"
VIDEO_URL_BASE="${OBSERVER_VIDEO_URL_BASE:-${VIDEO_URL_BASE:-}}"
STARTUP_TIMEOUT_SECONDS="${OBSERVER_STARTUP_TIMEOUT_SECONDS:-20}"

provider_base_url() {
  case "$1" in
    local) printf '%s' "$LOCAL_BASE_URL" ;;
    online) printf '%s' "$ONLINE_BASE_URL" ;;
    *) echo "Unknown provider: $1" >&2; exit 2 ;;
  esac
}

provider_api_key() {
  case "$1" in
    local) printf '%s' "EMPTY" ;;
    online) printf '%s' "$ONLINE_API_KEY" ;;
    *) echo "Unknown provider: $1" >&2; exit 2 ;;
  esac
}

provider_model() {
  case "$1" in
    local) printf '%s' "$LOCAL_MODEL" ;;
    online) printf '%s' "$ONLINE_MODEL" ;;
    *) echo "Unknown provider: $1" >&2; exit 2 ;;
  esac
}

is_legacy_qwen3_vl_model() {
  local model_lc
  model_lc="${1,,}"
  [[ "$model_lc" == qwen3-vl* || "$model_lc" == qwen3_vl* ]]
}

is_thinking_on() {
  case "${1,,}" in
    on|true|1|yes|y) return 0 ;;
    *) return 1 ;;
  esac
}

EVENT_BASE_URL="${OBSERVER_EVENT_BASE_URL:-$(provider_base_url "$EVENT_PROVIDER")}"
EVENT_API_KEY="${OBSERVER_EVENT_API_KEY:-$(provider_api_key "$EVENT_PROVIDER")}"
EVENT_MODEL="${OBSERVER_EVENT_MODEL:-$(provider_model "$EVENT_PROVIDER")}"
DETAIL_BASE_URL="${OBSERVER_DETAIL_BASE_URL:-$(provider_base_url "$DETAIL_PROVIDER")}"
DETAIL_API_KEY="${OBSERVER_DETAIL_API_KEY:-$(provider_api_key "$DETAIL_PROVIDER")}"
DETAIL_MODEL="${OBSERVER_DETAIL_MODEL:-$(provider_model "$DETAIL_PROVIDER")}"

if [[ "$EVENT_PROVIDER" == "online" ]] && is_legacy_qwen3_vl_model "$EVENT_MODEL" && is_thinking_on "$EVENT_THINKING"; then
  echo "event: disabling thinking for $EVENT_MODEL; this online Qwen3-VL model rejects thinking_budget/enable_thinking." >&2
  EVENT_THINKING="off"
  EVENT_THINKING_BUDGET=""
fi
if [[ "$DETAIL_PROVIDER" == "online" ]] && is_legacy_qwen3_vl_model "$DETAIL_MODEL" && is_thinking_on "$DETAIL_THINKING"; then
  echo "detail: disabling thinking for $DETAIL_MODEL; this online Qwen3-VL model rejects thinking_budget/enable_thinking." >&2
  DETAIL_THINKING="off"
  DETAIL_THINKING_BUDGET=""
fi
if ! is_thinking_on "$EVENT_THINKING"; then
  EVENT_THINKING_BUDGET=""
fi
if ! is_thinking_on "$DETAIL_THINKING"; then
  DETAIL_THINKING_BUDGET=""
fi

if [[ -z "$EVENT_BASE_URL" || -z "$DETAIL_BASE_URL" ]]; then
  echo "Missing observer base URL. Set OBSERVER_LOCAL_BASE_URL or OBSERVER_ONLINE_BASE_URL." >&2
  exit 2
fi

cmd=(
  conda run -n "$CONDA_ENV" python experiments/visual_observer_runner/observer_server.py
  --host "$HOST"
  --port "$PORT"
  --event_localizer_backend qwen_video
  --temporal_event_backend "$TEMPORAL_EVENT_BACKEND"
  --qwen_event_api_base_url "$EVENT_BASE_URL"
  --qwen_event_api_key "$EVENT_API_KEY"
  --qwen_event_model "$EVENT_MODEL"
  --qwen_event_temperature "$EVENT_TEMPERATURE"
  --qwen_event_max_tokens "$EVENT_MAX_TOKENS"
  --qwen_event_thinking "$EVENT_THINKING"
  --qwen_event_high_resolution_images "$EVENT_HIGH_RESOLUTION_IMAGES"
  --qwen_timeout "$QWEN_TIMEOUT"
  --qwen_detail_api_base_url "$DETAIL_BASE_URL"
  --qwen_detail_api_key "$DETAIL_API_KEY"
  --qwen_detail_model "$DETAIL_MODEL"
  --qwen_detail_temperature "$DETAIL_TEMPERATURE"
  --qwen_detail_max_tokens "$DETAIL_MAX_TOKENS"
  --qwen_detail_thinking "$DETAIL_THINKING"
  --qwen_detail_high_resolution_images "$DETAIL_HIGH_RESOLUTION_IMAGES"
  --qwen_video_url_mode "$QWEN_VIDEO_URL_MODE"
  --qwen_video_fps "$QWEN_VIDEO_FPS"
  --event_frame_fps "$EVENT_FRAME_FPS"
  --event_max_frames "$EVENT_MAX_FRAMES"
  --frame_max_side "$FRAME_MAX_SIDE"
  --sequence_frames "$SEQUENCE_FRAMES"
  --detail_sample_fps "$DETAIL_SAMPLE_FPS"
  --detail_boundary_offset "$DETAIL_BOUNDARY_OFFSET"
  --sequence_window_seconds "$SEQUENCE_WINDOW_SECONDS"
  --trace_detail "$TRACE_DETAIL"
)

if [[ -n "$EVENT_THINKING_BUDGET" ]]; then
  cmd+=(--qwen_event_thinking_budget "$EVENT_THINKING_BUDGET")
fi
if [[ -n "$DETAIL_THINKING_BUDGET" ]]; then
  cmd+=(--qwen_detail_thinking_budget "$DETAIL_THINKING_BUDGET")
fi
if [[ "$INCLUDE_REASONING" == "on" || "$INCLUDE_REASONING" == "true" || "$INCLUDE_REASONING" == "1" ]]; then
  cmd+=(--qwen_include_reasoning)
fi
if [[ -n "$VIDEO_URL_BASE" ]]; then
  cmd+=(--video_url_base "$VIDEO_URL_BASE")
fi

printf 'Starting observer in tmux session %s\n' "$SESSION"
printf 'event:  provider=%s model=%s thinking=%s thinking_budget=%s high_res_images=%s base=%s\n' "$EVENT_PROVIDER" "$EVENT_MODEL" "$EVENT_THINKING" "${EVENT_THINKING_BUDGET:-<unset>}" "$EVENT_HIGH_RESOLUTION_IMAGES" "$EVENT_BASE_URL"
printf 'detail: provider=%s model=%s thinking=%s thinking_budget=%s high_res_images=%s base=%s\n' "$DETAIL_PROVIDER" "$DETAIL_MODEL" "$DETAIL_THINKING" "${DETAIL_THINKING_BUDGET:-<unset>}" "$DETAIL_HIGH_RESOLUTION_IMAGES" "$DETAIL_BASE_URL"
printf 'video:  qwen_video_url_mode=%s fps=%s public_base=%s\n' "$QWEN_VIDEO_URL_MODE" "$QWEN_VIDEO_FPS" "${VIDEO_URL_BASE:-<mapping/env>}"
printf 'temporal events: backend=%s frame_fps=%s max_frames=%s frame_max_side=%s\n' "$TEMPORAL_EVENT_BACKEND" "$EVENT_FRAME_FPS" "$EVENT_MAX_FRAMES" "$FRAME_MAX_SIDE"

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" "$(printf '%q ' "${cmd[@]}")"

health_url="http://${HOST}:${PORT}/health"
printf 'Waiting for observer health: %s\n' "$health_url"

for ((i = 1; i <= STARTUP_TIMEOUT_SECONDS; i++)); do
  if health="$(curl -fsS "$health_url" 2>/dev/null)"; then
    printf 'Observer health after startup:\n'
    if command -v jq >/dev/null 2>&1; then
      printf '%s\n' "$health" | jq .
    else
      printf '%s\n' "$health"
    fi
    exit 0
  fi
  sleep 1
done

echo "Observer health did not become ready within ${STARTUP_TIMEOUT_SECONDS}s." >&2
echo "This often means the port is already occupied or the observer crashed during startup." >&2
echo >&2
echo "Check the current listener:" >&2
echo "  ss -ltnp | grep ':${PORT}'" >&2
echo >&2
echo "Check observer processes:" >&2
echo "  ps -ef | grep -E 'observer_server.py|${PORT}' | grep -v grep" >&2
echo >&2
echo "Check the tmux session log:" >&2
echo "  tmux capture-pane -t ${SESSION} -p | tail -120" >&2
echo >&2
echo "If a stale non-tmux observer is occupying the port, stop only that confirmed PID, for example:" >&2
echo "  kill <PID>" >&2
exit 1
