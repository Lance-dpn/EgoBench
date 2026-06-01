# Visual Observer Runner

This runner adds on-demand visual grounding to EgoBench Track 2. The service
agent sees a virtual `resolve_visual_reference` tool. When it calls that tool,
`run_interaction.py` calls the observer server, receives one visual identity
fact, and then returns that fact as a tool result to the service agent.

The current observer path is:

```text
video + user visual request
  -> event localizer: find the relevant time range and region
  -> frame extractor: sample original-size frames from that range
  -> detail recognizer: read the visible anchor from sampled frames
  -> compact result: [{"key": "...", "value": "...", "confidence": "..."}]
```

Visual results are identity clues only. Prices, discounts, nutrition, tax,
inventory, cart/order state, and final actions must still be confirmed through
scenario tools.

## 1. Working Directory

Run commands from EgoBench:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench
```

The observer startup script loads `.env` automatically.

## 2. Current Recommended Online Observer

For online DashScope/Qwen video requests, use a public video URL. The current
video base is:

```bash
export VIDEO_URL_BASE="https://egolink.yan2u.top"
export OBSERVER_VIDEO_URL_BASE="https://egolink.yan2u.top"
```

Opening the root URL in a browser can return `404`; this is expected. Check the
actual MP4 URL instead:

```bash
curl -I -L https://egolink.yan2u.top/greek_annie_1.mp4
ffprobe -v error \
  -show_entries format=format_name,duration,size:stream=codec_type,codec_name,width,height,r_frame_rate \
  -of json \
  https://egolink.yan2u.top/greek_annie_1.mp4
```

Expected for `greek_annie_1.mp4`:

```text
HTTP 200
content-type: video/mp4
codec: h264
resolution: 720x720
duration: about 16.134s
```

Recommended `.env` observer settings:

```bash
export OBSERVER_ONLINE_MODEL="qwen3.6-27b"
export OBSERVER_ONLINE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OBSERVER_ONLINE_API_KEY="<redacted>"

export OBSERVER_LOCAL_BASE_URL="http://127.0.0.1:8000/v1"
export OBSERVER_LOCAL_MODEL="qwen3.6-27b-fp8"

# Optional stage-specific overrides. Leave unset to use the provider default.
# export OBSERVER_EVENT_MODEL="qwen3.6-27b"
# export OBSERVER_DETAIL_MODEL="qwen3.6-27b-fp8"

export OBSERVER_EVENT_TEMPERATURE="0.3"
export OBSERVER_EVENT_THINKING="off"
export OBSERVER_EVENT_MAX_TOKENS="2048"
export OBSERVER_EVENT_THINKING_BUDGET="512"
export OBSERVER_EVENT_HIGH_RESOLUTION_IMAGES="off"

export OBSERVER_DETAIL_TEMPERATURE="0.0"
export OBSERVER_DETAIL_THINKING="off"
export OBSERVER_DETAIL_MAX_TOKENS="2048"
export OBSERVER_DETAIL_THINKING_BUDGET="512"
export OBSERVER_DETAIL_HIGH_RESOLUTION_IMAGES="on"
export OBSERVER_QWEN_TIMEOUT="300"

export OBSERVER_QWEN_VIDEO_FPS="2"

export VIDEO_URL_BASE="https://egolink.yan2u.top"
export OBSERVER_VIDEO_URL_BASE="https://egolink.yan2u.top"
```

Start or restart the observer:

```bash
OBSERVER_MODEL_PROVIDER=online \
  bash experiments/visual_observer_runner/start_observer.sh
```

Check health:

```bash
curl -sS http://127.0.0.1:18082/health | jq
```

Expected key fields:

```text
stages.event_localizer.backend=qwen_video
stages.event_localizer.temporal_event_backend=qwen_video
stages.event_localizer.base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
stages.event_localizer.generation.enable_thinking=false
stages.event_localizer.generation.max_tokens=2048
stages.detail_recognizer.generation.enable_thinking=false
stages.detail_recognizer.generation.max_tokens=2048
stages.detail_recognizer.generation.vl_high_resolution_images=true
stages.event_localizer.video_fps=2
```

For detail recognition, frames are extracted at original size and saved as PNG.
The detail image request uses base64 `image_url` and sends
`vl_high_resolution_images=true` when
`OBSERVER_DETAIL_HIGH_RESOLUTION_IMAGES=on`. This is the DashScope
OpenAI-compatible high-resolution image mode.

When the event localizer returns a `best_keyframes` timestamp, detail sampling
uses that timestamp only as a sampling anchor. The anchor is not treated as the
answer frame and is not allowed to override stronger evidence in other sampled
frames. The detail stage samples before and after the anchor across the event
time range plus `OBSERVER_DETAIL_BOUNDARY_OFFSET` seconds on both sides. If no
keyframe is returned, the observer falls back to uniform sampling across the
event time range.

Both event localization and detail recognition receive an augmented scene
description. It starts from the scenario task's `image_description`, then adds
scenario-specific visual guidance when needed. For `order`, the added guidance
states that the user may point to different dishes in sequence and that
ordinal requests such as first/second/third pointed dish must be resolved by
the chronological order of pointing actions in the video, not by the most
readable or salient menu item. It also states that a finger pointing at a dish
usually does not completely cover the intended dish, and that the menu item
nearest to the fingertip or pointing direction should be treated as the
intended dish when visible evidence supports it.

The outgoing event request follows the OpenAI-compatible video format used by
DashScope:

```json
{
  "model": "qwen3.6-27b",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "<event-localizer prompt>"},
        {
          "type": "video_url",
          "video_url": {"url": "https://egolink.yan2u.top/greek_annie_1.mp4"},
          "fps": 2
        }
      ]
    }
  ],
  "temperature": 0.3,
  "max_tokens": 2048,
  "extra_body": {
    "enable_thinking": false
  }
}
```

### 2.1 Event Backend Choice

The observer always exposes the event stage as `event_localizer.backend=qwen_video`
because the primary event localizer is Qwen-VL. For temporal or ordinal action
requests, the actual request backend can be switched by
`OBSERVER_TEMPORAL_EVENT_BACKEND`.

Supported values:

```text
qwen_video
  Sends one video input to the model.
  Online provider: public video URL from OBSERVER_VIDEO_URL_BASE or VIDEO_URL_BASE.
  Local provider: file:// video path under --allowed-local-media-path.

qwen_frames
  Samples frames before the event request and sends images to the model.
  Online provider: base64 image_url inputs.
  Local provider: file:// image inputs.
```

Recommended defaults:

```bash
# Online DashScope: use video by default for the temporal event stage.
OBSERVER_MODEL_PROVIDER=online \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_video \
  bash experiments/visual_observer_runner/start_observer.sh

# Local vLLM: prefer video to avoid large multi-image context/cache failures.
OBSERVER_MODEL_PROVIDER=local \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_video \
  bash experiments/visual_observer_runner/start_observer.sh
```

Use `qwen_video` as the default for both online and local runs. Switch to
`qwen_frames` only for targeted debugging when you explicitly want the event
stage to see sampled frames instead of a video input.

## 3. Thinking Mode

Event thinking can be changed without editing commands:

```bash
OBSERVER_EVENT_THINKING=off \
OBSERVER_MODEL_PROVIDER=online \
  bash experiments/visual_observer_runner/start_observer.sh
```

or:

```bash
OBSERVER_EVENT_THINKING=on \
OBSERVER_EVENT_THINKING_BUDGET=512 \
OBSERVER_MODEL_PROVIDER=online \
  bash experiments/visual_observer_runner/start_observer.sh
```

For online DashScope/Qwen requests, `start_observer.sh` sends
`extra_body.enable_thinking` and optional `extra_body.thinking_budget`. For
local vLLM requests, it uses `extra_body.chat_template_kwargs.enable_thinking`.
This distinction matters: `chat_template_kwargs` is the vLLM request-level
override, while DashScope's OpenAI-compatible API uses direct
`extra_body.enable_thinking`.

To test detail thinking without letting reasoning run unbounded:

```bash
OBSERVER_TRACE_DETAIL=full \
OBSERVER_MODEL_PROVIDER=online \
OBSERVER_EVENT_THINKING=on \
OBSERVER_DETAIL_THINKING=on \
OBSERVER_EVENT_THINKING_BUDGET=512 \
OBSERVER_DETAIL_THINKING_BUDGET=512 \
OBSERVER_QWEN_TIMEOUT=240 \
  bash experiments/visual_observer_runner/start_observer.sh
```

Current manual results on `order1` showed:

```text
event thinking off:
  first pointed dish: 24.333s, Mushroom soup
  top-left category: 33.574s, COLD CUTS
  bottom-middle category: 36.671s, ITALIAN PASTA

event thinking on:
  first pointed dish: 84.591s, Lasagne
  top-left category: 118.545s, CHEESE & OLIVES
```

Use `OBSERVER_EVENT_THINKING=off` for normal runs. Thinking mode is useful for
debugging, but it is slower and can shift spatial interpretation.

For online `qwen3-vl-*` models such as `qwen3-vl-32b-instruct`, keep event and
detail thinking off. These models can reject `thinking_budget` request
parameters with a 400 error. `start_observer.sh` automatically disables thinking
and clears thinking budgets for online `qwen3-vl-*` models.

## 4. Manual Observer Smoke Test

Use the same shape that `run_interaction.py` sends after the service agent calls
`resolve_visual_reference`.

First pointed dish:

```bash
curl -sS --max-time 240 \
  -X POST http://127.0.0.1:18082/observe \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "manual_order1_1_turn2",
    "request_key": "manual_first_pointed_dish",
    "scenario": "order",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/greek_annie_1.mp4",
    "image_description": "You and your friend are in a order. You look at the menu and point to three dishes in succession.",
    "current_user_message": "Identify the first dish the user is pointing at in the current sequence on Menu 2 from Annie Italian Restaurant.\nVisual referent to resolve: first pointed dish"
  }' | jq '{elapsed_seconds, trace_path, observation}'
```

Top-left menu category:

```bash
curl -sS --max-time 240 \
  -X POST http://127.0.0.1:18082/observe \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "manual_order1_1_turn2",
    "request_key": "manual_top_left_card",
    "scenario": "order",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/greek_annie_1.mp4",
    "image_description": "You and your friend are in a order. You look at the menu and point to three dishes in succession.",
    "current_user_message": "Identify the category title at the top of the far left side of Menu 2, shown as an independent small card.\nVisual referent to resolve: top far-left independent small card category"
  }' | jq '{elapsed_seconds, trace_path, observation}'
```

Bottom-middle category with hand illustration:

```bash
curl -sS --max-time 240 \
  -X POST http://127.0.0.1:18082/observe \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "manual_order1_1_turn2",
    "request_key": "manual_bottom_middle_hand",
    "scenario": "order",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/greek_annie_1.mp4",
    "image_description": "You and your friend are in a order. You look at the menu and point to three dishes in succession.",
    "current_user_message": "Identify the category title at the very bottom of the middle fold of Menu 2, with a small hand illustration on the left side of the title.\nVisual referent to resolve: bottom middle-fold category with hand illustration"
  }' | jq '{elapsed_seconds, trace_path, observation}'
```

Trace files are written under:

```text
experiments/visual_observer_runner/cache/visual_observer/runs/<timestamp>/<experiment_id>/traces/<scenario>.json
```

For standalone manual calls, the experiment id starts with `standalone-...`.

By default, traces are compact and omit full prompts, raw responses, and parsed
raw text. To keep the detailed event/detail prompts and model responses, restart
the observer with:

```bash
OBSERVER_TRACE_DETAIL=full \
OBSERVER_MODEL_PROVIDER=online \
  bash experiments/visual_observer_runner/start_observer.sh
```

Use this only for debugging. Full traces can be much larger and may include the
complete model request/response content.

## 5. Run Interaction

Start the observer first, then run:

```bash
source .env
conda run --no-capture-output -n egolink \
  python -u experiments/visual_observer_runner/run_interaction.py \
    --scenario order \
    --scenario_number 1 \
    --num_tasks 1 \
    --visual_context_source observer \
    --visual_observer_url http://127.0.0.1:18082/observe \
    --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
    --observe_once \
    --refresh_observation \
    --output_model_name qwen36-online-url-observer-order1-smoke
```

Results are written to:

```text
results/<output_model_name>/
experiments/visual_observer_runner/cache/visual_observations/
experiments/visual_observer_runner/cache/visual_observer/runs/
```

To run specific 1-based tasks instead of the first `--num_tasks` tasks, use
`--task_ids`:

```bash
source .env
conda run --no-capture-output -n egolink \
  python -u experiments/visual_observer_runner/run_interaction.py \
    --scenario order \
    --scenario_number 1 \
    --task_ids 3 \
    --visual_context_source observer \
    --visual_observer_url http://127.0.0.1:18082/observe \
    --observation_cache_dir experiments/visual_observer_runner/cache/visual_observations \
    --observe_once \
    --refresh_observation \
    --output_model_name order1-task3-debug
```

`--task_ids` also accepts comma-separated ids and ranges, for example
`--task_ids 3,7,10-12`. Keep `--refresh_observation` when you want to rerun the
observer and ignore stale cached visual results; remove it when intentionally
reusing an existing observation cache.

Evaluate a finished run:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name qwen36-online-url-observer-order1-smoke \
  --num_samples 0
```

## 6. Scenario Value Mode

Use `scenario_value` mode to bypass video understanding and return the scenario
JSON `key/value` as an oracle visual identity:

```bash
source .env
conda run --no-capture-output -n egolink \
  python -u experiments/visual_observer_runner/run_interaction.py \
    --scenario order \
    --scenario_number 1 \
    --num_tasks 1 \
    --visual_context_source scenario_value \
    --observe_once \
    --output_model_name scenario-value-order1-smoke
```

This mode is useful for testing service-agent tool behavior independently of
visual recognition quality.

## 7. Local Qwen3.6 And Mixed Observer

### 7.1 Start Local Qwen3.6

Start the local OpenAI-compatible vLLM server in tmux:

```bash
cd /mnt/sda/dpn/egolink2026

tmux kill-session -t qwen36 2>/dev/null || true
tmux new-session -d -s qwen36 \
  'cd /mnt/sda/dpn/egolink2026/model && exec env CUDA_VISIBLE_DEVICES=1,2 VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_LOGGING_LEVEL=INFO ./vllm-venv/bin/vllm serve /mnt/sda/dpn/egolink2026/model/Qwen3.6-27B-FP8 --served-model-name qwen3.6-27b-fp8 --host 0.0.0.0 --port 8000 --tensor-parallel-size 2 --max-model-len 32768 --gpu-memory-utilization 0.88 --trust-remote-code --reasoning-parser qwen3 --max-num-seqs 8 --allowed-local-media-path /mnt/sda/dpn/egolink2026'
```

The important flags are:

```text
--served-model-name qwen3.6-27b-fp8
--reasoning-parser qwen3
--allowed-local-media-path /mnt/sda/dpn/egolink2026
```

`--reasoning-parser qwen3` lets vLLM separate thinking text from
`message.content` when the observer requests reasoning support. The observer
normally sends `include_reasoning=false`, so JSON parsing sees only the final
answer content.

If startup hangs with shared-memory or custom-all-reduce errors, use the stable
fallback:

```bash
cd /mnt/sda/dpn/egolink2026

tmux kill-session -t qwen36 2>/dev/null || true
tmux new-session -d -s qwen36 \
  'cd /mnt/sda/dpn/egolink2026/model && exec env CUDA_VISIBLE_DEVICES=1,2 VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_LOGGING_LEVEL=INFO ./vllm-venv/bin/vllm serve /mnt/sda/dpn/egolink2026/model/Qwen3.6-27B-FP8 --served-model-name qwen3.6-27b-fp8 --host 0.0.0.0 --port 8000 --tensor-parallel-size 2 --max-model-len 32768 --gpu-memory-utilization 0.88 --trust-remote-code --reasoning-parser qwen3 --enforce-eager --disable-custom-all-reduce --max-num-seqs 8 --allowed-local-media-path /mnt/sda/dpn/egolink2026'
```

Verify readiness:

```bash
curl -sS http://127.0.0.1:8000/v1/models | jq
```

Expected model id:

```text
qwen3.6-27b-fp8
```

### 7.2 Use Local Qwen3.6 For Observer

`start_observer.sh` can switch event/detail providers independently. These env
variables are read by the script:

```bash
export OBSERVER_LOCAL_BASE_URL="http://127.0.0.1:8000/v1"
export OBSERVER_LOCAL_MODEL="qwen3.6-27b-fp8"

export OBSERVER_EVENT_THINKING="off"
export OBSERVER_EVENT_MAX_TOKENS="2048"
export OBSERVER_EVENT_TEMPERATURE="0.3"
export OBSERVER_EVENT_HIGH_RESOLUTION_IMAGES="off"

export OBSERVER_DETAIL_THINKING="off"
export OBSERVER_DETAIL_MAX_TOKENS="2048"
export OBSERVER_DETAIL_TEMPERATURE="0.0"
export OBSERVER_DETAIL_HIGH_RESOLUTION_IMAGES="on"
```

Use local Qwen3.6 for both event and detail:

```bash
OBSERVER_MODEL_PROVIDER=local \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_video \
OBSERVER_LOCAL_BASE_URL=http://127.0.0.1:8000/v1 \
OBSERVER_LOCAL_MODEL=qwen3.6-27b-fp8 \
  bash experiments/visual_observer_runner/start_observer.sh
```

For local all-Qwen3.6 runs, the current recommended smoke-test command is:

```bash
OBSERVER_MODEL_PROVIDER=local \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_video \
OBSERVER_EVENT_THINKING=off \
OBSERVER_DETAIL_THINKING=off \
OBSERVER_EVENT_MAX_TOKENS=2048 \
OBSERVER_DETAIL_MAX_TOKENS=2048 \
OBSERVER_TRACE_DETAIL=full \
  bash experiments/visual_observer_runner/start_observer.sh
```

`qwen_video` is recommended locally because the current vLLM service has a
32k context window and local multi-image event requests can exceed the context
budget or hit vLLM multimodal cache errors. If you intentionally test
`qwen_frames` locally, start with a small request:

```bash
OBSERVER_MODEL_PROVIDER=local \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_frames \
OBSERVER_EVENT_FRAME_FPS=1 \
OBSERVER_EVENT_MAX_FRAMES=8 \
OBSERVER_FRAME_MAX_SIDE=768 \
  bash experiments/visual_observer_runner/start_observer.sh
```

Use local event and online detail:

```bash
OBSERVER_EVENT_PROVIDER=local \
OBSERVER_DETAIL_PROVIDER=online \
OBSERVER_LOCAL_BASE_URL=http://127.0.0.1:8000/v1 \
OBSERVER_LOCAL_MODEL=qwen3.6-27b-fp8 \
  bash experiments/visual_observer_runner/start_observer.sh
```

Use online event and local detail:

```bash
OBSERVER_EVENT_PROVIDER=online \
OBSERVER_DETAIL_PROVIDER=local \
OBSERVER_LOCAL_BASE_URL=http://127.0.0.1:8000/v1 \
OBSERVER_LOCAL_MODEL=qwen3.6-27b-fp8 \
  bash experiments/visual_observer_runner/start_observer.sh
```

Override event/detail models separately when needed:

```bash
OBSERVER_EVENT_PROVIDER=online \
OBSERVER_DETAIL_PROVIDER=local \
OBSERVER_EVENT_MODEL=qwen3.6-27b \
OBSERVER_DETAIL_MODEL=qwen3.6-27b-fp8 \
  bash experiments/visual_observer_runner/start_observer.sh
```

Check observer routing and thinking settings:

```bash
curl -sS http://127.0.0.1:18082/health | jq '.stages'
```

The local model value must match the model id returned by `/v1/models`.

## 8. Troubleshooting Similar Observer Failures

### 8.1 Confirm The Running Configuration

Always check the live server state after restart:

```bash
curl -sS http://127.0.0.1:18082/health | jq
```

`start_observer.sh` also prints the actual health response after startup. If the
printed startup line and `/health` disagree, an old process is still occupying
the port or the restart did not reach the intended server.

Check port ownership and process state:

```bash
ss -ltnp | grep ':18082'
ps -ef | grep -E 'observer_server.py|18082' | grep -v grep
tmux capture-pane -t visual_observer -p | tail -120
```

For local Qwen3.6, also verify vLLM:

```bash
curl -sS http://127.0.0.1:8000/v1/models | jq
ss -ltnp | grep ':8000'
tmux capture-pane -t qwen36 -p | tail -160
```

### 8.2 Find The Relevant Trace

Observer traces are the main source of truth:

```bash
find experiments/visual_observer_runner/cache/visual_observer/runs \
  -type f -name '*.json' -printf '%T@ %p\n' | sort -nr | head
```

Use full traces when debugging request construction or model output:

```bash
OBSERVER_TRACE_DETAIL=full \
  bash experiments/visual_observer_runner/start_observer.sh
```

Full traces include event/detail prompts, request metadata, raw model text, and
parsed JSON. Compact traces are better for routine experiment runs.

### 8.3 Context Too Large In Local vLLM

A local event request can fail with:

```text
max_tokens must be at least 1, got -...
```

This means the prompt plus visual tokens exceeded the local model context. The
current local Qwen3.6 vLLM service is commonly started with
`--max-model-len 32768`; sending many high-resolution frames can consume that
budget before generation starts.

Fixes:

```bash
# Prefer this for local temporal/ordinal smoke tests.
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_video

# Or reduce the frame request if local qwen_frames is required.
OBSERVER_EVENT_FRAME_FPS=1
OBSERVER_EVENT_MAX_FRAMES=8
OBSERVER_FRAME_MAX_SIDE=768
OBSERVER_EVENT_MAX_TOKENS=1024
```

### 8.4 Local Multi-Image vLLM Cache Error

If the observer returns an internal server error and the `qwen36` tmux log shows:

```text
AssertionError: Expected a cached item for mm_hash=...
```

the failure is inside the local vLLM multimodal cache path for multi-image
requests. This is not a service-agent or observer JSON parsing issue. Use:

```bash
OBSERVER_MODEL_PROVIDER=local \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_video \
  bash experiments/visual_observer_runner/start_observer.sh
```

Restarting vLLM may clear a transient cache state, but the reliable workaround
is to avoid local `qwen_frames` for that run.

### 8.5 Event Is Valid But Selects The Wrong Moment

If the event stage returns a plausible JSON object but points to the wrong
moment, inspect:

```text
effective_event_localizer_backend
event_localizer.raw_text
event_localizer.clean_plan.candidate_events
event_localizer.clean_plan.referents
detail_recognizer.sequence_timestamps
detail_recognizer.raw_text
```

For ordinal pointing tasks, the event prompt asks the model to enumerate
candidate action events first, then select one by ordinal order. The detail
stage receives one visual target only and should use the full sampled sequence
around the event range. The keyframe is only a sampling anchor, not the answer.

If the selected moment is consistently late or outside the intended screen
region, you can run a targeted online `qwen_frames` comparison:

```bash
OBSERVER_MODEL_PROVIDER=online \
OBSERVER_TEMPORAL_EVENT_BACKEND=qwen_frames \
OBSERVER_EVENT_FRAME_FPS=2 \
OBSERVER_EVENT_MAX_FRAMES=32 \
  bash experiments/visual_observer_runner/start_observer.sh
```

## 9. Multiple Visual Requests And Cache

One task may need several different visual resolutions. Each call should ask for
one target only, for example:

```text
first pointed dish
top far-left independent small card category
bottom middle-fold category with hand illustration
```

`--observe_once` caches only identical visual requests within a task. Different
turns, queries, or `referent_hint` values still call the observer separately.

The cache key is:

```text
turn + query + referent_hint
```

Trace keys include the request key, for example:

```text
turn2_thinking_off_round2_top_left_card
```

Extracted keyframe filenames also include the request key in new runs, for
example:

```text
order-order1_1_turn3-0528a2984b8395fb-t0.90-r00-k01.png
```

This prevents multiple observer calls in the same turn from overwriting each
other.

## 10. Service-Agent Rules

The service agent prompt enforces these rules:

```text
1. Call resolve_visual_reference only for visual identity grounding.
2. Treat observer output as a visual clue, not a database key.
3. Confirm observer-returned names/categories through scenario tools before
   using them for concrete operations.
4. If tool results do not provide enough evidence to answer the user, call the
   observer for the missing visual identity.
5. Keep using scenario tools for prices, discounts, nutrition, tax, totals, and
   order/cart actions.
```

Successful visual identities are stored in compact visual memory so later turns
can resolve pronouns such as `it`, `this one`, or `the same category`.
