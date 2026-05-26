# Legacy AURA + QwenVL Visual Observer

This directory is now a compatibility layer. New experiment code and commands
live under `experiments/visual_observer_runner/`. The Python files in this
directory forward to the renamed implementation where possible.

This experiment path keeps one observer design:

1. AURA watches the video and localizes the user-referenced event.
2. The observer extracts an ordered short frame sequence from that event.
3. QwenVL reads the frame sequence and returns visual anchor key/value facts.
4. The service agent uses those visual anchors, then grounds all customer-facing
   facts through scenario tools.

Old MiniMax and single-keyframe observer paths were removed from the active
code. Historical cache files may still exist under `cache/`, but new runs should
use the sequence observer only.

## 1. Service Startup

Start or keep the AURA video service on `18081`.

Use the AURA virtual environment for this service. Do not use
`conda run -n egolink` for `aura_observer_server.py`; the EgoBench environment
does not necessarily contain AURA server dependencies such as `aiohttp`.

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

/mnt/sda/dpn/AURA/.venv/bin/python experiments/aura_gpt_runner/aura_observer_server.py \
  --host 127.0.0.1 \
  --port 18081 \
  --target-fps 2 \
  --max-frames 32 \
  --gpu-memory-utilization 0.75 \
  --max-model-len 32768 \
  --max-tokens 512
```

If you run services through `tmux`, a reproducible launch is:

```bash
cd /mnt/sda/dpn/egolink2026

tmux kill-session -t aura_observer 2>/dev/null || true
tmux new-session -d -s aura_observer \
  'cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench && /mnt/sda/dpn/AURA/.venv/bin/python experiments/aura_gpt_runner/aura_observer_server.py --host 127.0.0.1 --port 18081 --target-fps 2 --max-frames 32 --gpu-memory-utilization 0.75 --max-model-len 32768 --max-tokens 512'
```

Start the integrated observer on `18082`:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

source .env
conda run -n egolink python experiments/aura_gpt_runner/aura_minimax_observer.py \
  --host 127.0.0.1 \
  --port 18082 \
  --aura_observer_url http://127.0.0.1:18081/observe \
  --labeled_fps 2 \
  --sequence_frames 4 \
  --sequence_window_seconds 1.5 \
  --trace_detail compact
```

tmux launch:

```bash
cd /mnt/sda/dpn/egolink2026

tmux kill-session -t aura_qwenvl_observer 2>/dev/null || true
tmux new-session -d -s aura_qwenvl_observer \
  'cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench && source .env && conda run -n egolink python experiments/aura_gpt_runner/aura_minimax_observer.py --host 127.0.0.1 --port 18082 --aura_observer_url http://127.0.0.1:18081/observe --labeled_fps 2 --sequence_frames 4 --sequence_window_seconds 1.5 --trace_detail compact'
```

The filename `aura_minimax_observer.py` is kept for compatibility with existing
commands, but the implementation is now AURA + QwenVL only.

Health checks:

```bash
tmux ls
ss -ltnp | grep 18081
ss -ltnp | grep 18082
curl -sS http://127.0.0.1:18081/health
curl -sS http://127.0.0.1:18082/health
```

Expected integrated observer response:

```json
{
  "status": "ok",
  "observer": "aura_qwenvl_sequence",
  "qwen_model": "qwen3-vl-32b-instruct"
}
```

If `tmux new-session -d -s aura_observer ...` appears to do nothing, the
session probably started and then immediately exited because the command failed.
Run the server command once in the foreground to see the import/runtime error:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench
/mnt/sda/dpn/AURA/.venv/bin/python experiments/aura_gpt_runner/aura_observer_server.py --help
```

A common bad launch is:

```bash
conda run -n egolink python experiments/aura_gpt_runner/aura_observer_server.py --help
```

If that reports `ModuleNotFoundError: No module named 'aiohttp'`, it means the
AURA server was started with the wrong Python environment. Use
`/mnt/sda/dpn/AURA/.venv/bin/python` for the `18081` AURA server and keep
`conda run -n egolink` for the `18082` integrated observer and experiment
scripts.

## 2. Environment

QwenVL API configuration is resolved in this order:

```text
QW_OBSERVER_MODEL_NAME
QWEN_VL_API_KEY / QWEN_VL_API_BASE_URL / QWEN_VL_MODEL
QW_SERVICE_API_KEY / QW_SERVICE_API_BASE_URL / QW_SERVICE_MODEL_NAME
SERVICE_API_KEY / SERVICE_API_BASE_URL
API_KEY / LLM_API_BASE_URL
```

The project `.env` is loaded by the observer at startup.

Current expected observer model:

```bash
export QW_OBSERVER_MODEL_NAME="qwen3-vl-32b-instruct"
```

The current experiment setup uses:

```text
AURA local video model on 18081
Qwen3-VL-32B observer model through DashScope-compatible API
Service agent model from SERVICE_MODEL_NAME in .env
```

With the current `.env`, the observer model and service model are intentionally
separate:

```text
QW_OBSERVER_MODEL_NAME=qwen3-vl-32b-instruct
SERVICE_MODEL_NAME=MiniMax-M2.7-highspeed
```

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

## 3. Visual Anchor Diagnosis

This step evaluates only whether the observer extracted the hidden visual anchor
from the scenario JSON `value` fields. It is not the official interaction score.

Run one task:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

conda run -n egolink python experiments/aura_gpt_runner/evaluate_visual_anchor.py \
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
conda run -n egolink python experiments/aura_gpt_runner/evaluate_visual_anchor.py \
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
experiments/aura_gpt_runner/cache/visual_anchor_eval/retail1_instruction_retail1_full_qwen_sequence.json
```

## 4. Formal Single-Scenario Run

Run the full interactive pipeline for `retail1`:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

conda run -n egolink python experiments/aura_gpt_runner/hybrid_multi_agent.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 0 \
  --aura_observer_url http://127.0.0.1:18082/observe \
  --observe_once \
  --refresh_observation \
  --output_model_name aura-qwenvl32b-retail1-formal
```

Result file:

```text
results/aura-qwenvl32b-retail1-formal/retail1_easy.json
```

Evaluate this single-scenario run:

```bash
bash analysis_scripts/run_eval.sh \
  --model_name aura-qwenvl32b-retail1-formal \
  --num_samples 0
```

Evaluation output:

```text
eval_result/aura-qwenvl32b-retail1-formal/
```

## 5. Formal Full Run

Run all final scenario files:

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

MODEL_NAME="aura-qwenvl32b-formal-$(date +%Y%m%d%H%M)"

for item in \
  "retail 1" "retail 2" "retail 3" "retail 4" "retail 5" "retail 7" "retail 8" "retail 9" \
  "restaurant 1" "restaurant 2" "restaurant 3" "restaurant 4" \
  "kitchen 1" "kitchen 2" "kitchen 3" \
  "order 1"
do
  set -- $item
  SCENARIO=$1
  NUM=$2

  conda run -n egolink python experiments/aura_gpt_runner/hybrid_multi_agent.py \
    --scenario "$SCENARIO" \
    --scenario_number "$NUM" \
    --num_tasks 0 \
    --aura_observer_url http://127.0.0.1:18082/observe \
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

## 6. Task Subsets

For a quick formal smoke test, set `--num_tasks 1` or `--num_tasks 10`:

```bash
conda run -n egolink python experiments/aura_gpt_runner/hybrid_multi_agent.py \
  --scenario retail \
  --scenario_number 1 \
  --num_tasks 10 \
  --aura_observer_url http://127.0.0.1:18082/observe \
  --observe_once \
  --refresh_observation \
  --output_model_name aura-qwenvl32b-retail1-10
```

Use `--refresh_observation` for clean formal runs. Omit it only when you want to
reuse cached observer outputs for debugging.

## 7. Trace Layout

New observer traces are written under:

```text
experiments/aura_gpt_runner/cache/aura_qwenvl_observer/runs/<run_timestamp>/<experiment_id>/
```

Important fields:

```text
stages.labeled_video
stages.aura_event_localizer.clean_plan
stages.vision_details
observation.visual_key_values
observation.visual_referents
observation.detail_evidence
```

Extracted frames are saved as:

```text
<scenario>-<task>-t<timestamp>-r<referent_index>-k<frame_index>.jpg
```

Formal interaction logs are written under:

```text
results/<MODEL_NAME>/<scenario><number>_easy.json
```

Official evaluation logs are written under:

```text
eval_result/<MODEL_NAME>/
```

## 8. Debug Commands

Inspect running processes:

```bash
pgrep -af 'aura_observer_server|aura_minimax_observer'
tmux ls
```

Inspect observer logs:

```bash
tmux capture-pane -t aura_qwenvl_observer -p -S -120
```

Inspect the actual Qwen observer model:

```bash
curl -sS http://127.0.0.1:18082/health
```

## 9. Manual AURA Split Test

Use this when you want to inspect how AURA localizes event time ranges and
referents before looking at the final service-agent score.

This command calls the integrated observer on `18082`, which internally calls
the AURA server on `18081`, writes a trace, and then also runs QwenVL detail
reading. For AURA split debugging, inspect only
`stages.aura_event_localizer.clean_plan` in the trace.

```bash
cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench

python - <<'PY'
import json
import requests

payload = {
    "task_id": "retail1_manual_aura_split_test",
    "experiment_id": "manual-aura-split-retail1",
    "experiment_timestamp": "manual",
    "scenario": "retail",
    "video_path": "/mnt/sda/dpn/egolink2026/code/track2/EgoBench/videos/retail1.mp4",
    "image_description": "You are currently in front of a wine shelf and have pointed to three bottles of wine in succession.",
    "current_user_message": "Please locate the first and second bottles I pointed at, respectively.",
}

r = requests.post("http://127.0.0.1:18082/observe", json=payload, timeout=900)
r.raise_for_status()
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
PY
```

The heredoc end marker `PY` must start at the beginning of the line. If your
shell shows `heredoc>`, the command has not executed yet; press `Ctrl-C` and
rerun the block with the final `PY` unindented.

Trace path for the command above:

```text
experiments/aura_gpt_runner/cache/aura_qwenvl_observer/runs/manual/manual-aura-split-retail1/traces/retail1.json
```

Pretty-print the trace:

```bash
python -m json.tool \
  experiments/aura_gpt_runner/cache/aura_qwenvl_observer/runs/manual/manual-aura-split-retail1/traces/retail1.json
```

Quickly extract the AURA split:

```bash
python - <<'PY'
import json
from pathlib import Path

trace = Path("experiments/aura_gpt_runner/cache/aura_qwenvl_observer/runs/manual/manual-aura-split-retail1/traces/retail1.json")
data = json.loads(trace.read_text(encoding="utf-8"))
tasks = data.get("tasks", {})
for task_key, task in tasks.items():
    for turn_key, turn in task.get("turns", {}).items():
        clean = turn.get("stages", {}).get("aura_event_localizer", {}).get("clean_plan", {})
        print("TASK:", task_key, turn_key)
        print("REQUEST:", clean.get("current_visual_request"))
        for idx, ref in enumerate(clean.get("referents", [])):
            print(
                idx,
                ref.get("user_referent"),
                ref.get("ordinal"),
                ref.get("event_time_range"),
                ref.get("sequence_timestamps"),
                ref.get("target_region"),
            )
PY
```

For multi-referent prompts such as "first and second bottles", the expected
AURA output is one referent per requested object. If the trace contains only one
referent, AURA localized only part of the request and the event-localizer prompt
needs further tightening.
