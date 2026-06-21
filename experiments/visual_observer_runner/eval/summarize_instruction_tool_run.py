#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_latest(path: Path) -> dict[int, dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        task_id = record.get("task_id")
        if task_id is None:
            continue
        record["_jsonl_line"] = line_number
        latest[int(task_id)] = record
    return latest


def summarize_file(path: Path) -> dict[str, Any]:
    latest = load_latest(path)
    records = list(latest.values())
    errors = [record for record in records if record.get("error")]
    successes = [record for record in records if not record.get("error")]
    mismatches = [
        record
        for record in successes
        if not record.get("gt_comparison", {}).get("all_pairs_match")
    ]
    return {
        "file": str(path),
        "scenario": path.stem,
        "latest_tasks": len(records),
        "successes": len(successes),
        "errors": len(errors),
        "mismatches": len(mismatches),
        "error_task_ids": [record.get("task_id") for record in errors],
        "mismatch_task_ids": [record.get("task_id") for record in mismatches],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize latest task records from instruction-driven GT JSONL files.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    summaries = [summarize_file(path) for path in sorted(args.run_dir.glob("*.jsonl"))]
    payload = {"run_dir": str(args.run_dir), "summaries": summaries}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for summary in summaries:
        print(
            f"{summary['scenario']}: latest={summary['latest_tasks']} "
            f"success={summary['successes']} errors={summary['errors']} "
            f"mismatches={summary['mismatches']} "
            f"mismatch_task_ids={summary['mismatch_task_ids'][:20]}"
        )


if __name__ == "__main__":
    main()
