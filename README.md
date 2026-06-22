# Lance-dpn EgoBench Track 2

This repository is the Lance-dpn working branch for EgoLink 2026 Track 2 / EgoBench final evaluation. It keeps the official EgoBench sandbox, tools, scenarios, and evaluator, and adds our frame-based GPT-5.5 service runner, correction agent, rerun scripts, and clean final result staging files.

Raw run logs, local evaluation outputs, GT audit notes, temporary zip files, and manual process reports are intentionally kept out of Git. They may exist on the Lance-dpn workstation for debugging, but they are not part of the GitHub development branch.

The current branch is organized for the final five scenarios:

| Scenario | File | Tasks |
|---|---|---:|
| Retail 6 | `retail6_easy.json` | 49 |
| Retail 10 | `retail10_easy.json` | 63 |
| Kitchen 4 | `kitchen4_easy.json` | 50 |
| Restaurant 5 | `restaurant5_easy.json` | 50 |
| Order 2 | `order2_easy.json` | 97 |

The staged submission files are kept under `submission/Lance-dpn_track2/`.
Local GT-based checks are used only for debugging and are not official
benchmark results.

## Repository Layout

Core files:

- `experiments/gpt55_frame_service_runner/run_frame_agent.py`  
  Our frame-based service runner. It keeps the official simulated user flow and sends sampled video frames to the service model.

- `experiments/gpt55_frame_service_runner/prompts/service.py`  
  Main service-agent prompt and scenario-specific rules.

- `experiments/gpt55_frame_service_runner/tool_call_correction.py`  
  Correction agent used to audit tool batches and replies before execution.

- `experiments/gpt55_frame_service_runner/frame_sampler.py`  
  Video frame sampling and resizing.

- `experiments/langgraph_service_agent/evaluate_task_id_aligned.py`  
  Task-id aligned evaluator used for local GT checks.

- `scenarios/final/`  
  Final scenario JSON files. In official evaluation, the service agent must not read these files directly.

- `tools/`  
  Official scenario tools and DB initializers, including the updated `kitchen4` DB.

Important result location:

- `submission/Lance-dpn_track2/results/Lance-dpn/`  
  Clean submission staging directory containing the five required result JSON files.

Local result zips and evaluator outputs should be generated when needed and are ignored by Git.

## Environment

Use the existing project environment:

```bash
source .env
python --version
```

The frame runner reads generic OpenAI-compatible environment variables:

```bash
SERVICE_MODEL_NAME
SERVICE_API_KEY
SERVICE_API_BASE_URL
```

The simulated user and summary/check calls use the configured user model variables, including:

```bash
USER_MODEL_NAME
USER_API_KEY
USER_API_BASE_URL
```

The correction agent uses `CORRECTION_*` when set; otherwise it reuses the service model settings.

Do not commit `.env` or any plaintext API key.

## Running A Scenario

Direct run example:

```bash
source .env
python -u experiments/gpt55_frame_service_runner/run_frame_agent.py \
  --scenario kitchen \
  --scenario_number 4 \
  --num_tasks 5 \
  --output_model_name smoke-kitchen4 \
  --multi_agent_user \
  --summary_user \
  --service_reasoning_effort low \
  --enable_correction_agent \
  --resume \
  --continue_on_task_error \
  --frame_fps 0.5 \
  --frame_max_side 1920 \
  --frame_rotation none \
  --image_detail high \
  --frame_attach_policy auto
```

Results are checkpointed after each task:

```text
results/<output_model_name>/<scenario><scenario_number>_easy.json
```

Use `--resume` with the same `--output_model_name` to continue a stopped run without overwriting completed records.

## Frame Sampling Rates

The final experiments used these sampling rates:

| Scenario | FPS |
|---|---:|
| `retail6` | 1 |
| `retail10` | 0.5 |
| `kitchen4` | 0.5 |
| `restaurant5` | 1 |
| `order2` | 2 |

The runner uses `--frame_attach_policy auto`: frames are attached immediately for visually phrased user turns; otherwise the service can request visual context by outputting `NEED_VISUAL_CONTEXT`.

## Long Reruns

Long runs should be launched in tmux and logged with `tee`. The repository includes helper scripts for the main final reruns:

```bash
source .env
bash experiments/gpt55_frame_service_runner/run_20260622_kitchen4_newdb_4way.sh
bash experiments/gpt55_frame_service_runner/run_20260622_order2_remaining_3way.sh
```

These scripts split long task sets across multiple tmux windows and write realtime logs under:

```text
experiments/gpt55_frame_service_runner/cache/run_logs/<RUN_ID>/
```

The scripts resolve the project root from their own location. Set `PYTHON=/path/to/python` if you need a specific interpreter; otherwise they use `python`.

## Correction Agent

Enable correction with:

```bash
--enable_correction_agent
```

The correction agent audits:

- Whether a state-changing tool call is supported by branch-predicate evidence.
- Whether tool parameters use canonical DB fields.
- Whether a reply is consistent with executed tool results.
- Whether set meals, allergens, per-100g conditions, final payment, tax, and nutrition computations use the correct tool and scope.

Recent correction behavior is in:

- `experiments/gpt55_frame_service_runner/tool_call_correction.py`
- `experiments/gpt55_frame_service_runner/run_frame_agent.py`

When correction rejects a state-changing tool batch and the max correction round is reached, the runner blocks execution instead of silently applying the rejected mutation.

## Evaluation

Evaluate the current clean submission staging directory:

```bash
python experiments/langgraph_service_agent/evaluate_task_id_aligned.py \
  submission/Lance-dpn_track2/results/Lance-dpn \
  --output eval_result/submission_lance_dpn_track2_eval.json
```

Evaluate any result directory:

```bash
python experiments/langgraph_service_agent/evaluate_task_id_aligned.py \
  results/<run_name> \
  --output eval_result/<run_name>/task_id_aligned_eval.json
```

For split reruns, pass all split result directories:

```bash
python experiments/langgraph_service_agent/evaluate_task_id_aligned.py \
  results/<part1> results/<part2> results/<part3> \
  --output eval_result/<rerun_name>/eval_task_id_aligned.json
```

## Submission Artifacts

Official result staging:

```text
submission/Lance-dpn_track2/
└── results/
    └── Lance-dpn/
        ├── retail6_easy.json
        ├── retail10_easy.json
        ├── kitchen4_easy.json
        ├── restaurant5_easy.json
        └── order2_easy.json
```

Results-only zip:

```text
Lance-dpn_track2_results_only_clean.zip
```

This zip should be generated locally when packaging results. It is intentionally not tracked in Git and should contain only:

```text
results/
└── Lance-dpn/
    ├── retail6_easy.json
    ├── retail10_easy.json
    ├── kitchen4_easy.json
    ├── restaurant5_easy.json
    └── order2_easy.json
```

For official submission, add the required technical report:

```text
Lance-dpn_track2.zip
├── Lance-dpn.pdf
└── results/
    └── Lance-dpn/
        ├── retail6_easy.json
        ├── retail10_easy.json
        ├── kitchen4_easy.json
        ├── restaurant5_easy.json
        └── order2_easy.json
```

Then send the final zip to the official submission email according to the competition instructions.

## Important Fairness Constraints

The service agent must not directly read or use `scenarios/final/*.json`, GT annotations, audit reports, evaluation outputs, or database internals during an official interaction. The service should obtain information only from:

- the current user dialogue,
- attached video frames,
- official tools and their returned results.

The files under `scenarios/final/`, local GT fields, replay reports, and eval outputs are for simulated-user execution, analysis, and local debugging only.

## Git Hygiene

Ignored runtime output:

- `results/`
- `eval_result/`
- `experiments/**/cache/`
- `experiments/visual_observer_runner/eval/`
- `experiments/visual_observer_runner/docs/`
- `*.zip`
- videos and frame caches
- local `.env`
- local manual review notes such as `scenarios/final/manual_check.md`

Avoid adding bulk replay, audit, and local review directories such as:

```text
experiments/visual_observer_runner/eval/instruction_tool_runs/
```

unless there is a specific reason to publish them.
