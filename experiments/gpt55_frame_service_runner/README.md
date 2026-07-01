# GPT-5.5 Frame Service Runner

This experiment keeps the official EgoBench simulated-user flow, but replaces
the service agent with a GPT-5.5 Responses API client that receives sampled
image frames instead of a video input.

The official runner and visual-observer runner are not modified.

## What It Does

At a high level, `run_frame_agent.py`:

1. Loads an EgoBench scenario from `scenarios/final/<scenario><number>.json`.
2. Initializes the official scenario database and tool catalog.
3. Samples local task videos into JPEG frames with `ffmpeg`/`ffprobe`.
4. Runs the official simulated user through the Chat Completions path.
5. Runs the service agent through the OpenAI Responses API with optional frame
   inputs.
6. Executes official EgoBench tools when the service agent emits JSON tool calls.
7. Saves task checkpoints under `results/<output_model_name>/`.

The service agent receives frames only according to the selected frame attachment
policy. The default policy is `auto`: visually phrased user turns receive frames
immediately; otherwise the service agent can request them by outputting exactly
`NEED_VISUAL_CONTEXT`.

## Main Files

- `run_frame_agent.py`: experiment entrypoint, CLI, simulation loop, checkpointing.
- `frame_sampler.py`: video duration probing, uniform frame sampling, frame cache.
- `openai_responses_client.py`: lightweight Responses API client with retry logic.
- `tool_call_correction.py`: optional correction-agent support for auditing service
  tool calls or final replies.
- `prompts/service.py`: service-agent prompt and scenario-specific rules.

## Run Directly

```bash
source .env
python -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
  --scenario kitchen \
  --scenario_number 2 \
  --num_tasks 10 \
  --output_model_name example-kitchen2-run \
  --multi_agent_user \
  --summary_user \
  --frame_fps 2 \
  --frame_max_side 1920 \
  --frame_rotation none \
  --image_detail high \
  --frame_attach_policy auto
```

For long runs, prefer `python -u` inside a shell/tmux session so logs are flushed
in real time.

## Run With Tmux Logs

```bash
source .env
mkdir -p experiments/gpt55_frame_service_runner/cache/run_logs

RUN_NAME=example-kitchen2-run

tmux new-session -d -s "$RUN_NAME" \
  'cd <repo-root> && \
   source .env && \
   python -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
     --scenario kitchen \
     --scenario_number 2 \
     --num_tasks 10 \
     --output_model_name example-kitchen2-run \
     --multi_agent_user \
     --summary_user \
     --frame_attach_policy auto \
     2>&1 | tee experiments/gpt55_frame_service_runner/cache/run_logs/example-kitchen2-run.log'
```

Attach to the live run:

```bash
tmux attach -t example-kitchen2-run
```

Follow the saved log:

```bash
tail -f experiments/gpt55_frame_service_runner/cache/run_logs/example-kitchen2-run.log
```

The runner itself prints to stdout only. Log files are created by `tee`, not by
the runner.

## Important Options

- `--scenario retail|kitchen|restaurant|order`: scenario family.
- `--scenario_number N`: scenario file number.
- `--num_tasks N`: run the first N tasks.
- `--task_ids 1,3,5-7`: run specific 1-based task ids.
- `--output_model_name NAME`: output directory name under `results/`.
- `--resume`: skip completed task ids already present in the result JSON.
- `--continue_on_task_error`: checkpoint a failed task and continue later tasks.
- `--frame_fps`: frame sampling rate, default `2`.
- `--frame_max_side`: maximum sampled frame side, default `1920`.
- `--max_frames`: optional cap on sampled frames per video.
- `--frame_rotation none|clockwise|counterclockwise|180`: rotate sampled frames.
- `--image_detail low|auto|high`: Responses API image detail setting.
- `--frame_attach_policy each_turn|first_turn|auto|never`: controls frame
  attachment.
- `--enable_correction_agent`: audit service outputs before execution/delivery.

The legacy `--frames_each_turn` flag maps to `--frame_attach_policy each_turn`;
`--no-frames_each_turn` maps to `--frame_attach_policy never`.

## Model Configuration

Service-model settings prefer:

```text
SERVICE_MODEL_NAME
SERVICE_API_KEY
SERVICE_API_BASE_URL
```

`OPENAI_MODEL_NAME`, `OPENAI_API_KEY`, and `OPENAI_BASE_URL` are accepted as
fallbacks.

User-model settings prefer:

```text
USER_MODEL_NAME
USER_API_KEY
USER_API_BASE_URL
USER_TEMPERATURE
```

If user endpoint variables are unset, the runner can reuse the service endpoint.
Qwen/DashScope thinking options can be controlled with:

```bash
--user_enable_thinking
--user_thinking_budget 4096
--user_preserve_thinking
```

## Outputs And Resume

Results are checkpointed after each completed task to:

```text
results/<output_model_name>/<scenario><scenario_number>_easy.json
```

Frame caches are stored under:

```text
experiments/gpt55_frame_service_runner/cache/frames/
```

Correction logs, when enabled, are stored under:

```text
experiments/gpt55_frame_service_runner/cache/correction_logs/
```

Resume with the same `--output_model_name` and add `--resume`.

## Correction Agent

The correction agent is optional. When enabled, it reviews proposed service-agent
tool batches and final replies. It does not receive images and is intended to
audit tool/schema/evidence/state/calculation support, not visual recognition.

By default, correction uses the Responses API and reuses the service model
configuration when correction-specific values are unset:

```bash
--enable_correction_agent
--correction_api_type responses
```

An OpenAI-compatible chat-completions backend is also available:

```bash
--correction_api_type chat_completions
```

## Prompt Construction

The service prompt is built in `prompts/service.py` by
`build_service_agent_prompt(...)`. It combines:

- the current scenario name and number;
- the strict output protocol, including JSON-only tool calls and
  `NEED_VISUAL_CONTEXT`;
- the general service-agent workflow for visual grounding, tool use, branching,
  state changes, and final replies;
- scenario-specific rules for `retail`, `kitchen`, `restaurant`, or `order`;
- the official scenario tool catalog loaded from `tools/<scenario>/`.

The main design is that frames provide visual hypotheses, while official tools
and databases provide canonical names, facts, calculations, and state changes.

The correction prompt is built in `tool_call_correction.py` by
`build_correction_system_prompt(...)`. It is also scenario-aware, but its role is
different: it audits the service agent's proposed next output before execution
or delivery. The audit context includes the proposed tool batch or reply, recent
filtered dialogue, previous and current tool ledgers, the service prompt, and the
official tool catalog. Images are intentionally not sent to the correction
agent.

Read-only tool batches such as `find_*`, `get_*`, `list_*`, `tally_*`, and
`compute_*` are automatically approved by default. State-changing calls and
final replies can be reviewed by the correction model. When a proposal is
rejected, the runner appends compact feedback to the service-agent history and
asks the service agent to replan.

## Notes

- Tool calls must be emitted as a single JSON array, for example:

  ```json
  [{"tool_name":"...","parameters":{}}]
  ```

- The runner uses official EgoBench tools and databases for facts and state
  changes.
- Large frame payloads can be expensive or rejected by some backends. Lower
  `--frame_max_side`, `--frame_fps`, or set `--max_frames` if needed.
- `--refresh_frames` rebuilds cached frames.
