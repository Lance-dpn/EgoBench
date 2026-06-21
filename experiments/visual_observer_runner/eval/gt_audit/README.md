# GT Audit Workflow

This directory contains a small, deterministic audit path for EgoBench GT checks.
It is intentionally not a free-running LLM agent.

## Goal

For each reviewed task, the audit should:

- read the scenario task and its current `ground_truth`;
- treat `value` as the first resolved visual anchor and `secondary_value` as the second resolved visual anchor;
- execute official DB tools to gather branch and candidate evidence;
- make branch and ranking decisions from tool results;
- execute required state mutations;
- read the latest current state before final output tools;
- call final compute/tally tools;
- compare the generated GT calls with the current scenario GT;
- emit a report with enough evidence to review any mismatch.

## Non-goals

- Do not let an LLM directly generate GT.
- Do not run full scenario sweeps from this directory.
- Do not compute totals, taxes, or nutrition manually.
- Do not hide branch-evidence calls inside benchmark GT.

## Spec Shape

The first implemented spec is `specs/order2_task6.json`. It is deliberately
explicit: the spec names the visual anchor, page-scope candidates, branch field,
mutation, post-check, and final output tools.

The deterministic script is expected to be conservative. If a requested
operation cannot be proven through official tools, it should put that limitation
in the report instead of inventing data.
