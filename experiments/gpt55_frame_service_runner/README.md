# GPT-5.5 Frame Service Runner

This experiment keeps the official EgoBench user simulation flow but replaces
the service agent with a GPT-5.5 Responses API client that receives sampled
image frames instead of a video input.

The official runner and the visual-observer runner are not modified.

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

Prefer the environment python path above for long tmux runs. `conda run -n
egolink python -u ...` also works, but `conda run` can buffer output in some
terminal/tmux setups, which makes progress logs look delayed.

## Run in Tmux With Logs

Use this form when an experiment may run for a long time and you want both
realtime terminal output and a saved log file:

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
     --frame_fps 2 \
     --frame_max_side 1920 \
     --frame_rotation none \
     --image_detail high \
     --frame_attach_policy auto \
     2>&1 | tee experiments/gpt55_frame_service_runner/cache/run_logs/example-kitchen2-run.log'
```

Attach to the live run:

```bash
tmux attach -t example-kitchen2-run
```

Follow the saved log without attaching:

```bash
tail -f experiments/gpt55_frame_service_runner/cache/run_logs/example-kitchen2-run.log
```

The runner itself prints to stdout only. Log files under
`cache/run_logs/` are created only when the command uses `tee` as shown above.

Frames are sampled uniformly at 2 fps by default. The default attachment policy
is `auto`: when the latest user message contains a visual reference, the service
agent receives frames on the first call for that turn. For non-visual messages,
the service starts text-only; if it needs new visual grounding, it must output
exactly `NEED_VISUAL_CONTEXT`, and the runner retries the same turn with frames
attached. The sentinel is internal and is not written as a user-visible agent
reply.

Frame attachment policies:

- `each_turn`: preserve the original behavior and attach frames once per user
  turn.
- `first_turn`: attach frames only on the first user turn.
- `auto`: attach frames immediately for visually phrased user messages; otherwise
  start text-only and attach frames only after `NEED_VISUAL_CONTEXT`.
- `never`: never attach frames.

The legacy `--frames_each_turn` flag maps to `--frame_attach_policy each_turn`.
`--no-frames_each_turn` maps to `--frame_attach_policy never`. Prefer the
explicit `--frame_attach_policy ...` form for new experiments.

When frames are attached, the service agent should resolve the visual referent
directly from the sampled frame sequence, then call official tools using the
normal JSON array format:

```json
[{"tool_name":"...","parameters":{}}]
```

The service prompt now asks the model not to output key frame ids or visual
trace metadata in tool-call JSON, because those hints can reinforce an unstable
visual interpretation.

The default `--max_visual_context_requests 6` allows a single user turn to
resolve several independent visual referents. If the service repeatedly asks
for visual context after frames have already been attached for the same call,
the runner stops that turn.

The recommended and default `--frame_max_side 1920` preserves small visual text
and menu details. With 18 seconds of video at 2 fps, 1920px frames can produce a
large request body because JPEG frames are embedded as base64 data URLs. The
runner logs each Responses API request size by default. Lower this to 1536px,
1024px, or 768px only when the backend rejects large payloads.

Use `--frame_rotation counterclockwise` for restaurant menu videos that appear
sideways and should be sent to the model in normal reading orientation. The
default is `none`, and rotated frame caches are stored separately from original
frame caches.

The service agent and correction agent both send `temperature=0.0` by default.
Override them explicitly with `--service_temperature` or
`--correction_temperature` when a different sampling setting is intended.
The service agent sends OpenAI Responses `reasoning.effort=low` by default.
The correction agent sends `reasoning.effort=medium` by default when using the
Responses API. Override them with
`--service_reasoning_effort none|minimal|low|medium|high|xhigh` and
`--correction_reasoning_effort none|minimal|low|medium|high|xhigh`; `none`
omits the `reasoning` object and uses the backend default.

The user model uses the OpenAI-compatible Chat Completions path. For Qwen on
DashScope, thinking is controlled with provider-specific `extra_body`
parameters, not OpenAI Responses `reasoning.effort`. Omit these flags to use the
provider default, or set them explicitly:

```bash
--user_temperature 0 \
--user_enable_thinking \
--user_thinking_budget 4096 \
--user_preserve_thinking
```

Use `--no-user_enable_thinking` to explicitly disable Qwen thinking mode. These
user thinking settings apply to user response generation, user contradiction
checks/corrections, and user-side summaries.

## Recovery Controls

Large frame payloads can briefly exhaust an API backend. The runner retries
service-model calls by default:

- `--service_max_retries 8`
- `--service_retry_base_delay 30`
- `--service_retry_max_delay 180`
- `--service_retry_after_cap 300`

Retryable failures include 408 stream disconnects, 429/5xx errors, connection
errors, unexpected EOF, `auth_unavailable`, and Cloudflare 524 timeouts. If the
provider returns `retry_after`, the runner waits according to that value up to
`--service_retry_after_cap`.

Results are checkpointed after every task to:

```text
results/<output_model_name>/<scenario><scenario_number>_easy.json
```

Resume a stopped run with the same `--output_model_name`:

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
  --frame_attach_policy auto \
  --resume
```

By default, a task-level failure is checkpointed and then stops the run so the
error is visible. Add `--continue_on_task_error` to record the failed task and
continue later tasks.

The runner reads service model settings from the generic `SERVICE_MODEL_NAME`,
`SERVICE_API_KEY`, and `SERVICE_API_BASE_URL` variables, with `OPENAI_*` and
older local aliases accepted only as compatibility fallbacks. The simulated user
and user-summary calls read `USER_MODEL_NAME`, `USER_API_KEY`, and
`USER_API_BASE_URL`; if unset, they can reuse the service endpoint.

`--multi_agent_user` enables the official user-side contradiction check and
correction flow. `--summary_user` enables user-side dialogue summaries between
turns; use both for the closest match to the official multi-agent user setting.
Summary generation runs after the current service-agent reply so the summary
captures the completed user-agent turn before the next simulated user message.

The service prompt is intentionally strict:
- Tool calls must be exactly one JSON array with no prose mixed in:
  `[{"tool_name":"...","parameters":{}}]`.
- The service prompt asks the model not to include key frame ids or visual trace
  metadata in tool-call JSON.
- Visual recognition is DB-constrained: frames provide visual clues, while tools
  provide canonical item names and business facts.

## Correction Agent

Add `--enable_correction_agent` to audit each proposed service-agent tool batch
or final reply before execution. The service agent still uses the Responses API
and frame inputs. The correction agent does not receive images and does not
audit visual target correctness.

The correction prompt is scenario-aware. At startup the runner builds a
scenario-specific correction system prompt for `retail`, `restaurant`,
`kitchen`, or `order`, mirroring the service prompt's scenario-rule injection
but phrased for audit behavior.

By default, the correction agent now uses the Responses API with the same
GPT-5.5 service configuration as the service agent:

```bash
--correction_api_type responses
```

In this mode, unset correction fields reuse `--service_model_name`,
`--service_api_key`, and `--service_api_base_url`.

An OpenAI-compatible chat-completions correction backend remains available only
when explicitly requested:

```bash
--correction_api_type chat_completions
export CORRECTION_API_KEY=...
export CORRECTION_API_BASE_URL=https://api.example.com/v1
export CORRECTION_MODEL_NAME=correction-model
```

`CORRECTION_API_KEY`, `CORRECTION_API_BASE_URL`, and `CORRECTION_MODEL_NAME`
override the chat-completions defaults in that mode. Older provider-specific
aliases are accepted only as compatibility fallbacks. The correction context
includes the latest user request, summarized dialogue, recent service-agent
history, the full official scenario tool catalog, previous executed tool
results, and the currently proposed tool batch or reply. It does not access the
database directly.

By default, read-only batches using `find_*`, `get_*`, `tally_*`, or `compute_*`
are automatically approved. This preserves the service agent's ability to turn
visual observations into database evidence and run non-mutating calculations.
Batches containing state-changing tools such as `add_*`, `remove_*`, or
`clear_*` are reviewed as a whole in their original order. Final replies are
also reviewed. The correction agent audits tool names, parameter fields,
returned result fields, filters, quantities, rankings, ties, state targets, and
reply support. It explicitly does not decide whether a pointed product, dish,
region, ingredient, action, OCR text, or spatial relation was visually
recognized correctly. Use `--no-correction_auto_approve_read_only` to force
read-only batches through the correction model as well.

Canonicalization policy: when a visual/OCR lookup returns no result, the service
prompt tells the agent to retry a small number of distinctive tokens or stable
substrings before giving up. Once a tool returns a clear canonical field such as
`product_name`, `dish_name`, `category`, or `restaurant_name`, later calls and
final replies should use that DB field rather than the preliminary visual
spelling. In restaurant menu boards, a large uppercase label above a drink image
is treated as that drink's menu name; in order scenes, an unsupported or
incomplete restaurant name should be clarified with the user before dish/order
mutations.

For payment, tax, discount-adjusted price, and set-meal totals, the official
`compute_*`/total tool output is the source of truth. These DB methods apply
catalog discounts and set-meal discounts, so final replies should not hand-compute
totals from undiscounted price facts.

The default correction retry budget is `--max_correction_rounds 5`. Every
correction decision is printed in the run log, including APPROVE decisions and
their compact summaries, and is also written to the correction jsonl log. When a
proposed tool batch or final reply is rejected, the runner appends the service
agent's previous proposal plus compact correction feedback to the service
history and calls the service model again. The rejected output is not executed or
shown to the user. Rejection feedback includes the exact rejected output plus
`decision`, `error_type`, `reason`, and `replan`; correction feedback is about
tool/schema/evidence/state/calculation issues, not visual target correction.

Correction jsonl records include `audit_context` stats for model-reviewed
decisions, including context character count. The correction audit context is no
longer truncated: `--correction_max_tool_log_entries`,
`--correction_max_tool_result_chars`, and `--correction_max_audit_context_chars`
are deprecated no-ops kept for CLI compatibility. Deterministic read-only
approvals do not call the correction model, so their `audit_context` field is
empty.

Example single-task replay:

```bash
conda run --no-capture-output -n egolink python experiments/gpt55_frame_service_runner/run_frame_agent.py \
  --scenario retail \
  --scenario_number 3 \
  --task_ids 7 \
  --output_model_name example-retail3-task7 \
  --enable_correction_agent \
  --correction_on_max_rounds stop \
  --multi_agent_user \
  --summary_user
```

For multi-task, split, or repeated runs, use the same command shape with a descriptive
`--output_model_name`, explicit `--task_ids` or `--num_tasks`, and one ignored
log file per tmux session.
