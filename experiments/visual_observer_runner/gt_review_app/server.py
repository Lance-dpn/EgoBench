#!/usr/bin/env python3
"""Local web review tool for clean-v2 observer GT datasets."""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
APP_DIR = CURRENT_FILE.parent
FRONTEND_DIST = APP_DIR / "frontend" / "dist"
PROJECT_ROOT = CURRENT_FILE.parents[3]
EVAL_ROOT = PROJECT_ROOT / "experiments" / "visual_observer_runner" / "eval"
DEFAULT_DATA_ROOT = EVAL_ROOT / "observer_dataset_clean_v2"
VIDEOS_ROOT = PROJECT_ROOT / "videos"
FRAME_CACHE_ROOT = PROJECT_ROOT / "experiments" / "visual_observer_runner" / "cache" / "gt_review_frames"
DATASET_FILE = "05_observer_dataset_with_gt.json"
SCENARIOS = ("order", "retail", "restaurant", "kitchen")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    json_response(handler, {"error": message}, int(status))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def safe_child_path(root: Path, rel_path: str) -> Path | None:
    decoded = urllib.parse.unquote(rel_path)
    candidate = (root / decoded).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def parse_range_header(header: str | None, file_size: int) -> tuple[int, int] | None:
    if not header or not header.startswith("bytes="):
        return None
    value = header.removeprefix("bytes=").strip()
    if "-" not in value:
        return None
    start_text, end_text = value.split("-", 1)
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    elif end_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return None
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        return None
    if start >= file_size:
        return None
    return max(start, 0), min(end, file_size - 1)


def copy_file_range(src: Any, dst: Any, length: int, chunk_size: int = 1024 * 1024) -> None:
    remaining = length
    while remaining > 0:
        chunk = src.read(min(chunk_size, remaining))
        if not chunk:
            break
        try:
            dst.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            break
        remaining -= len(chunk)


def text_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(text_blob(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def increment(mapping: dict[str, int], key: Any) -> None:
    text = str(key or "unknown")
    mapping[text] = mapping.get(text, 0) + 1


def first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]) if values else ""


def clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_string(value: Any, field_name: str) -> str:
    text = clean_optional_string(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def clean_optional_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number or null") from exc


def clean_range(
    value: Any,
    field_name: str,
    *,
    required: bool = False,
) -> list[float] | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field_name} must be [start, end]")
    start = clean_optional_float(value[0], f"{field_name}[0]")
    end = clean_optional_float(value[1], f"{field_name}[1]")
    if start is None or end is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if start < 0 or end < 0:
        raise ValueError(f"{field_name} cannot contain negative time")
    if end < start:
        raise ValueError(f"{field_name} end must be >= start")
    return [round(start, 3), round(end, 3)]


def clean_string_list(value: Any, field_name: str) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError(f"{field_name} must be a list or newline-delimited string")


def validate_dataset(data: dict[str, Any]) -> None:
    if not isinstance(data.get("cases"), list):
        raise ValueError("Dataset missing cases list")
    for case in data["cases"]:
        case_id = case.get("case_id")
        event_gt = case.get("event_gt") or {}
        detail_gt = case.get("detail_gt") or {}
        visual_query = case.get("visual_query_v1") or {}
        target_kind = ((visual_query.get("target") or {}).get("kind"))
        primary = event_gt.get("primary_content_range")
        expected = event_gt.get("expected_time_range")
        if primary is not None:
            clean_range(primary, f"{case_id}.event_gt.primary_content_range", required=True)
        if expected is not None:
            clean_range(expected, f"{case_id}.event_gt.expected_time_range", required=True)
        if target_kind and detail_gt.get("target_kind") != target_kind:
            raise ValueError(f"{case_id} detail_gt.target_kind must match visual_query target kind")


@dataclass
class Dataset:
    scenario: str
    path: Path
    data: dict[str, Any]


class DatasetStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, tuple[float, Dataset]] = {}

    def dataset_paths(self) -> list[Path]:
        paths = []
        for scenario in SCENARIOS:
            path = self.root / scenario / DATASET_FILE
            if path.exists():
                paths.append(path)
        paths.extend(sorted(self.root.glob(f"*/{DATASET_FILE}")))
        seen: set[Path] = set()
        unique = []
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(path)
        return unique

    def discover(self) -> list[dict[str, Any]]:
        rows = []
        for path in self.dataset_paths():
            try:
                data = load_json(path)
            except json.JSONDecodeError:
                continue
            scenario = str(data.get("scenario") or path.parent.name)
            rows.append(dataset_summary(scenario, path, data))
        order = {name: index for index, name in enumerate(SCENARIOS)}
        rows.sort(key=lambda row: (order.get(row["scenario"], 999), row["scenario"]))
        return rows

    def load(self, scenario: str) -> Dataset | None:
        for path in self.dataset_paths():
            path_scenario = path.parent.name
            if path_scenario != scenario:
                try:
                    data_scenario = str(load_json(path).get("scenario") or path_scenario)
                except json.JSONDecodeError:
                    continue
                if data_scenario != scenario:
                    continue
            mtime = path.stat().st_mtime
            cached = self._cache.get(scenario)
            if cached and cached[0] == mtime:
                return cached[1]
            data = load_json(path)
            dataset = Dataset(scenario=str(data.get("scenario") or scenario), path=path, data=data)
            self._cache[dataset.scenario] = (mtime, dataset)
            return dataset
        return None

    def save(self, dataset: Dataset, reason: str) -> None:
        validate_dataset(dataset.data)
        backup_dir = dataset.path.parent / "review_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"{dataset.path.stem}.{stamp}.json"
        backup_path.write_text(dataset.path.read_text(encoding="utf-8"), encoding="utf-8")
        dataset.data.setdefault("review_metadata", {})
        dataset.data["review_metadata"].update(
            {
                "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
                "review_tool_version": "clean_v2_review_app_v1",
                "last_change_reason": reason,
                "last_backup_path": display_path(backup_path),
            }
        )
        refresh_counts(dataset.data)
        write_json_atomic(dataset.path, dataset.data)
        self._cache.pop(dataset.scenario, None)


def refresh_counts(data: dict[str, Any]) -> None:
    cases = data.get("cases") or []
    data["case_count"] = len(cases)
    data["gt_ready_case_count"] = sum(case.get("gt_status") == "gt_video_annotated" for case in cases)
    data["review_required_count"] = len(cases) - data["gt_ready_case_count"]
    coverage = data.setdefault("coverage", {})
    coverage["video_case_counts"] = counter_dict(case.get("video_id") for case in cases)
    coverage["target_kind_counts"] = counter_dict(
        ((case.get("visual_query_v1") or {}).get("target") or {}).get("kind") for case in cases
    )
    coverage["referent_type_counts"] = counter_dict(
        ((case.get("visual_query_v1") or {}).get("referent") or {}).get("type") for case in cases
    )
    coverage["menu_label_counts"] = counter_dict(
        ((case.get("visual_query_v1") or {}).get("scope") or {}).get("menu_label") for case in cases
    )
    coverage["menu_instance_counts"] = counter_dict(
        ((case.get("visual_query_v1") or {}).get("scope") or {}).get("menu_instance") for case in cases
    )


def counter_dict(values: Any) -> dict[str, int]:
    rows: dict[str, int] = {}
    for value in values:
        increment(rows, value)
    return rows


def dataset_summary(scenario: str, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    cases = data.get("cases") or []
    status_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    target_kind_counts: dict[str, int] = {}
    referent_type_counts: dict[str, int] = {}
    problem_type_counts: dict[str, int] = {}
    human_review_status_counts: dict[str, int] = {}
    menu_label_counts: dict[str, int] = {}
    menu_instance_counts: dict[str, int] = {}
    video_ids: set[str] = set()
    for case in cases:
        visual_query = case.get("visual_query_v1") or {}
        event_gt = case.get("event_gt") or {}
        detail_gt = case.get("detail_gt") or {}
        referent = visual_query.get("referent") or {}
        target = visual_query.get("target") or {}
        scope = visual_query.get("scope") or {}
        increment(status_counts, case.get("gt_status"))
        increment(confidence_counts, f"event:{event_gt.get('confidence') or 'unknown'}")
        increment(confidence_counts, f"detail:{detail_gt.get('confidence') or 'unknown'}")
        increment(target_kind_counts, target.get("kind"))
        increment(referent_type_counts, referent.get("type"))
        increment(problem_type_counts, case.get("problem_type"))
        increment(human_review_status_counts, case.get("human_review_status") or "unreviewed")
        increment(menu_label_counts, scope.get("menu_label"))
        increment(menu_instance_counts, scope.get("menu_instance"))
        if case.get("video_id"):
            video_ids.add(str(case["video_id"]))
    return {
        "scenario": scenario,
        "path": display_path(path),
        "status": data.get("status"),
        "schema_version": data.get("schema_version"),
        "case_count": len(cases),
        "gt_ready_case_count": data.get("gt_ready_case_count"),
        "review_required_count": data.get("review_required_count"),
        "excluded_count": data.get("excluded_count"),
        "video_ids": sorted(video_ids),
        "status_counts": status_counts,
        "confidence_counts": confidence_counts,
        "target_kind_counts": target_kind_counts,
        "referent_type_counts": referent_type_counts,
        "problem_type_counts": problem_type_counts,
        "human_review_status_counts": human_review_status_counts,
        "menu_label_counts": menu_label_counts,
        "menu_instance_counts": menu_instance_counts,
    }


def list_cases(dataset: Dataset, query: dict[str, list[str]]) -> dict[str, Any]:
    rows = [case_row(case) for case in dataset.data.get("cases") or []]
    rows = apply_case_filters(rows, query)
    rows.sort(key=lambda row: (row["video_id"], row["problem_type"], row["case_id"]))
    return {"scenario": dataset.scenario, "count": len(rows), "cases": rows}


def case_row(case: dict[str, Any]) -> dict[str, Any]:
    visual_query = case.get("visual_query_v1") or {}
    referent = visual_query.get("referent") or {}
    target = visual_query.get("target") or {}
    scope = visual_query.get("scope") or {}
    event_gt = case.get("event_gt") or {}
    detail_gt = case.get("detail_gt") or {}
    content_hint = ((referent.get("appearance") or {}).get("content_hint"))
    return {
        "case_id": case.get("case_id"),
        "scenario": case.get("scenario"),
        "video_id": case.get("video_id"),
        "problem_type": case.get("problem_type"),
        "target_kind": target.get("kind"),
        "referent_type": referent.get("type"),
        "referent_action": referent.get("action"),
        "ordinal": referent.get("ordinal"),
        "menu_label": scope.get("menu_label"),
        "menu_instance": scope.get("menu_instance"),
        "content_hint": content_hint,
        "canonical_value": detail_gt.get("canonical_value"),
        "detail_confidence": detail_gt.get("confidence"),
        "event_confidence": event_gt.get("confidence"),
        "gt_status": case.get("gt_status"),
        "human_review_status": case.get("human_review_status") or "unreviewed",
        "human_reviewed_at": case.get("human_reviewed_at"),
        "human_reviewer": case.get("human_reviewer"),
        "primary_content_range": event_gt.get("primary_content_range"),
        "key_frame_time": event_gt.get("key_frame_time"),
    }


def apply_case_filters(rows: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
    text = first_query_value(query, "q").lower()
    video_id = first_query_value(query, "video_id")
    target_kind = first_query_value(query, "target_kind")
    referent_type = first_query_value(query, "referent_type")
    confidence = first_query_value(query, "confidence")
    status = first_query_value(query, "status")
    human_review_status = first_query_value(query, "human_review_status")
    menu_label = first_query_value(query, "menu_label")
    menu_instance = first_query_value(query, "menu_instance")
    filtered = []
    for row in rows:
        haystack = text_blob(row).lower()
        if text and text not in haystack:
            continue
        if video_id and row.get("video_id") != video_id:
            continue
        if target_kind and row.get("target_kind") != target_kind:
            continue
        if referent_type and row.get("referent_type") != referent_type:
            continue
        if confidence and confidence not in {row.get("detail_confidence"), row.get("event_confidence")}:
            continue
        if status and row.get("gt_status") != status:
            continue
        if human_review_status and row.get("human_review_status") != human_review_status:
            continue
        if menu_label and row.get("menu_label") != menu_label:
            continue
        if menu_instance and row.get("menu_instance") != menu_instance:
            continue
        filtered.append(row)
    return filtered


def case_detail(dataset: Dataset, case_id: str) -> dict[str, Any] | None:
    cases = dataset.data.get("cases") or []
    case = next((item for item in cases if item.get("case_id") == case_id), None)
    if case is None:
        return None
    case = json.loads(json.dumps(case, ensure_ascii=False))
    return {
        "scenario": dataset.scenario,
        "case": case,
        "video": {
            "path": case.get("video_id"),
            "url": f"/api/video/{urllib.parse.quote(str(case.get('video_id') or ''))}",
        },
        "frame": {
            "key_frame_time": (case.get("event_gt") or {}).get("key_frame_time"),
            "url": frame_url(case.get("video_id"), (case.get("event_gt") or {}).get("key_frame_time")),
        },
    }


def frame_url(video_id: Any, time_value: Any) -> str | None:
    if not video_id or time_value is None:
        return None
    return f"/api/frame/{urllib.parse.quote(str(video_id))}?t={urllib.parse.quote(str(time_value))}"


def find_case(dataset: Dataset, case_id: str) -> dict[str, Any]:
    case = next((item for item in dataset.data.get("cases") or [] if item.get("case_id") == case_id), None)
    if case is None:
        raise ValueError(f"Unknown case: {case_id}")
    return case


def update_event_gt(dataset: Dataset, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    case = find_case(dataset, case_id)
    event_gt = case.setdefault("event_gt", {})
    event_gt["primary_content_range"] = clean_range(
        payload.get("primary_content_range"), "primary_content_range", required=True
    )
    event_gt["expected_time_range"] = clean_range(
        payload.get("expected_time_range"), "expected_time_range", required=True
    )
    event_gt["allowed_transition_range"] = clean_range(payload.get("allowed_transition_range"), "allowed_transition_range")
    key_frame_time = clean_optional_float(payload.get("key_frame_time"), "key_frame_time")
    if key_frame_time is None:
        raise ValueError("key_frame_time is required")
    if key_frame_time < 0:
        raise ValueError("key_frame_time cannot be negative")
    primary_start, primary_end = event_gt["primary_content_range"]
    if key_frame_time < primary_start or key_frame_time > primary_end:
        raise ValueError("key_frame_time must be inside primary_content_range")
    event_gt["key_frame_time"] = round(key_frame_time, 3)
    event_gt["confidence"] = clean_string(payload.get("confidence"), "confidence")
    event_gt["evidence"] = clean_optional_string(payload.get("evidence")) or ""
    expected_region = payload.get("expected_region")
    if not isinstance(expected_region, dict):
        raise ValueError("expected_region must be an object")
    event_gt["expected_region"] = {
        "description": clean_optional_string(expected_region.get("description")),
        "coarse_region": clean_optional_string(expected_region.get("coarse_region")),
        "notes": clean_optional_string(expected_region.get("notes")),
    }
    append_review_note(case, payload.get("review_note"), "event_gt")
    return {"ok": True, "case": case}


def update_detail_gt(dataset: Dataset, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    case = find_case(dataset, case_id)
    detail_gt = case.setdefault("detail_gt", {})
    visual_target_kind = (((case.get("visual_query_v1") or {}).get("target") or {}).get("kind"))
    target_kind = clean_string(payload.get("target_kind"), "target_kind")
    if visual_target_kind and target_kind != visual_target_kind:
        raise ValueError("target_kind must match visual_query_v1.target.kind")
    detail_gt["target_kind"] = target_kind
    detail_gt["canonical_value"] = clean_string(payload.get("canonical_value"), "canonical_value")
    detail_gt["acceptable_aliases"] = clean_string_list(payload.get("acceptable_aliases"), "acceptable_aliases")
    detail_gt["negative_neighbors"] = clean_string_list(payload.get("negative_neighbors"), "negative_neighbors")
    detail_gt["confidence"] = clean_string(payload.get("confidence"), "confidence")
    detail_gt["evidence"] = clean_optional_string(payload.get("evidence")) or ""
    append_review_note(case, payload.get("review_note"), "detail_gt")
    return {"ok": True, "case": case}


def update_case_review(dataset: Dataset, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    case = find_case(dataset, case_id)
    if "gt_status" in payload:
        case["gt_status"] = clean_string(payload.get("gt_status"), "gt_status")
    if "human_review_status" in payload:
        status = clean_string(payload.get("human_review_status"), "human_review_status")
        if status not in {"unreviewed", "verified", "needs_fix"}:
            raise ValueError("human_review_status must be unreviewed, verified, or needs_fix")
        case["human_review_status"] = status
        case["human_reviewed_at"] = datetime.now(timezone.utc).isoformat()
        case["human_reviewer"] = clean_optional_string(payload.get("human_reviewer")) or "manual_review"
    note = clean_optional_string(payload.get("review_note"))
    if note:
        append_review_note(case, note, "case")
    return {"ok": True, "case": case}


def append_review_note(case: dict[str, Any], note_value: Any, source: str) -> None:
    note = clean_optional_string(note_value)
    if not note:
        return
    stamp = datetime.now(timezone.utc).isoformat()
    text = f"{stamp} [{source}] {note}"
    notes = case.setdefault("review_notes", [])
    if text not in notes:
        notes.append(text)


class ReviewHandler(BaseHTTPRequestHandler):
    store = DatasetStore(DEFAULT_DATA_ROOT)

    def do_GET(self) -> None:  # noqa: N802
        self.route_request(write_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self.route_request(write_body=False)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        if not path.startswith("/api/datasets/"):
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown path: {path}")
            return
        try:
            payload = self.read_json_body()
            self.serve_dataset_post(path, payload)
        except json.JSONDecodeError:
            error_response(self, HTTPStatus.BAD_REQUEST, "Request body must be valid JSON")
        except ValueError as exc:
            error_response(self, HTTPStatus.BAD_REQUEST, str(exc))

    def route_request(self, write_body: bool) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/api/datasets":
            json_response(self, {"datasets": self.store.discover()})
            return
        if path.startswith("/api/datasets/"):
            self.serve_dataset_api(path, query)
            return
        if path.startswith("/api/video/"):
            self.serve_video(path.removeprefix("/api/video/"), write_body=write_body)
            return
        if path.startswith("/api/frame/"):
            self.serve_frame(path.removeprefix("/api/frame/"), query, write_body=write_body)
            return
        self.serve_frontend(path, write_body=write_body)

    def serve_dataset_api(self, path: str, query: dict[str, list[str]]) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            error_response(self, HTTPStatus.NOT_FOUND, "Missing scenario")
            return
        scenario = parts[2]
        dataset = self.store.load(scenario)
        if dataset is None:
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown scenario: {scenario}")
            return
        if len(parts) == 3:
            json_response(self, dataset_summary(dataset.scenario, dataset.path, dataset.data))
            return
        if len(parts) == 4 and parts[3] == "cases":
            json_response(self, list_cases(dataset, query))
            return
        if len(parts) == 5 and parts[3] == "cases":
            detail = case_detail(dataset, parts[4])
            if detail is None:
                error_response(self, HTTPStatus.NOT_FOUND, f"Unknown case: {parts[4]}")
                return
            json_response(self, detail)
            return
        error_response(self, HTTPStatus.NOT_FOUND, f"Unknown dataset path: {path}")

    def serve_dataset_post(self, path: str, payload: dict[str, Any]) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) != 6 or parts[3] != "cases":
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown dataset path: {path}")
            return
        scenario = parts[2]
        case_id = parts[4]
        action = parts[5]
        dataset = self.store.load(scenario)
        if dataset is None:
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown scenario: {scenario}")
            return
        if action == "event-gt":
            result = update_event_gt(dataset, case_id, payload)
        elif action == "detail-gt":
            result = update_detail_gt(dataset, case_id, payload)
        elif action == "review":
            result = update_case_review(dataset, case_id, payload)
        else:
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown case action: {action}")
            return
        self.store.save(dataset, f"{action} update {case_id}")
        json_response(self, result)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def serve_frontend(self, path: str, write_body: bool = True) -> None:
        rel_path = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = safe_child_path(FRONTEND_DIST, rel_path)
        if candidate is None or not candidate.exists() or not candidate.is_file():
            candidate = FRONTEND_DIST / "index.html"
        if not candidate.exists() or not candidate.is_file():
            error_response(
                self,
                HTTPStatus.NOT_FOUND,
                "Frontend build not found. Run `npm install && npm run build` in gt_review_app/frontend.",
            )
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "text/html"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def serve_video(self, rel_path: str, write_body: bool = True) -> None:
        path = safe_child_path(VIDEOS_ROOT, rel_path)
        if path is None or not path.exists() or not path.is_file():
            error_response(self, HTTPStatus.NOT_FOUND, f"Video not found: {rel_path}")
            return
        file_size = path.stat().st_size
        range_value = parse_range_header(self.headers.get("Range"), file_size)
        content_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
        if range_value is None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if write_body:
                with path.open("rb") as handle:
                    copy_file_range(handle, self.wfile, file_size)
            return
        start, end = range_value
        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if write_body:
            with path.open("rb") as handle:
                handle.seek(start)
                copy_file_range(handle, self.wfile, length)

    def serve_frame(self, rel_path: str, query: dict[str, list[str]], write_body: bool = True) -> None:
        video_path = safe_child_path(VIDEOS_ROOT, rel_path)
        if video_path is None or not video_path.exists() or not video_path.is_file():
            error_response(self, HTTPStatus.NOT_FOUND, f"Video not found: {rel_path}")
            return
        time_text = first_query_value(query, "t") or "0"
        try:
            time_value = max(float(time_text), 0.0)
        except ValueError:
            error_response(self, HTTPStatus.BAD_REQUEST, "t must be a number")
            return
        frame_path = cached_frame_path(video_path.name, time_value)
        if not frame_path.exists():
            try:
                generate_frame(video_path, time_value, frame_path)
            except RuntimeError as exc:
                error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return
        body = frame_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


def cached_frame_path(video_name: str, time_value: float) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in video_name)
    safe_time = str(round(time_value, 3)).replace(".", "_")
    return FRAME_CACHE_ROOT / safe_name / f"t_{safe_time}.jpg"


def generate_frame(video_path: Path, time_value: float, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; key frame extraction is unavailable")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.jpg")
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(round(time_value, 3)),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(tmp_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0 or not tmp_path.exists():
        raise RuntimeError(f"ffmpeg failed to extract frame: {result.stderr[-1000:]}")
    tmp_path.replace(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18100)
    parser.add_argument(
        "--data_root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Directory containing clean-v2 scenario subdirectories.",
    )
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    if not data_root.exists():
        raise SystemExit(f"Clean-v2 dataset directory not found: {data_root}")
    ReviewHandler.store = DatasetStore(data_root)
    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    print(f"Clean-v2 GT review app: http://{args.host}:{args.port}")
    print(f"Scanning: {data_root}/*/{DATASET_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
