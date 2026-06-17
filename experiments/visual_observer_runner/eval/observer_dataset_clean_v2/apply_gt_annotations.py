#!/usr/bin/env python3
"""Apply reviewed GT annotation files to clean v2 datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = ROOT / "experiments/visual_observer_runner/eval/observer_dataset_clean_v2"
SCENARIOS = ("order", "retail", "restaurant", "kitchen")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_datasets() -> dict[str, dict[str, Any]]:
    return {scenario: load_json(DATA_ROOT / scenario / "05_observer_dataset_with_gt.json") for scenario in SCENARIOS}


def find_case(datasets: dict[str, dict[str, Any]], case_id: str) -> tuple[str, dict[str, Any]] | None:
    for scenario, data in datasets.items():
        for case in data["cases"]:
            if case["case_id"] == case_id:
                return scenario, case
    return None


def refresh_counts(data: dict[str, Any]) -> None:
    gt_ready = sum(case["gt_status"] == "gt_video_annotated" for case in data["cases"])
    review_required = sum(case["gt_status"] != "gt_video_annotated" for case in data["cases"])
    data["gt_ready_case_count"] = gt_ready
    data["review_required_count"] = review_required


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    args = parser.parse_args()

    annotation_path = Path(args.annotations)
    annotations = load_json(annotation_path)["annotations"]
    datasets = load_datasets()
    applied: list[str] = []
    missing: list[str] = []

    for annotation in annotations:
        found = find_case(datasets, annotation["case_id"])
        if not found:
            missing.append(annotation["case_id"])
            continue
        _, case = found
        case["event_gt"] = annotation["event_gt"]
        case["detail_gt"] = annotation["detail_gt"]
        case["gt_status"] = "gt_video_annotated"
        case["evaluation_modes"] = ["event_only", "detail_with_gt_event", "detail_with_predicted_event", "end_to_end"]
        case.setdefault("review_notes", []).append(f"GT applied from {annotation_path.name}.")
        applied.append(annotation["case_id"])

    for data in datasets.values():
        refresh_counts(data)

    if args.apply:
        for scenario, data in datasets.items():
            write_json(DATA_ROOT / scenario / "05_observer_dataset_with_gt.json", data)

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry_run",
                "applied_count": len(applied),
                "applied_case_ids": applied,
                "missing_case_ids": missing,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
