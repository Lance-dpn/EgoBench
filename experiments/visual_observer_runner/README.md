# Visual Observer Runner

This experiment path keeps the current two-stage observer design:

1. A local Qwen3-VL video model watches the original video and localizes the
   user-referenced event.
2. The observer extracts an ordered short frame sequence from that event time
   range.
3. The Qwen API observer model reads the frame sequence and returns one
   visual anchor key/value fact per localized referent.
4. The service agent uses those visual anchors, then grounds all customer-facing
   facts through scenario tools.

Old MiniMax and single-keyframe observer paths were removed from the active
code. New manual runs should use the `qwen_video` observer shown below.

## 1. Current Manual Reproduction

Run commands from EgoBench:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench
```

The current split is:

```text
stage 1 event localization:
  local vLLM Qwen3-VL-FP8
  http://127.0.0.1:8000/v1
  qwen3-vl-32b-fp8

stage 2 image-sequence recognition:
  Qwen API credentials from .env
  QW_SERVICE_API_KEY
  QW_SERVICE_API_BASE_URL
  QW_OBSERVER_MODEL_NAME=qwen3-vl-32b-instruct
```

### 1.1 Check Local Video Model

The local video model must be running and must have been started with local
media access:

```text
--allowed-local-media-path /mnt/sda/dpn/egolink2026
```

Check it:

```bash
curl -sS http://127.0.0.1:8000/v1/models | jq
```

Expected model id:

```text
qwen3-vl-32b-fp8
```

If it is not running, start it from the model directory:

```bash
cd /mnt/sda/dpn/egolink2026

tmux kill-session -t qwen3vl 2>/dev/null || true
tmux new-session -d -s qwen3vl \
  'cd /mnt/sda/dpn/egolink2026/model && exec env CUDA_VISIBLE_DEVICES=1,2 VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_LOGGING_LEVEL=INFO ./vllm-venv/bin/vllm serve /mnt/sda/dpn/egolink2026/model/Qwen3-VL-32B-Instruct-FP8 --served-model-name qwen3-vl-32b-fp8 --host 0.0.0.0 --port 8000 --tensor-parallel-size 2 --max-model-len 32768 --gpu-memory-utilization 0.88 --trust-remote-code --enforce-eager --disable-custom-all-reduce --max-num-seqs 8 --allowed-local-media-path /mnt/sda/dpn/egolink2026'
```

Startup takes several minutes.

### 1.2 Check Qwen API Observer Variables

The observer server loads `.env` at startup. Confirm these variables exist
without printing API key values:

```bash
grep -E '^(export[[:space:]]+)?(QW_SERVICE_API_KEY|QW_SERVICE_API_BASE_URL|QW_OBSERVER_MODEL_NAME)=' .env \
  | sed -E 's/(API_KEY)=.*/\1=<redacted>/'
```

Expected relevant variables:

```text
QW_SERVICE_API_KEY=<redacted>
QW_SERVICE_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QW_OBSERVER_MODEL_NAME=qwen3-vl-32b-instruct
```

### 1.3 Start The Observer

Use `--qwen_event_*` for the local video model. Do not use global
`--qwen_model` here, because that would also affect fallback/default resolution.
The detail stage will use `.env`:

```bash
cd /mnt/sda/dpn/egolink2026

tmux kill-session -t visual_observer 2>/dev/null || true
tmux kill-session -t aura_qwenvl_observer 2>/dev/null || true
tmux new-session -d -s visual_observer \
  'cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench && source .env && conda run -n egolink python experiments/visual_observer_runner/observer_server.py --host 127.0.0.1 --port 18082 --event_localizer_backend qwen_video --qwen_event_api_base_url http://127.0.0.1:8000/v1 --qwen_event_api_key EMPTY --qwen_event_model qwen3-vl-32b-fp8 --qwen_event_temperature 0.3 --qwen_event_max_tokens 2048 --qwen_event_enable_thinking --qwen_detail_temperature 0.0 --qwen_detail_max_tokens 1024 --sequence_frames 8 --detail_sample_fps 2 --detail_boundary_offset 0.25 --sequence_window_seconds 1.5 --trace_detail compact'
```

If `visual_observer` does not appear in `tmux ls`, check whether port `18082`
is already occupied by an old observer:

```bash
ss -ltnp | grep 18082
curl -sS http://127.0.0.1:18082/health | jq
```

The current observer should report:

```text
observer=visual_event_qwen_sequence
stages.event_localizer.backend=qwen_video
```

If health reports `aura_qwenvl_sequence` or `aura_minimax_observer.py`, stop the
old session first:

```bash
tmux kill-session -t aura_qwenvl_observer
```

Or run it in the foreground for debugging:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

source .env
conda run -n egolink python experiments/visual_observer_runner/observer_server.py \
  --host 127.0.0.1 \
  --port 18082 \
  --event_localizer_backend qwen_video \
  --qwen_event_api_base_url http://127.0.0.1:8000/v1 \
  --qwen_event_api_key EMPTY \
  --qwen_event_model qwen3-vl-32b-fp8 \
  --qwen_event_temperature 0.3 \
  --qwen_event_max_tokens 2048 \
  --qwen_event_enable_thinking \
  --qwen_detail_temperature 0.0 \
  --qwen_detail_max_tokens 1024 \
  --sequence_frames 8 \
  --detail_sample_fps 2 \
  --detail_boundary_offset 0.25 \
  --sequence_window_seconds 1.5 \
  --trace_detail compact
```

### 1.4 Health Check

```bash
curl -sS http://127.0.0.1:18082/health | jq
```

Expected important fields:

```json
{
  "status": "ok",
  "observer": "visual_event_qwen_sequence",
  "stages": {
    "event_localizer": {
      "backend": "qwen_video",
      "input": "original_video",
      "base_url": "http://127.0.0.1:8000/v1",
      "model": "qwen3-vl-32b-fp8",
      "request_level_fps": null,
      "generation": {
        "temperature": 0.3,
        "max_tokens": 2048,
        "enable_thinking": true
      }
    },
    "detail_recognizer": {
      "input": "ordered_original_size_frames",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "model": "qwen3-vl-32b-instruct",
      "generation": {
        "temperature": 0.0,
        "max_tokens": 1024,
        "enable_thinking": false
      },
      "max_frames": 8,
      "sample_fps": 2.0,
      "boundary_offset_seconds": 0.25,
      "frame_resize": "none",
      "frame_format": "png"
    }
  }
}
```

This confirms that stage 1 uses the local FP8 video model and stage 2 uses the
Qwen API observer model from `.env`.

## 2. Manual Retail1 Reproduction

The following commands reproduce three separate wine-name probes. They each ask
about one referent only. Treat the returned `observation.visual_key_values[0]`
as the observer result; model output can change after prompt, sampling, or model
updates.

### First Pointed Wine

```bash
curl -sS --max-time 900 http://127.0.0.1:18082/observe \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "retail1_manual_first_wine_name_separate",
    "experiment_id": "manual-qwen-video-separate-wine-names",
    "experiment_timestamp": "manual-qwen-video-separate-wine-names",
    "scenario": "retail",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/retail1.mp4",
    "image_description": "You are currently in front of a wine shelf and have pointed to three bottles of wine in succession.",
    "current_user_message": "What is the name of the first wine I pointed at?"
  }'
```

Recent observed result after switching detail frames to original-size PNG:

```text
Oyster Bay Merlot
```

### Second Pointed Wine

```bash
curl -sS --max-time 900 http://127.0.0.1:18082/observe \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "retail1_manual_second_wine_name_separate",
    "experiment_id": "manual-qwen-video-separate-wine-names",
    "experiment_timestamp": "manual-qwen-video-separate-wine-names",
    "scenario": "retail",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/retail1.mp4",
    "image_description": "You are currently in front of a wine shelf and have pointed to three bottles of wine in succession.",
    "current_user_message": "What is the name of the second wine I pointed at?"
  }'
```

Recent observed result before the original-size PNG change:

```text
River Terrace
```

### Third Pointed Wine

```bash
curl -sS --max-time 900 http://127.0.0.1:18082/observe \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "retail1_manual_third_wine_name_separate",
    "experiment_id": "manual-qwen-video-separate-wine-names",
    "experiment_timestamp": "manual-qwen-video-separate-wine-names",
    "scenario": "retail",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/retail1.mp4",
    "image_description": "You are currently in front of a wine shelf and have pointed to three bottles of wine in succession.",
    "current_user_message": "What is the name of the third wine I pointed at?"
  }'
```

Recent observed result before the original-size PNG change:

```text
KING OF WINE
```

### Inspect The Manual Trace

The trace path is returned in the `/observe` response as `trace_path`. With the
example `experiment_timestamp` and `experiment_id` above, it is:

```text
experiments/visual_observer_runner/cache/visual_observer/runs/manual-qwen-video-separate-wine-names/manual-qwen-video-separate-wine-names/traces/retail1.json
```

Summarize the predicted names, localized time ranges, and sampled frame
timestamps:

```bash
jq '.tasks
  | to_entries[]
  | select(.key|test("retail1_manual_(first|second|third)_wine_name_separate"))
  | {
      task: .key,
      value: .value.observations[-1].observation.visual_key_values[0].value,
      confidence: .value.observations[-1].observation.visual_key_values[0].confidence,
      event_range: .value.observations[-1].observation.visual_referents[0].event_time_range,
      timestamps: .value.observations[-1].observation.detail_evidence[0].timestamps
    }' \
  experiments/visual_observer_runner/cache/visual_observer/runs/manual-qwen-video-separate-wine-names/manual-qwen-video-separate-wine-names/traces/retail1.json
```

Example summary format:

```text
first  -> Oyster Bay Merlot,     frames [0.95, 1.2, 1.7, 1.95]
second -> River Terrace,        frames [2.45, 2.7, 3.2, 3.7, 4.05]
third  -> KING OF WINE,         frames [5.12, 5.37, 5.87, 6.37, 6.67]
```

Extracted frames are under:

```text
experiments/visual_observer_runner/cache/visual_observer/runs/manual-qwen-video-separate-wine-names/manual-qwen-video-separate-wine-names/keyframes/
```

## 3. Configuration Details

QwenVL API configuration is split by stage:

```text
event:  --qwen_event_* > QW_EVENT_OBSERVER_* > --qwen_* > shared env
detail: --qwen_detail_* > QW_DETAIL_OBSERVER_* > QW_OBSERVER_MODEL_NAME + QW_SERVICE_* > --qwen_* > shared env
```

Use explicit `--qwen_event_*` arguments for the local video localizer. Leave
detail-stage settings in `.env` unless you intentionally want to override the
Qwen API image-recognition model.

Current intended split:

```text
event localizer:
  backend=qwen_video
  model=qwen3-vl-32b-fp8
  base_url=http://127.0.0.1:8000/v1
  input=original video file URL

detail recognizer:
  model=qwen3-vl-32b-instruct
  base_url=QW_SERVICE_API_BASE_URL from .env
  input=ordered extracted image frames

service agent:
  model=SERVICE_MODEL_NAME from .env
  input=task dialogue, tool schema, and compact visual observation JSON
```

The detail stage samples at `--detail_sample_fps 2`, which is one frame every
0.5 seconds inside the localized range. It also adds one context frame before
and after the range using `--detail_boundary_offset 0.25`, then caps the
sequence at `--sequence_frames 8`. These second-stage frames are extracted from
the original video at original size and saved as PNG files; the current
`qwen_video` path does not resize them before sending them to the detail model.

The service agent prompt treats observer names as noisy visual anchors. Before
using a visual name for price, country/origin, category, tax, discount,
nutrition, or cart actions, the agent must reconcile it with tool-returned
catalog entries. Generic substring matches that drop distinctive visual tokens
must be treated as inconclusive.

Example:

```text
Visual anchor: KIM CRAFTED Sauvignon Blanc
Bad tool normalization: sauvignon blanc
Preferred normalization: a specific catalog item such as Kim Crawford Sauvignon Blanc,
when returned by tool probing and consistent with the distinctive visual tokens.
```

## 4. Visual Anchor Diagnosis

This step evaluates only whether the observer extracted the hidden visual anchor
from the scenario JSON `value` fields. It is not the official interaction score.

Run one task:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

conda run -n egolink python experiments/visual_observer_runner/evaluate_visual_anchor.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 1 \
  --observer_url http://127.0.0.1:18082/observe \
  --prompt_mode instruction \
  --refresh \
  --run_timestamp qwen_sequence_smoke
```

Run full `retail1` as a visual sanity check:

```bash
conda run -n egolink python experiments/visual_observer_runner/evaluate_visual_anchor.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --observer_url http://127.0.0.1:18082/observe \
  --prompt_mode instruction \
  --refresh \
  --run_timestamp retail1_full_qwen_sequence
```

Output:

```text
experiments/visual_observer_runner/cache/visual_anchor_eval/retail1_instruction_retail1_full_qwen_sequence.json
```

## 5. Scenario Value Oracle Control

Use this control experiment when you want to skip video understanding entirely.
The runner reads each task's `key` and `value` fields from
`scenarios/final/<scenario><number>.json` and injects them as oracle visual
anchors for the service agent.

This mode does not call the observer server, does not inspect the video, and
does not use observer cache files. It tests whether the service agent can solve
the task through tool calls once the visual anchor label is already correct.

Only the scenario `key/value` visual labels are injected. Ground-truth tool
calls, prices, country/origin, discounts, nutrition, cart state, and final
answers are not injected and must still come from tools.

Run full `retail1` with oracle visual anchors:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --visual_context_source scenario_value \
  --observe_once \
  --output_model_name scenario-value-retail1-formal
```

Result file:

```text
results/scenario-value-retail1-formal/retail1_easy.json
```

Evaluate the oracle control:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name scenario-value-retail1-formal \
  --num_samples 0
```

Expected compact visual block shape inside the service prompt:

```json
{
  "observer": "scenario_value_oracle",
  "current_visual_request": "the current user turn",
  "visual_key_values": [
    {
      "key": "product_name",
      "value": "Kim Crawford Sauvignon Blanc",
      "confidence": "oracle",
      "evidence": "Provided from scenarios/final key/value labels for a control experiment.",
      "source": "scenario_key_value"
    }
  ],
  "visual_referents": [],
  "detail_evidence": [],
  "uncertainties": null
}
```

Interpretation:

```text
scenario_value score high, real observer score low:
  bottleneck is mainly video localization or visual recognition.

scenario_value score low:
  bottleneck is mainly service-agent prompting, tool selection, database
  grounding, conditional reasoning, cart state handling, or the benchmark label.
```

## 6. Switch Service Agent To MiniMax

The observer model and service-agent model are configured independently. If you
want the service agent to use MiniMax from `.env`, override the active
`SERVICE_*` variables when starting `run_interaction.py`.

Do not only pass `--service_model_name MiniMax-M2.7-highspeed`. The API key and
base URL must be switched at the same time; otherwise the runner may keep using
the default DeepSeek or generic endpoint settings.

Also note that `run_interaction.py` uses two LLM roles:

```text
service agent:
  answers the user's requests and calls tools.
  controlled by SERVICE_MODEL_NAME, SERVICE_API_KEY, SERVICE_API_BASE_URL.

simulated user:
  generates user turns, optional user-consistency checks, corrections, and
  optional summaries.
  controlled by USER_MODEL_NAME, API_KEY, LLM_API_BASE_URL.
```

Switching only `SERVICE_*` moves only the service agent to MiniMax. DeepSeek
usage can still increase because the simulated user side still uses
`USER_MODEL_NAME`, `API_KEY`, and `LLM_API_BASE_URL` from `.env`.

Current `.env` MiniMax variables expected by the commands below:

```text
MINIMAX_SERVICE_MODEL_NAME=MiniMax-M2.7-highspeed
MINIMAX_SERVICE_API_KEY=<redacted>
MINIMAX_SERVICE_API_BASE_URL=https://api.minimaxi.com/v1
```

Run the `scenario_value` oracle control with MiniMax as the service agent:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

source .env

SERVICE_MODEL_NAME="$MINIMAX_SERVICE_MODEL_NAME" \
SERVICE_API_KEY="$MINIMAX_SERVICE_API_KEY" \
SERVICE_API_BASE_URL="$MINIMAX_SERVICE_API_BASE_URL" \
conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --visual_context_source scenario_value \
  --observe_once \
  --output_model_name scenario-value-minimax-retail1-formal
```

Evaluate it:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name scenario-value-minimax-retail1-formal \
  --num_samples 0
```

Run the real observer pipeline with MiniMax as the service agent:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

source .env

SERVICE_MODEL_NAME="$MINIMAX_SERVICE_MODEL_NAME" \
SERVICE_API_KEY="$MINIMAX_SERVICE_API_KEY" \
SERVICE_API_BASE_URL="$MINIMAX_SERVICE_API_BASE_URL" \
conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --visual_context_source observer \
  --visual_observer_url http://127.0.0.1:18082/observe \
  --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
  --observe_once \
  --refresh_observation \
  --output_model_name visual-observer-minimax-retail1-formal
```

Evaluate it:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name visual-observer-minimax-retail1-formal \
  --num_samples 0
```

When `SERVICE_MODEL_NAME` starts with `MiniMax-`, the service-agent config adds
`extra_body={"reasoning_split": true}` for the MiniMax-compatible endpoint.

Service-agent thinking is enabled by default in
`config/service_agent_config.py`:

```text
SERVICE_ENABLE_THINKING=true
SERVICE_REASONING_EFFORT=high
```

Provider-specific behavior:

```text
GPT service models whose names start with gpt-5:
  use OpenAI Responses API
  reasoning={"effort": "high", "summary": "auto"}

DeepSeek service models:
  use Chat Completions API
  reasoning_effort="high"
  extra_body={"thinking": {"type": "enabled"}}

MiniMax service models:
  use Chat Completions API
  extra_body={"reasoning_split": true}
```

To run the whole interaction with MiniMax and avoid DeepSeek calls from both
the simulated user and service agent, override both groups of variables:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

source .env

USER_MODEL_NAME="$MINIMAX_USER_MODEL_NAME" \
API_KEY="$MINIMAX_API_KEY" \
LLM_API_BASE_URL="$MINIMAX_LLM_API_BASE_URL" \
SERVICE_MODEL_NAME="$MINIMAX_SERVICE_MODEL_NAME" \
SERVICE_API_KEY="$MINIMAX_SERVICE_API_KEY" \
SERVICE_API_BASE_URL="$MINIMAX_SERVICE_API_BASE_URL" \
conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --visual_context_source scenario_value \
  --observe_once \
  --output_model_name scenario-value-all-minimax-retail1-formal
```

Use the same full override for the real observer pipeline:

```bash
source .env

USER_MODEL_NAME="$MINIMAX_USER_MODEL_NAME" \
API_KEY="$MINIMAX_API_KEY" \
LLM_API_BASE_URL="$MINIMAX_LLM_API_BASE_URL" \
SERVICE_MODEL_NAME="$MINIMAX_SERVICE_MODEL_NAME" \
SERVICE_API_KEY="$MINIMAX_SERVICE_API_KEY" \
SERVICE_API_BASE_URL="$MINIMAX_SERVICE_API_BASE_URL" \
conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --visual_context_source observer \
  --visual_observer_url http://127.0.0.1:18082/observe \
  --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
  --observe_once \
  --refresh_observation \
  --output_model_name visual-observer-all-minimax-retail1-formal
```

Verify the active runtime config before a long run:

```bash
source .env

USER_MODEL_NAME="$MINIMAX_USER_MODEL_NAME" \
API_KEY="$MINIMAX_API_KEY" \
LLM_API_BASE_URL="$MINIMAX_LLM_API_BASE_URL" \
SERVICE_MODEL_NAME="$MINIMAX_SERVICE_MODEL_NAME" \
SERVICE_API_KEY="$MINIMAX_SERVICE_API_KEY" \
SERVICE_API_BASE_URL="$MINIMAX_SERVICE_API_BASE_URL" \
conda run -n egolink python - <<'PY'
from config.user_agent_config import USER_MODEL_NAME, USER_API_BASE_URL
from config.service_agent_config import SERVICE_MODEL_NAME, SERVICE_API_BASE_URL

print("USER_MODEL_NAME =", USER_MODEL_NAME)
print("USER_API_BASE_URL =", USER_API_BASE_URL)
print("SERVICE_MODEL_NAME =", SERVICE_MODEL_NAME)
print("SERVICE_API_BASE_URL =", SERVICE_API_BASE_URL)
PY
```

Both user and service model/base URL should point to MiniMax before you start a
full run.

## 7. Formal Single-Scenario Run

Run the full interactive pipeline for `retail1`:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --visual_context_source observer \
  --visual_observer_url http://127.0.0.1:18082/observe \
  --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
  --observe_once \
  --refresh_observation \
  --output_model_name visual-observer-qwen32b-retail1-formal
```

Result file:

```text
results/visual-observer-qwen32b-retail1-formal/retail1_easy.json
```

Evaluate this single-scenario run:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name visual-observer-qwen32b-retail1-formal \
  --num_samples 0
```

Evaluation output:

```text
eval_result/visual-observer-qwen32b-retail1-formal/
```

## 8. Formal Full Run

Run all final scenario files:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

MODEL_NAME="visual-observer-qwen32b-formal-$(date +%Y%m%d%H%M)"

for item in \
  "retail 1" "retail 2" "retail 3" "retail 4" "retail 5" "retail 7" "retail 8" "retail 9" \
  "restaurant 1" "restaurant 2" "restaurant 3" "restaurant 4" \
  "kitchen 1" "kitchen 2" "kitchen 3" \
  "order 1"
do
  set -- $item
  SCENARIO=$1
  NUM=$2

  conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
    --scenario "$SCENARIO" \
    --scenario_number "$NUM" \
    --num_tasks 0 \
    --visual_context_source observer \
    --visual_observer_url http://127.0.0.1:18082/observe \
    --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
    --observe_once \
    --refresh_observation \
    --output_model_name "$MODEL_NAME"
done

echo "$MODEL_NAME"
```

Evaluate all generated result files:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name "$MODEL_NAME" \
  --num_samples 0
```

Summary output:

```text
eval_result/<MODEL_NAME>/summary.json
```

## 9. Task Subsets

For a quick formal smoke test, set `--num_tasks 1` or `--num_tasks 10`:

```bash
conda run -n egolink python experiments/visual_observer_runner/run_interaction.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 10 \
  --visual_context_source observer \
  --visual_observer_url http://127.0.0.1:18082/observe \
  --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
  --observe_once \
  --refresh_observation \
  --output_model_name visual-observer-qwen32b-retail1-10
```

Use `--refresh_observation` for clean formal runs. Omit it only when you want to
reuse cached observer outputs for debugging.

For the oracle control subset, replace the observer arguments with:

```bash
  --visual_context_source scenario_value \
```

## 10. Trace Layout

New observer traces are written under:

```text
experiments/visual_observer_runner/cache/visual_observer/runs/<run_timestamp>/<experiment_id>/
```

Important fields:

```text
request.current_user_message
request.image_description
stages.labeled_video.skipped
stages.event_localizer.backend
stages.event_localizer.qwen_base_url
stages.event_localizer.qwen_model
stages.event_localizer.clean_plan.current_visual_request
stages.event_localizer.clean_plan.referents[].event_time_range
stages.event_localizer.clean_plan.referents[].downstream_instruction
stages.vision_details[].qwen_base_url
stages.vision_details[].qwen_model
stages.vision_details[].timestamps
stages.vision_details[].frame_paths
stages.vision_details[].clean_detail.visual_key_values
observation.visual_key_values
observation.visual_referents
observation.detail_evidence
```

`stages.event_localizer` is the stage-1 video localization output. With the
current `qwen_video` backend, `stages.labeled_video` is intentionally skipped
because the model receives the original video directly.

`stages.vision_details` is the stage-2 image-sequence recognition output. Its
`clean_detail.visual_key_values` field is where the Qwen API detail model's
recognized item name or other visual anchor appears.

`observation` is the compact JSON sent back to `run_interaction.py`. The service
agent receives this compact observation as text in its prompt.

Extracted frames are saved as:

```text
<scenario>-<task>-t<timestamp>-r<referent_index>-k<frame_index>.png
```

Formal interaction logs are written under:

```text
results/<MODEL_NAME>/<scenario><number>_easy.json
```

Official evaluation logs are written under:

```text
eval_result/<MODEL_NAME>/
```

## 11. Debug Commands

Inspect running processes for the current observer:

```bash
pgrep -af 'visual_observer_runner/observer_server.py'
tmux ls
```

Inspect observer logs:

```bash
tmux capture-pane -t visual_observer -p -S -120
```

Inspect the active observer service:

```bash
curl -sS http://127.0.0.1:18082/health | jq
```

Inspect the current event localization plan from a manual trace:

```bash
jq '.tasks[].observations[-1].stages.event_localizer.clean_plan' \
  experiments/visual_observer_runner/cache/visual_observer/runs/manual-qwen-video-separate-wine-names/manual-qwen-video-separate-wine-names/traces/retail1.json
```

Inspect the detail model outputs:

```bash
jq '.tasks[].observations[-1].stages.vision_details[]
  | {
      user_referent,
      qwen_model,
      timestamps,
      visual_key_values: .clean_detail.visual_key_values,
      uncertainty: .clean_detail.uncertainty
    }' \
  experiments/visual_observer_runner/cache/visual_observer/runs/manual-qwen-video-separate-wine-names/manual-qwen-video-separate-wine-names/traces/retail1.json
```
