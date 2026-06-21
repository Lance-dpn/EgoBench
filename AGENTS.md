# EgoBench Agent Operating Guide

This repository is the EgoLink 2026 Track 2 service-agent project. Use this file
as the stable working agreement for future agent work in this repo.

## Project Map

- `README.md`: benchmark usage, output formats, scoring rules, and official
  competition assumptions.
- `config/`: model and media configuration.
  - `user_agent_config.py`: simulated user model. Treat user-agent prompt/model
    changes as benchmark-sensitive.
  - `service_agent_config.py`: evaluated service-agent model and video access.
- `run/`: core interaction sandbox.
  - `multi_agent.py`: main runner. It loads a scenario, initializes the matching
    database, drives the simulated user and service agent, executes tool calls,
    and writes interaction logs under `results/{model_name}/`.
  - `prompts.py`: user and service prompt templates. Service-agent prompts are
    the primary prompt-tuning surface.
  - `utils.py`: media packaging, tool-call parsing, tool execution, and user
    response checks.
  - `apis/`: provider adapters for OpenAI-compatible or vendor-specific calls.
- `tools/`: service-agent tools and benchmark database state.
  - Each domain has `*_tools.json` tool schemas, `*_db.py` tool/database
    behavior, `*_init.py` initial data, and `*_test.py` checks.
  - Domains are `retail`, `kitchen`, `restaurant`, and `order`.
- `scenarios/final/`: task definitions and ground truth.
  - Each task includes `Instruction`, `analysis`, `ground_truth`, visual
    metadata, and sometimes key/value anchors for visual grounding.
  - Treat `ground_truth` plus the initialized benchmark database as the source
    of truth, not external real-world knowledge.
- `results/`: generated interaction trajectories. Ignored by git.
- `eval_result/`: generated evaluation outputs. Ignored by git.
- `analysis_scripts/`: evaluation and result-analysis tools.
  - `evaluate_interaction.py`: main evaluator. It compares tool calls and final
    database hashes.
  - `print_eval.py`: reporting helper.
  - `analyze_error_reasons.py`: heuristic error classification. Useful, but do
    not stop at its labels.
  - `run_eval.sh`: standard evaluation entry point.
- `experiments/visual_observer_runner/`: on-demand visual grounding runner.
  It exposes a virtual `resolve_visual_reference` flow and is important for
  ordinal pointing or visually anchored tasks.
- `experiments/aura_gpt_runner/`: alternate/hybrid runner experiments.

## Daily Workflow

1. Start from the repository root:

   ```bash
   cd /mnt/sda/dpn/egolink2026/code/track2/EgoBench
   ```

2. Inspect current state before changing files:

   ```bash
   git status --short --branch
   git diff
   ```

3. Do not overwrite unrelated local changes. If the worktree contains user
   edits outside the current task, leave them unstaged unless explicitly told
   otherwise.

4. Keep generated artifacts out of git. `results/`, `eval_result/`, videos,
   caches, `.env*`, model weights, and local agent state are intentionally
   ignored.

5. Prefer small commits with clear scope. For this project, commit code,
   prompts, tool/database fixes, docs, and scripts separately when they answer
   different questions.

6. Synchronize with GitHub after confirmed changes:

   ```bash
   git status --short --branch
   git add <intended-files-only>
   git commit -m "<short scope>"
   git push origin <current-branch>
   ```

   If the working tree is mixed, stage exact paths only. Never use `git add -A`
   unless every changed file belongs to the same commit.

## Running And Evaluation

Run a targeted scenario during development:

```bash
python run/multi_agent.py \
  --scenario order \
  --scenario_number 1 \
  --service_model_name "$SERVICE_MODEL_NAME" \
  --multi_agent_user \
  --summary_user \
  --num_tasks 10
```

Run the full configured suite:

```bash
bash run_all_scenarios.sh
```

Evaluate generated results:

```bash
bash analysis_scripts/run_eval.sh
```

or directly:

```bash
cd analysis_scripts
python evaluate_interaction.py --model_name "<results-dir-name>" --num_samples 0
```

Primary ranking metric is `avg_joint_success_rate`, and a task is successful
only when both process/tool-call evaluation and final database-state evaluation
pass.

## Post-Run Deep Diagnosis

After every task execution or evaluation run, do not only report aggregate
scores. For failed or suspicious tasks, perform a concrete task-level audit:

1. Identify failed tasks from `eval_result/<model>/<scenario>_easy_eval.json`.
   Check:
   - `detailed_results[].tool_based`
   - `detailed_results[].result_based`
   - `detailed_results[].joint_success`
   - `micro_tool_stats`
   - `invalid_scenarios` when only a subset of tasks was run

2. Open the matching scenario in `scenarios/final/<scenario><number>.json`.
   For each failed `task_id`, read:
   - `Instruction`: what the simulated user is supposed to ask for.
   - `analysis`: benchmark intended reasoning path.
   - `ground_truth`: expected state-changing and final computation calls.
   - `key`/`value` and visual metadata when the task depends on pointed items.

3. Open the matching trajectory in `results/<model>/<scenario>_easy.json`.
   Compare:
   - user turns and whether the user got diverted or repeated unclear requests;
   - service-agent natural-language claims;
   - every `tool_calls[].calls` item and its `results`;
   - missing calls, extra calls, wrong parameters, wrong branch decisions, and
     calls made against the wrong restaurant/user/cart/order.

4. Inspect the relevant tool schemas in `tools/<domain>/<domain>_tools.json`.
   Verify the exact tool names, required parameters, enum values, and whether
   the service agent used an unavailable or malformed tool.

5. Inspect the benchmark database and tool implementation:
   - `tools/<domain>/<domain>_init.py`: exact catalog/order/cart/menu values,
     initial user state, prices, discounts, nutrition, allergens, set meals,
     and naming variants.
   - `tools/<domain>/<domain>_db.py`: fuzzy matching behavior, parameter
     handling, state mutation semantics, and final computation logic.
   - For order set meals, explicitly check whether the tool treats the set meal
     as a top-level order item or expands included dishes. In the current order
     data, `compute_total_payment` over top-level set meals can return `0.0`
     because set-meal prices are missing, while tax and nutrition tools expand
     included dishes.

6. Reconstruct the expected and actual database effect. When needed, replay the
   ground-truth calls and the model calls through the same DB class rather than
   reasoning from text only.

7. Classify root cause with evidence. Use precise categories such as:
   - visual grounding error: wrong pointed dish/category/ordinal event;
   - tool syntax error: invalid JSON, mixed text plus JSON, missing parameters;
   - tool selection error: wrong API chosen for the requested operation;
   - parameter grounding error: wrong `user_id`, restaurant, category, dish, set
     meal, quantity, tag, taste, nutrition field, or threshold;
   - reasoning branch error: wrong conditional path after querying the DB;
   - database/tool mismatch: prompt expected one name/value but tool data uses
     another benchmark-specific value;
   - over-operation: extra mutation changed the final DB hash;
   - under-operation: required mutation or final computation missing;
   - user-interaction issue: service answer confused the simulated user enough
     to derail the task.

8. Propose the next improvement based on the root cause:
   - prompt changes for JSON-only calls, state tracking, branch discipline, or
     concise user clarification;
   - visual-observer changes for pointing/ordinal/category recognition;
   - tool wrapper or validation changes for parameter normalization;
   - benchmark data fixes only when `scenarios/final`, `tools`, and evaluator
     evidence show a real inconsistency.

9. Treat result-based success as insufficient when tool-based success fails.
   Add-then-remove workflows and non-mutating final calculations can make the
   final database hash look correct even when the agent skipped required tool
   calls or chose the wrong branch.

10. For visual-observer order failures, audit restaurant selection before
    auditing only the pointed item. If the service agent selected the wrong
    restaurant, subsequent visual names, set meals, categories, and database
    checks may all become inconsistent. Look for later user-mentioned set meals
    or dish names that contradict the active restaurant.

11. Record likely author data or grounding issues in
    `experiments/visual_observer_runner/docs/order_grounding_issues.md` instead
    of silently changing official scenario, tool, or evaluation files.

## Reporting Standard

For every completed debugging pass, report:

- exact scenario, task id, model/result directory, and eval file;
- expected ground-truth calls summarized from `scenarios/final`;
- actual calls and tool results summarized from `results`;
- concrete discrepancy and root cause;
- next action and whether it is prompt, observer, tool/database, or evaluation
  logic work;
- validation command and outcome.

Keep conclusions evidence-based. If a failure label from
`analyze_error_reasons.py` conflicts with the task-level evidence, prefer the
task-level reconstruction.

# Environment Setup

Activate conda environment before you use pip or conda to install packages, or run any scripts:

`source /home/yan2u/miniconda3/etc/profile.d/conda.sh && conda activate egolink`

You can install packages with pip or conda if you are missing some dependencies.
