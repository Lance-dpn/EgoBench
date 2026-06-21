# LangGraph Service Agent

This experiment runs an independent LangGraph-based service agent while keeping
the existing EgoBench user simulation, GPT-5.5 frame input path, DB tools, and
result JSON format. It is meant for side-by-side comparison with
`experiments/gpt55_frame_service_runner/run_frame_agent.py`.

## Install

Use the same environment as the GPT-5.5 frame runner, then add LangGraph:

```bash
pip install -U langgraph
```

The runner also uses the same `.env` keys as the frame runner:

- `SERVICE_API_KEY` or `OPENAI_API_KEY`
- `SERVICE_API_BASE_URL` or `OPENAI_BASE_URL`
- optional `LANCE_SERVICE_MODEL_NAME` / `SERVICE_MODEL_NAME`

## Run

```bash
python -u experiments/langgraph_service_agent/run_langgraph_frame_agent.py \
  --scenario retail \
  --scenario_number 6 \
  --task_ids 1 \
  --output_model_name gpt55-langgraph-retail6-smoke \
  --multi_agent_user \
  --summary_user \
  --frame_fps 2 \
  --frame_max_side 1920 \
  --image_detail high \
  --frame_attach_policy auto
```

Results are written to:

```text
results/{output_model_name}/{scenario}{scenario_number}_easy.json
```

## Design

The service-side inner loop is a compact LangGraph state machine. It keeps one
strong service-planner model node and uses graph nodes for state preparation,
validation, tool execution, and final checks:

```text
prepare_context
  -> think_and_plan
  -> validate_action          when visual retry or strict tool JSON is emitted
  -> final_check              when the planner answers the user

validate_action
  -> execute_tools            when schema/repeat/semantic checks pass
  -> think_and_plan           when the planner must repair invalid output

execute_tools
  -> prepare_context          with official tool results
  -> finalize_budget          when the per-turn tool-round budget is exhausted

final_check
  -> final_reply              when required task steps are complete
  -> think_and_plan           when shopping-list/cart/final-compute/grounding steps are missing
```

It reuses the existing Responses API client, frame sampling, JSON tool-call
extraction, duplicate mutation guard, and `run.utils.execute_tool`, but keeps a
separate LangGraph service prompt.

The LangGraph service prompt is independent from the legacy frame runner prompt:

```text
experiments/langgraph_service_agent/prompts.py
```

The prompt assumes the graph manages visual context and validation. The service
model should not request visual context directly; it should either emit strict
tool-call JSON or answer from official tool evidence.

`visual_resolve` uses the same GPT-5.5 service endpoint as the service agent. It
turns attached sampled frames into an internal visual-memory JSON note before
the tool loop starts. That note is only a hypothesis: later nodes must still use
official DB tools to canonicalize names, fields, facts, branch decisions,
calculations, and state changes.

No LangGraph stage injects or validates against raw database contents directly.
Canonical names, restaurant names, categories, prices, nutrition, cart/order
state, and final calculations must come from official tool results.

Context is organized by the compact graph:

- `prepare_context`: current user request + optional GPT-5.5 visual-memory
  hypothesis.
- `think_and_plan`: one strong planner prompt inherited from the legacy service
  agent's key strategies: current-turn focus, visual hypothesis vs official
  evidence, branch-first execution, candidate-set narrowing, no duplicate
  mutations, and official final calculations.
- `validate_action`: schema, repeat, boundary, state-change permission, and
  semantic guards.
- `execute_tools`: official DB tool execution and tool-evidence logging.
- `final_check`: ensures required current-turn actions, visual entity
  calibration, boundary evidence, and final compute steps exist before final
  reply.

The output includes `langgraph_trace` per turn so failures can be compared with
the legacy runner at the node/event level.

## Current Scope

Implemented:

- independent LangGraph service-agent backend
- GPT-5.5 multimodal frame calls
- GPT-5.5 visual-memory node before the service tool loop
- visual-context retry routing
- strict tool-call JSON validation
- duplicate state-changing tool-call guard
- internal task checklist from the scenario instruction and user message
- DB canonical product context for exact field grounding
- completion verifier for required cart/list/final-compute steps
- semantic guard for oversized read-only batches
- official DB tool execution
- same high-level result JSON fields as existing runners

Not yet implemented:

- correction-agent review as a graph node
- explicit branch-decision node
- LangGraph persistence/checkpointer

Those should be added after the baseline produces comparable result files.
