#!/usr/bin/env python3
"""Generate review artifacts before visual GT video inspection.

The output is intentionally pre-GT: event/detail templates are empty and marked
pending_video_inspection. This lets us review the taxonomy and normalization
behavior before filling timestamps, regions, or detail identities.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.visual_observer_runner.visual_request_normalizer import (  # noqa: E402
    build_detail_gt_template,
    build_event_gt_template,
    normalize_visual_requests,
)


SCENARIOS_DIR = PROJECT_ROOT / "scenarios" / "final"
DEFAULT_OUTPUT_ROOT = CURRENT_FILE.parent / "eval"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def observer_rows(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [request["observer_task"] for request in requests]


def scenario_files(args: argparse.Namespace) -> list[Path]:
    if args.scenario_key:
        return [SCENARIOS_DIR / f"{args.scenario_key}.json"]
    if args.scenario:
        prefix = args.scenario
        if args.scenario_number is not None:
            prefix = f"{args.scenario}{args.scenario_number}"
        return sorted(SCENARIOS_DIR.glob(f"{prefix}*.json"))
    return sorted(SCENARIOS_DIR.glob("*.json"))


def collect_requests(paths: list[Path], max_tasks: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    event_templates: list[dict[str, Any]] = []
    detail_templates: list[dict[str, Any]] = []

    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        scenario_key = path.stem
        tasks = load_json(path)
        if max_tasks is not None:
            tasks = tasks[:max_tasks]
        for idx, task in enumerate(tasks, start=1):
            task_requests = normalize_visual_requests(
                scenario_key=scenario_key,
                task_id=idx,
                task=task,
            )
            requests.extend(task_requests)
            event_templates.extend(build_event_gt_template(request) for request in task_requests)
            detail_templates.extend(build_detail_gt_template(request) for request in task_requests)

    return requests, event_templates, detail_templates


def summarize_requests(requests: list[dict[str, Any]], paths: list[Path]) -> str:
    by_scenario = Counter(request["scenario_key"] for request in requests)
    by_pattern = Counter(request["pattern"] for request in requests)
    by_event_mode = Counter(request["event_mode"] for request in requests)
    by_detail_mode = Counter(request["detail_mode"] for request in requests)
    by_target_key = Counter(request["target_key"] for request in requests)
    by_abstract_task = Counter(request["abstract_task_key"] for request in requests)
    by_visual_task_group = Counter(request["visual_task_group_key"] for request in requests)
    by_pair = Counter((request["scenario_key"], request["event_mode"]) for request in requests)
    review_confidence = Counter(request["extraction_confidence"] for request in requests)
    example_by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for request in requests:
        bucket = example_by_mode[request["event_mode"]]
        if len(bucket) < 3:
            bucket.append(request)

    lines = [
        "# Visual GT Bootstrap Review Summary",
        "",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "This package is pre-video-inspection. Event/detail GT fields are empty",
        "and marked `pending_video_inspection` for human review before any GT is",
        "frozen.",
        "",
        "## Source Files",
        "",
    ]
    for path in paths:
        lines.append(f"- `{path.relative_to(PROJECT_ROOT)}`")

    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- normalized visual requests: {len(requests)}",
            f"- scenarios: {len(by_scenario)}",
            "",
            "### By Scenario",
            "",
        ]
    )
    for key, count in sorted(by_scenario.items()):
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### By Event Mode", ""])
    for key, count in by_event_mode.most_common():
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### By Detail Mode", ""])
    for key, count in by_detail_mode.most_common():
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### By Fine Pattern (debug)", ""])
    for key, count in by_pattern.most_common():
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### By Target Key", ""])
    for key, count in by_target_key.most_common():
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### Top Abstract Visual Tasks", ""])
    for key, count in by_abstract_task.most_common(20):
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### Top Coarse Visual Task Groups", ""])
    for key, count in by_visual_task_group.most_common(20):
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "### Extraction Confidence", ""])
    for key, count in review_confidence.most_common():
        lines.append(f"- `{key}`: {count}")

    lines.extend(["", "## Scenario x Event Mode Matrix", ""])
    for (scenario_key, event_mode), count in sorted(by_pair.items()):
        lines.append(f"- `{scenario_key}` / `{event_mode}`: {count}")

    lines.extend(["", "## Event Mode Examples", ""])
    for event_mode, examples in sorted(example_by_mode.items()):
        lines.append(f"### `{event_mode}`")
        lines.append("")
        for request in examples:
            review_snippet = request["review_source_instruction_snippet"]
            if len(review_snippet) > 260:
                review_snippet = review_snippet[:257] + "..."
            lines.append(
                f"- `{request['request_id']}` pattern=`{request['pattern']}` "
                f"detail=`{request['detail_mode']}` target=`{request['target_key']}` "
                f"ordinal=`{request.get('ordinal')}` action=`{request.get('action')}`"
            )
            lines.append(f"  review snippet: {review_snippet}")
        lines.append("")

    lines.extend(
        [
            "## Review Checklist",
            "",
            "- Confirm taxonomy pattern names are sufficient.",
            "- Confirm high-recall extraction is acceptable before video GT work.",
            "- Confirm final scenario `key/value` is not included as detail GT.",
            "- Confirm event/detail template fields are enough for manual correction.",
            "- Confirm center-based event scoring remains the primary event metric.",
            "",
        ]
    )
    return "\n".join(lines)


def build_abstract_task_groups(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for request in requests:
        key = request["abstract_task_key"]
        group = groups.setdefault(
            key,
            {
                "abstract_task_key": key,
                "event_mode": request["event_mode"],
                "detail_mode": request["detail_mode"],
                "target_key": request["target_key"],
                "count": 0,
                "scenario_keys": [],
                "request_ids": [],
                "examples": [],
            },
        )
        group["count"] += 1
        if request["scenario_key"] not in group["scenario_keys"]:
            group["scenario_keys"].append(request["scenario_key"])
        group["request_ids"].append(request["request_id"])
        if len(group["examples"]) < 5:
            group["examples"].append(
                {
                    "request_id": request["request_id"],
                    "scenario_key": request["scenario_key"],
                    "task_id": request["task_id"],
                    "review_source_instruction_snippet": request["review_source_instruction_snippet"],
                    "observer_task": request["observer_task"],
                }
            )
    return sorted(groups.values(), key=lambda item: (-item["count"], item["abstract_task_key"]))


def build_visual_task_groups(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for request in requests:
        key = request["visual_task_group_key"]
        group = groups.setdefault(
            key,
            {
                "visual_task_group_key": key,
                "event_mode": request["event_mode"],
                "detail_mode": request["detail_mode"],
                "target_key": request["target_key"],
                "count": 0,
                "scenario_keys": [],
                "abstract_task_keys": [],
                "request_ids": [],
                "examples": [],
            },
        )
        group["count"] += 1
        if request["scenario_key"] not in group["scenario_keys"]:
            group["scenario_keys"].append(request["scenario_key"])
        if request["abstract_task_key"] not in group["abstract_task_keys"]:
            group["abstract_task_keys"].append(request["abstract_task_key"])
        group["request_ids"].append(request["request_id"])
        if len(group["examples"]) < 5:
            group["examples"].append(
                {
                    "request_id": request["request_id"],
                    "scenario_key": request["scenario_key"],
                    "task_id": request["task_id"],
                    "review_source_instruction_snippet": request["review_source_instruction_snippet"],
                    "observer_task": request["observer_task"],
                }
            )
    return sorted(groups.values(), key=lambda item: (-item["count"], item["visual_task_group_key"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["order", "retail", "restaurant", "kitchen"])
    parser.add_argument("--scenario_number", type=int)
    parser.add_argument("--scenario_key", help="Exact scenario key, e.g. order1 or retail8.")
    parser.add_argument("--max_tasks", type=int, help="Limit tasks per scenario for review.")
    parser.add_argument("--output_dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = scenario_files(args)
    if not paths:
        raise SystemExit("No scenario files matched.")

    run_name = time.strftime("review_%Y%m%d%H%M%S")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_name)
    requests, event_templates, detail_templates = collect_requests(paths, args.max_tasks)
    abstract_groups = build_abstract_task_groups(requests)
    visual_task_groups = build_visual_task_groups(requests)

    write_jsonl(output_dir / "normalized_visual_requests.jsonl", requests)
    write_jsonl(output_dir / "observer_tasks.jsonl", observer_rows(requests))
    write_json(output_dir / "event_gt_templates.json", event_templates)
    write_json(output_dir / "detail_gt_templates.json", detail_templates)
    write_json(output_dir / "abstract_visual_task_groups.json", abstract_groups)
    write_json(output_dir / "coarse_visual_task_groups.json", visual_task_groups)
    summary = summarize_requests(requests, paths)
    (output_dir / "summary.md").write_text(summary, encoding="utf-8")

    print(f"output_dir={output_dir}")
    print(f"scenario_files={len(paths)}")
    print(f"normalized_visual_requests={len(requests)}")
    print(f"event_templates={len(event_templates)}")
    print(f"detail_templates={len(detail_templates)}")
    print(f"abstract_visual_task_groups={len(abstract_groups)}")


if __name__ == "__main__":
    main()
