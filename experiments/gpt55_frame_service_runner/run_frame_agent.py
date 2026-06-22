#!/usr/bin/env python3
"""EgoBench runner for GPT-5.5 image-frame service-agent experiments."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(PROJECT_ROOT / ".env")

DEFAULT_SERVICE_MODEL_NAME = (
    os.environ.get("SERVICE_MODEL_NAME")
    or os.environ.get("OPENAI_MODEL_NAME")
    or "gpt-5.5"
)
DEFAULT_USER_MODEL_NAME = (
    os.environ.get("USER_MODEL_NAME")
    or os.environ.get("SERVICE_MODEL_NAME")
    or os.environ.get("OPENAI_MODEL_NAME")
    or "qwen3.5-397b-a17b"
)
VIDEO_LOCAL_PATH = os.environ.get("VIDEO_LOCAL_PATH", "./videos")
VISUAL_CONTEXT_REQUEST = "NEED_VISUAL_CONTEXT"
VISUAL_REFERENCE_PATTERN = re.compile(
    r"\b("
    r"video|frame|image|picture|photo|visual|visible|shown|showing|see|look|"
    r"point|pointed|pointing|marked|selected|highlighted|circled|boxed|"
    r"left|right|top|bottom|middle|center|front|back|near|next|under|above|"
    r"color|blue|red|green|yellow|white|black|orange|purple|pink|light|dark|"
    r"bottle|shelf|menu|table|plate|bowl|pan|pot|knife|hand|border|region|area"
    r")\b",
    re.IGNORECASE,
)
VISUAL_DEICTIC_PATTERN = re.compile(r"\b(this|that|these|those)\b", re.IGNORECASE)
VISUAL_OBJECT_PATTERN = re.compile(
    r"\b(item|object|product|dish|ingredient|bottle|shelf|menu|table|plate|box|region|area)\b",
    re.IGNORECASE,
)
from experiments.gpt55_frame_service_runner.frame_sampler import (  # noqa: E402
    SampledFrame,
    frame_metadata,
    image_data_url,
    sample_video_frames,
)
from experiments.gpt55_frame_service_runner.openai_responses_client import (  # noqa: E402
    OpenAIResponsesServiceClient,
)
from experiments.gpt55_frame_service_runner.prompts import (  # noqa: E402
    SERVICE_PROMPT_VERSION,
    build_service_agent_prompt,
)
from experiments.gpt55_frame_service_runner.tool_call_correction import (  # noqa: E402
    ChatCompletionsCorrectionClient,
    CorrectionDecision,
    ResponsesCorrectionClient,
    audit_context_stats,
    build_audit_context,
    build_correction_system_prompt,
    compact_decision_feedback,
    correction_log_path,
    deterministic_batch_approval,
    deterministic_batch_feedback,
    deterministic_reply_feedback,
    env_default_model,
    env_chat_completions_model,
    failure_decision,
    is_mutation_call,
    normalize_calls,
    review_with_agent,
    write_correction_log,
)
from run.prompts import USER_TEXT_ONLY_PROMPT_EASY, USER_TURN_SUMMARY_PROMPT  # noqa: E402
from tools.kitchen.kitchen_db import KitchenDB  # noqa: E402
from tools.kitchen.kitchen_init import kitchen_init_data  # noqa: E402
from tools.order.order_db import OrderDB  # noqa: E402
from tools.order.order_init import order_init_data  # noqa: E402
from tools.restaurant.restaurant_db import RestaurantDB  # noqa: E402
from tools.restaurant.restaurant_init import restaurant_init_data, restaurant_init_data5  # noqa: E402
from tools.retail.retail_db import RetailDB  # noqa: E402
from tools.retail.retail_init import (  # noqa: E402
    retail_init_data1,
    retail_init_data2,
    retail_init_data3,
    retail_init_data4,
    retail_init_data5,
    retail_init_data6,
    retail_init_data7,
    retail_init_data8,
    retail_init_data9,
    retail_init_data10,
)


RETAIL_INIT_DATA = {
    1: retail_init_data1,
    2: retail_init_data2,
    3: retail_init_data3,
    4: retail_init_data4,
    5: retail_init_data5,
    6: retail_init_data6,
    7: retail_init_data7,
    8: retail_init_data8,
    9: retail_init_data9,
    10: retail_init_data10,
}


def init_db(scenario: str, scenario_number: int) -> Any:
    if scenario == "retail":
        db = RetailDB()
        db.init_from_json(RETAIL_INIT_DATA[scenario_number])
        return db
    if scenario == "kitchen":
        db = KitchenDB()
        db.init_from_json(kitchen_init_data)
        return db
    if scenario == "restaurant":
        db = RestaurantDB()
        db.init_from_json(restaurant_init_data5 if scenario_number == 5 else restaurant_init_data)
        return db
    if scenario == "order":
        db = OrderDB()
        db.init_from_json(order_init_data)
        return db
    raise ValueError(f"Unsupported scenario: {scenario}")


def slugify_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return slug.strip("-") or "model"


def timestamp_tag() -> str:
    return time.strftime("%Y%m%d%H%M", time.localtime())


def optional_bool_env(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def optional_int_env(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return int(value)


def parse_task_ids(value: str) -> list[int]:
    task_ids: list[int] = []
    seen: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = [item.strip() for item in part.split("-", 1)]
            if not start_text.isdigit() or not end_text.isdigit():
                raise argparse.ArgumentTypeError(f"Invalid task range: {part!r}")
            start = int(start_text)
            end = int(end_text)
            if start <= 0 or end <= 0 or end < start:
                raise argparse.ArgumentTypeError(f"Invalid task range: {part!r}")
            candidates = range(start, end + 1)
        else:
            if not part.isdigit():
                raise argparse.ArgumentTypeError(f"Invalid task id: {part!r}")
            candidates = [int(part)]
        for task_id in candidates:
            if task_id <= 0:
                raise argparse.ArgumentTypeError("Task ids are 1-based.")
            if task_id not in seen:
                task_ids.append(task_id)
                seen.add(task_id)
    if not task_ids:
        raise argparse.ArgumentTypeError("At least one task id is required.")
    return task_ids


def contains_stop_signal(text: str) -> bool:
    return any(line.strip() == "STOP" for line in str(text).splitlines()) or "STOP" in str(text)


def is_visual_context_request(text: str) -> bool:
    return str(text or "").strip() == VISUAL_CONTEXT_REQUEST


def is_stale_visual_context_rejection(decision: CorrectionDecision) -> bool:
    """Detect correction rejections that contradict already-attached frames."""
    if decision.approved:
        return False
    text = str(decision.reason or "").lower()
    if not text:
        return False
    stale_markers = (
        "no attached frames",
        "no frames are attached",
        "no current frames",
        "no frames or tool results",
        "fresh visual context",
        "need_visual_context",
        "key_frames",
        "key frames",
        "request visual context",
        "visual context before",
    )
    return any(marker in text for marker in stale_markers)


def sanitize_correction_revise(
    decision: CorrectionDecision,
    proposed_calls: list[dict[str, Any]],
) -> CorrectionDecision:
    """Do not let correction directly replace state-changing tool calls."""
    if decision.decision != "REVISE" or not decision.calls:
        return decision
    if any(is_mutation_call(call) for call in proposed_calls + decision.calls):
        return CorrectionDecision(
            decision="REJECT",
            reason=(
                "decision: REJECT\n"
                "error_type: state_change\n"
                "visible_evidence: not audited\n"
                "reason: Correction proposed replacement mutation; mutations must be replanned by the service agent, not auto-rewritten.\n"
                "suggestion: Gather or cite official evidence, then let the service agent emit the correct mutation.\n"
                "replan: Continue without executing replacement_calls."
            ),
            raw_text=decision.raw_text,
            input_tokens=decision.input_tokens,
            output_tokens=decision.output_tokens,
            error=decision.error,
        )
    return decision


def message_likely_needs_visual(text: str) -> bool:
    value = str(text or "")
    if VISUAL_REFERENCE_PATTERN.search(value):
        return True
    return bool(VISUAL_DEICTIC_PATTERN.search(value) and VISUAL_OBJECT_PATTERN.search(value))


def should_attach_frames_for_call(
    args: argparse.Namespace,
    *,
    turn: int,
    latest_user_message: str,
    frames_sent_this_turn: bool,
    force_attach: bool,
) -> bool:
    if force_attach:
        return args.frame_attach_policy != "never"
    if frames_sent_this_turn:
        return False
    # Explicit legacy policies attach frames at most once per user turn.
    if args.frame_attach_policy == "each_turn":
        return True
    if args.frame_attach_policy == "first_turn":
        return turn == 0
    if args.frame_attach_policy == "auto":
        return message_likely_needs_visual(latest_user_message)
    return False


def canonical_tool_call_text(tool_call_obj: Any) -> str:
    calls = tool_call_obj if isinstance(tool_call_obj, list) else [tool_call_obj]
    return json.dumps(calls, ensure_ascii=False)


def format_json_for_feedback(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def extract_tool_calls_from_json(value: Any) -> list[dict[str, Any]]:
    def is_tool_call_dict(item: Any) -> bool:
        return isinstance(item, dict) and any(key in item for key in ("tool_call", "tool_name", "name"))

    if isinstance(value, list):
        return [item for item in value if is_tool_call_dict(item)]
    if not isinstance(value, dict):
        return []
    if is_tool_call_dict(value):
        return [value]
    for key in ("tool_calls", "calls"):
        nested = value.get(key)
        if isinstance(nested, list):
            return [item for item in nested if is_tool_call_dict(item)]
        if is_tool_call_dict(nested):
            return [nested]
    return []


def detect_tool_call(response_text: str, base_check_tool_call: Any) -> tuple[bool, Any]:
    is_tool, tool_call_obj = base_check_tool_call(response_text)
    if is_tool:
        calls = extract_tool_calls_from_json(tool_call_obj)
        return True, calls or tool_call_obj

    text = str(response_text or "")
    decoder = json.JSONDecoder()
    valid_calls: list[dict[str, Any]] = []
    seen: set[str] = set()

    for idx, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        calls = extract_tool_calls_from_json(value)
        for call in calls:
            fingerprint = json.dumps(call, ensure_ascii=False, sort_keys=True, default=str)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            valid_calls.append(call)

    if valid_calls:
        return True, valid_calls
    return False, None


def is_strict_tool_call_response(response_text: str) -> bool:
    text = str(response_text or "").strip()
    if not text:
        return False
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
    except json.JSONDecodeError:
        return False
    if text[end:].strip():
        return False
    return bool(extract_tool_calls_from_json(value))


def is_internal_service_history_message(message: dict[str, Any]) -> bool:
    role = str(message.get("role", ""))
    content = str(message.get("content", "") or "").strip()
    if not content:
        return True
    if role == "user":
        if content.startswith("Internal preflight review") and any(
            marker in content.lower()
            for marker in (
                "unsupported order restaurant_name",
                "unsupported restaurant_name",
            )
        ):
            return False
        return (
            content.startswith("Tool execution result:")
            or content.startswith("Internal preflight review")
        )
    if role == "assistant":
        if is_visual_context_request(content):
            return True
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            return False
        return bool(extract_tool_calls_from_json(value))
    return False


def filtered_dialogue_history(service_history: list[dict[str, Any]]) -> list[dict[str, str]]:
    dialogue: list[dict[str, str]] = []
    for idx, message in enumerate(service_history):
        next_message = service_history[idx + 1] if idx + 1 < len(service_history) else {}
        next_content = str(next_message.get("content", "") or "").strip()
        if str(message.get("role", "")) == "assistant" and (
            next_content.startswith("Internal preflight review")
        ):
            continue
        if is_internal_service_history_message(message):
            continue
        role = str(message.get("role", ""))
        if role not in {"user", "assistant"}:
            continue
        dialogue.append({"role": role, "content": str(message.get("content", "") or "")})
    return dialogue


STATE_CHANGING_TOOL_PREFIXES = (
    "add_",
    "remove_",
    "delete_",
    "update_",
    "set_",
    "clear_",
    "replace_",
)
STATE_CHANGE_REPEAT_INTENT_PATTERN = re.compile(
    r"\b(again|another|additional|extra|more|one more|add more|increase|repeat)\b|"
    r"(再|再次|另一个|更多|追加|加一|多加)",
    re.IGNORECASE,
)


def is_state_changing_tool(tool_name: str) -> bool:
    name = str(tool_name or "").strip().lower()
    return name.startswith(STATE_CHANGING_TOOL_PREFIXES)


def tool_call_fingerprint(call: dict[str, Any]) -> str:
    return json.dumps(
        {
            "tool_name": str(call.get("tool_name") or call.get("name") or "").strip(),
            "parameters": call.get("parameters", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def tool_result_succeeded(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if str(result.get("status", "")).lower() == "error":
        return False
    content = result.get("content")
    if content is None:
        return True
    try:
        parsed = json.loads(str(content))
    except json.JSONDecodeError:
        return "error" not in str(content).lower()
    status = str(parsed.get("status", "")).lower() if isinstance(parsed, dict) else ""
    return status not in {"error", "failed", "failure"}


def successful_state_change_fingerprints(tool_logs: list[dict[str, Any]]) -> set[str]:
    fingerprints: set[str] = set()
    for entry in tool_logs:
        calls = entry.get("calls")
        if not isinstance(calls, list):
            call = entry.get("call")
            calls = [call] if isinstance(call, dict) else []
        results = entry.get("results")
        if not isinstance(results, list):
            result = entry.get("result")
            results = [result] if result is not None else []
        for idx, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            tool_name = call.get("tool_name") or call.get("name") or ""
            if not is_state_changing_tool(str(tool_name)):
                continue
            result = results[idx] if idx < len(results) else {}
            if tool_result_succeeded(result):
                fingerprints.add(tool_call_fingerprint(call))
    return fingerprints


def split_repeated_state_changes(
    proposed_calls: list[dict[str, Any]],
    *,
    prior_tool_logs: list[dict[str, Any]],
    current_tool_logs: list[dict[str, Any]],
    latest_user_message: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if STATE_CHANGE_REPEAT_INTENT_PATTERN.search(str(latest_user_message or "")):
        return proposed_calls, []
    completed = successful_state_change_fingerprints(prior_tool_logs)
    completed.update(successful_state_change_fingerprints(current_tool_logs))
    safe_calls: list[dict[str, Any]] = []
    repeated_calls: list[dict[str, Any]] = []
    for call in proposed_calls:
        tool_name = str(call.get("tool_name") or call.get("name") or "")
        if is_state_changing_tool(tool_name) and tool_call_fingerprint(call) in completed:
            repeated_calls.append(call)
        else:
            safe_calls.append(call)
    return safe_calls, repeated_calls


def concise_text(value: Any, max_chars: int = 500) -> str:
    _ = max_chars
    return str(value)


def load_results(path: str) -> list[dict[str, Any]]:
    result_path = Path(path)
    if not result_path.exists():
        return []
    with open(result_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Existing result file is not a list: {result_path}")
    return data


def save_results(path: str, results: list[dict[str, Any]]) -> None:
    result_path = Path(path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = result_path.with_name(result_path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, result_path)


def is_completed_result(result: dict[str, Any]) -> bool:
    return "task_id" in result and not result.get("error")


def resolve_video_path(video_filename: str) -> Path:
    basename = os.path.basename(str(video_filename))
    candidates = [
        Path(VIDEO_LOCAL_PATH) / basename,
        PROJECT_ROOT / "videos" / basename,
        PROJECT_ROOT / str(video_filename),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Video file not found locally: {video_filename}")


def frame_cache_dir(args: argparse.Namespace, video_path: Path) -> Path:
    scenario_key = f"{args.scenario}{args.scenario_number}"
    rotation_suffix = "" if args.frame_rotation == "none" else f"_rot-{args.frame_rotation}"
    return Path(args.frame_cache_dir) / scenario_key / f"{video_path.stem}{rotation_suffix}"


def prepare_frames(args: argparse.Namespace, video_path: Path) -> list[SampledFrame]:
    return sample_video_frames(
        video_path,
        frame_cache_dir(args, video_path),
        fps=args.frame_fps,
        max_side=args.frame_max_side,
        jpeg_quality=args.jpeg_quality,
        max_frames=args.max_frames,
        rotation=args.frame_rotation,
        refresh=args.refresh_frames,
    )


def configure_user_model_env(args: argparse.Namespace) -> None:
    os.environ["USER_MODEL_NAME"] = args.user_model_name
    os.environ["USER_API_KEY"] = args.user_api_key or ""
    os.environ["USER_API_BASE_URL"] = args.user_api_base_url or ""
    # Legacy aliases for older official helper code paths.
    os.environ["API_KEY"] = args.user_api_key or ""
    os.environ["LLM_API_BASE_URL"] = args.user_api_base_url or ""
    os.environ["USER_TEMPERATURE"] = str(args.user_temperature)
    if args.user_enable_thinking is not None:
        os.environ["USER_ENABLE_THINKING"] = "true" if args.user_enable_thinking else "false"
    else:
        os.environ.pop("USER_ENABLE_THINKING", None)
    if args.user_thinking_budget is not None:
        os.environ["USER_THINKING_BUDGET"] = str(args.user_thinking_budget)
    else:
        os.environ.pop("USER_THINKING_BUDGET", None)
    if args.user_preserve_thinking is not None:
        os.environ["USER_PRESERVE_THINKING"] = "true" if args.user_preserve_thinking else "false"
    else:
        os.environ.pop("USER_PRESERVE_THINKING", None)
    print(
        "👤 [User Model] "
        f"model={args.user_model_name}, "
        f"base_url={args.user_api_base_url or '[unset]'}, "
        f"temperature={args.user_temperature}, "
        f"enable_thinking={args.user_enable_thinking}, "
        f"thinking_budget={args.user_thinking_budget}, "
        f"preserve_thinking={args.user_preserve_thinking}"
    )


def text_content(text: str, *, role: str = "user") -> list[dict[str, str]]:
    content_type = "output_text" if role == "assistant" else "input_text"
    return [{"type": content_type, "text": text}]


def frame_content(
    frames: list[SampledFrame],
    image_detail: str,
    *,
    header: str | None = None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": header
            or (
                "The following images are uniformly sampled frames from the task video. "
                "They are in chronological order and each image is preceded by its frame id and timestamp."
            ),
        }
    ]
    for frame in frames:
        content.append({"type": "input_text", "text": f"{frame.frame_id}: timestamp={frame.timestamp:.2f}s"})
        content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(frame.path),
                "detail": image_detail,
            }
        )
    return content


def response_input_items(
    service_history: list[dict[str, str]],
    *,
    frames: list[SampledFrame],
    attach_frames: bool,
    image_detail: str,
    frame_header: str | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    last_user_index = -1
    for idx, message in enumerate(service_history):
        if message.get("role") == "user":
            last_user_index = idx

    for idx, message in enumerate(service_history):
        role = message.get("role", "user")
        content = text_content(str(message.get("content", "")), role=role)
        if attach_frames and idx == last_user_index:
            content.extend(frame_content(frames, image_detail, header=frame_header))
        items.append({"role": role, "content": content})
    return items


def parse_key_frames_from_reply(
    reply: str,
    all_frames: list[SampledFrame],
    max_frames: int = 3,
) -> list[SampledFrame]:
    if not reply or not all_frames:
        return []

    frame_indices: dict[str, int] = {frame.frame_id: idx for idx, frame in enumerate(all_frames)}
    timestamps = [frame.timestamp for frame in all_frames]

    def closest_index_by_time(ts: float) -> int:
        return min(range(len(all_frames)), key=lambda idx: abs(timestamps[idx] - ts))

    def contiguous_window(center_idx: int, window: int = 3) -> list[SampledFrame]:
        if not all_frames or window <= 0:
            return []
        half = window // 2
        start = max(0, center_idx - half)
        end = min(len(all_frames), start + window)
        if end - start < window:
            start = max(0, end - window)
        return all_frames[start:end]

    reply_text = str(reply)
    # Prefer explicit KEY_FRAMES format first, then bare frame ids, then time points.
    frame_id_candidates: list[int] = []

    key_frames_block = ""
    key_match = re.search(r"KEY_FRAMES\s*:\s*\[([^\]]*)\]", reply_text, re.IGNORECASE)
    if key_match:
        key_frames_block = key_match.group(1)
    if key_frames_block:
        for match in re.finditer(r"\bF\d{3}\b", key_frames_block):
            fid = match.group(0)
            if fid in frame_indices:
                frame_id_candidates.append(frame_indices[fid])

    if not frame_id_candidates:
        for match in re.finditer(r"\bF\d{3}\b", reply_text):
            fid = match.group(0)
            if fid in frame_indices:
                frame_id_candidates.append(frame_indices[fid])

    if frame_id_candidates:
        # Keep order, remove duplicates.
        frame_id_candidates = sorted(dict.fromkeys(frame_id_candidates))
        # 1) prefer an explicit consecutive triple in provided IDs.
        for start_idx in range(len(frame_id_candidates)):
            candidate = frame_id_candidates[start_idx : start_idx + max_frames]
            if len(candidate) < max_frames:
                break
            if all(candidate[i + 1] - candidate[i] == 1 for i in range(max_frames - 1)):
                return [all_frames[idx] for idx in candidate]

        return []

    # Fallback only from explicit time block, e.g. KEY_FRAME_TIMES: [3.2,4.8,5.6].
    numeric_candidates: list[float] = []
    time_block_match = re.search(r"KEY_FRAME_TIMES?\s*:\s*\[([^\]]*)\]", reply_text, flags=re.IGNORECASE)
    if time_block_match:
        for match in re.finditer(r"(-?\d+(?:\.\d+)?)", time_block_match.group(1)):
            try:
                numeric_candidates.append(float(match.group(0)))
            except ValueError:
                continue

    if numeric_candidates:
        center = closest_index_by_time(float(numeric_candidates[0]))
        return contiguous_window(center, window=max_frames)

    return []


def call_service_model(
    client: OpenAIResponsesServiceClient,
    *,
    instructions: str,
    service_history: list[dict[str, str]],
    frames: list[SampledFrame],
    attach_frames: bool,
    image_detail: str,
    frame_header: str | None = None,
) -> tuple[str, int, int]:
    result = client.create(
        instructions=instructions,
        input_items=response_input_items(
            service_history,
            frames=frames,
            attach_frames=attach_frames,
            image_detail=image_detail,
            frame_header=frame_header,
        ),
    )
    return result.text, result.input_tokens, result.output_tokens


def call_user_llm_for_runner(
    messages: list[dict[str, Any]],
    *,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
    temperature: float | None,
    enable_thinking: bool | None,
    thinking_budget: int | None,
    preserve_thinking: bool | None,
    max_retries: int = 3,
    base_delay: float = 10.0,
) -> tuple[str, int, int]:
    from openai import OpenAI

    extra_body: dict[str, Any] = {}
    if enable_thinking is not None:
        extra_body["enable_thinking"] = enable_thinking
    if thinking_budget is not None:
        extra_body["thinking_budget"] = thinking_budget
    if preserve_thinking is not None:
        extra_body["preserve_thinking"] = preserve_thinking

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            client = OpenAI(api_key=api_key or "", base_url=base_url or None)
            kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if extra_body:
                kwargs["extra_body"] = extra_body
            completion = client.chat.completions.create(**kwargs)
            content = completion.choices[0].message.content or ""
            input_tokens = 0
            output_tokens = 0
            if getattr(completion, "usage", None):
                input_tokens = getattr(completion.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(completion.usage, "completion_tokens", 0) or 0
            return content, input_tokens, output_tokens
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                wait_time = (base_delay * (2**attempt)) + random.uniform(0, 1)
                print(
                    f"[User Model Retry] Attempt {attempt + 1}/{max_retries} failed: "
                    f"{exc}. Retrying in {wait_time:.2f}s..."
                )
                time.sleep(wait_time)
            else:
                print(f"[User Model Error] Failed after {max_retries} attempts: {exc}")
    return f"Error: {last_error}", 0, 0


def run_simulation(input_path: str, tool_info_path: str, output_path: str, args: argparse.Namespace) -> None:
    configure_user_model_env(args)
    import run.utils as run_utils

    check_tool_call = run_utils.check_tool_call
    execute_tool = run_utils.execute_tool
    official_check_user_contradiction = run_utils.check_user_contradiction

    def call_llm(
        messages: list[dict[str, Any]],
        agent_type: str = "service",
        service_model_name: str | None = None,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
        preserve_thinking: bool | None = None,
    ) -> tuple[str, int, int]:
        if agent_type != "user":
            return run_utils.call_llm(
                messages,
                agent_type=agent_type,
                service_model_name=service_model_name or args.service_model_name,
                enable_thinking=bool(enable_thinking),
            )
        return call_user_llm_for_runner(
            messages,
            model_name=args.user_model_name,
            api_key=args.user_api_key,
            base_url=args.user_api_base_url,
            temperature=args.user_temperature if temperature is None else temperature,
            enable_thinking=args.user_enable_thinking if enable_thinking is None else enable_thinking,
            thinking_budget=args.user_thinking_budget if thinking_budget is None else thinking_budget,
            preserve_thinking=args.user_preserve_thinking if preserve_thinking is None else preserve_thinking,
        )

    def check_user_contradiction(**kwargs: Any) -> tuple[str, Any]:
        kwargs.pop("user_temperature", None)
        kwargs.pop("user_enable_thinking", None)
        kwargs.pop("user_thinking_budget", None)
        kwargs.pop("user_preserve_thinking", None)
        return official_check_user_contradiction(**kwargs)

    run_utils.call_llm = call_llm

    with open(tool_info_path, "r", encoding="utf-8") as f:
        tools_list = json.load(f)
    tool_descriptions = json.dumps(tools_list, indent=2, ensure_ascii=False)

    with open(input_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    if args.task_ids:
        selected = []
        for task_id in args.task_ids:
            if task_id > len(scenarios):
                raise ValueError(f"Task id {task_id} is out of range; only {len(scenarios)} tasks are available.")
            selected.append((task_id, scenarios[task_id - 1]))
    else:
        if args.num_tasks > 0:
            scenarios = scenarios[: args.num_tasks]
        selected = list(enumerate(scenarios, start=1))

    service_client = OpenAIResponsesServiceClient(
        model=args.service_model_name,
        api_key=args.service_api_key,
        base_url=args.service_api_base_url,
        max_output_tokens=args.service_max_output_tokens,
        temperature=args.service_temperature,
        reasoning_effort=args.service_reasoning_effort,
        timeout=args.service_timeout,
        max_retries=args.service_max_retries,
        retry_base_delay=args.service_retry_base_delay,
        retry_max_delay=args.service_retry_max_delay,
        retry_after_cap=args.service_retry_after_cap,
        log_request_size=args.log_service_payload_size,
        payload_warn_mb=args.service_payload_warn_mb,
    )
    print(
        "🤖 [Service Model] "
        f"model={args.service_model_name}, "
        f"base_url={args.service_api_base_url or '[default]'}, "
        f"temperature={args.service_temperature}, "
        f"reasoning_effort={args.service_reasoning_effort}"
    )
    correction_client = None
    correction_system_prompt = build_correction_system_prompt(
        scenario=args.scenario,
        scenario_number=args.scenario_number,
    )
    correction_log_file = PROJECT_ROOT / correction_log_path(output_path)
    if args.enable_correction_agent:
        if args.correction_api_type == "responses":
            correction_client = ResponsesCorrectionClient(
                model=args.correction_model_name,
                api_key=args.correction_api_key,
                base_url=args.correction_api_base_url,
                max_tokens=args.correction_max_output_tokens,
                temperature=args.correction_temperature,
                reasoning_effort=args.correction_reasoning_effort,
                timeout=args.correction_timeout,
                max_retries=args.correction_max_retries,
                retry_base_delay=args.correction_retry_base_delay,
                retry_max_delay=args.correction_retry_max_delay,
                retry_after_cap=args.correction_retry_after_cap,
            )
        else:
            correction_client = ChatCompletionsCorrectionClient(
                model=args.correction_model_name,
                api_key=args.correction_api_key,
                base_url=args.correction_api_base_url,
                max_tokens=args.correction_max_output_tokens,
                temperature=args.correction_temperature,
                timeout=args.correction_timeout,
                max_retries=args.correction_max_retries,
                retry_base_delay=args.correction_retry_base_delay,
                retry_max_delay=args.correction_retry_max_delay,
                retry_after_cap=args.correction_retry_after_cap,
                thinking=args.correction_thinking,
                reasoning_effort=args.correction_reasoning_effort,
            )
        print(
            "🧭 [Correction Agent] "
            f"api_type={args.correction_api_type}, "
            f"model={args.correction_model_name}, "
            f"base_url={args.correction_api_base_url or '[default]'}, "
            f"scenario={args.scenario}{args.scenario_number}, "
            f"temperature={args.correction_temperature}, "
            f"reasoning_effort={args.correction_reasoning_effort}"
        )

    all_results: list[dict[str, Any]] = load_results(output_path) if args.resume else []
    completed_task_ids = {int(result["task_id"]) for result in all_results if is_completed_result(result)}
    if args.resume:
        print(f"🔄 [Resume] Loaded {len(all_results)} existing result records from {output_path}")
        if completed_task_ids:
            print(f"🔄 [Resume] Skipping completed task ids: {sorted(completed_task_ids)}")

    for task_id, sc in selected:
        if task_id in completed_task_ids:
            continue
        print(f"\n🚀 {'=' * 20} GPT Frame Scenario {args.scenario}{args.scenario_number}: {task_id} {'=' * 20}")
        db = init_db(args.scenario, args.scenario_number)
        user_instruction = sc.get("Instruction", "")
        image_description = sc.get("image_description", "")
        video_path = resolve_video_path(sc.get("image_path", ""))
        frames = prepare_frames(args, video_path)
        print(f"🖼️ [Frames] {len(frames)} frames sampled from {video_path}")

        start_time = time.time()
        history_log: dict[str, Any] = {
            "task_id": task_id,
            "mode": "text",
            "instruction": user_instruction,
            "image_description": image_description,
            "dialogue": [],
            "tool_calls": [],
            "rounds_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls_count": 0,
            "user_response_time_seconds": 0.0,
            "agent_response_time_seconds": 0.0,
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time)),
            "service_prompt_version": SERVICE_PROMPT_VERSION,
            "user_model_config": {
                "model": args.user_model_name,
                "temperature": args.user_temperature,
                "enable_thinking": args.user_enable_thinking,
                "thinking_budget": args.user_thinking_budget,
                "preserve_thinking": args.user_preserve_thinking,
            },
            "frame_input": {
                "video_path": str(video_path),
                "frame_fps": args.frame_fps,
                "frame_max_side": args.frame_max_side,
                "frame_rotation": args.frame_rotation,
                "image_detail": args.image_detail,
                "frames_each_turn": bool(args.frames_each_turn),
                "frame_attach_policy": args.frame_attach_policy,
                "frames": frame_metadata(frames),
            },
                "frame_attached_calls": 0,
                "visual_context_requests": 0,
            }
        if args.enable_correction_agent:
            history_log["correction_agent"] = {
                "enabled": True,
                "model": args.correction_model_name,
                "max_rounds": args.max_correction_rounds,
                "scenario": f"{args.scenario}{args.scenario_number}",
            }

        user_agent_sys_prompt = USER_TEXT_ONLY_PROMPT_EASY.format(
            user_instruction=user_instruction,
            image_description=image_description,
            original_user_response="",
            evaluation_feedback="",
            history_summary="",
            service_agent_response="Dear customer, how can I help you?",
        )
        user_messages = [
            {"role": "system", "content": user_agent_sys_prompt},
            {
                "role": "user",
                "content": (
                    "You are a customer in the environment shown in the video, and you need to complete "
                    "the instructions in **Task**. I am your AI customer service representative; please "
                    "interact with me in the first person. Let's begin the conversation.\n"
                    "Dear customer, how can I help you?"
                ),
            },
        ]

        service_agent_sys_prompt = build_service_agent_prompt(
            tool_descriptions=tool_descriptions,
            scenario=args.scenario,
            scenario_number=args.scenario_number,
        )
        service_history: list[dict[str, str]] = []
        rounds_count = 0
        input_tokens_total = 0
        output_tokens_total = 0
        tool_calls_count = 0
        accumulated_original_scores: dict[str, float] = {}
        accumulated_final_scores: dict[str, float] = {}
        scenario_original_scores: dict[str, float] = {}
        scenario_corrected_scores: dict[str, float] = {}
        valid_evaluation_count = 0
        last_agent_response_for_check = "Dear customer, how can I help you?"
        summarized_history_str = ""
        executor = None
        task_error: Exception | None = None

        for turn in range(args.max_turns):
            user_start_time = time.time()
            user_reply, user_input_tok, user_output_tok = call_llm(
                user_messages,
                agent_type="user",
                service_model_name=args.user_model_name,
                temperature=args.user_temperature,
                enable_thinking=args.user_enable_thinking,
                thinking_budget=args.user_thinking_budget,
                preserve_thinking=args.user_preserve_thinking,
            )
            user_gen_time = time.time() - user_start_time
            history_log["user_response_time_seconds"] += user_gen_time
            print(f"⏱️ [Time] User response generation (Turn {turn}): {user_gen_time:.3f} seconds")

            evaluation_info = None
            check_start_time = time.time()
            if args.multi_agent_user:
                original_user_reply = user_reply
                user_reply, evaluation_info = check_user_contradiction(
                    user_response=original_user_reply,
                    user_instruction=user_instruction,
                    image_description=image_description,
                    multi_agent_user=True,
                    last_agent_response=last_agent_response_for_check,
                    history=history_log["dialogue"],
                    summarized_history=summarized_history_str if args.summary_user else None,
                    user_mode="easy",
                    user_temperature=args.user_temperature,
                    user_enable_thinking=args.user_enable_thinking,
                    user_thinking_budget=args.user_thinking_budget,
                    user_preserve_thinking=args.user_preserve_thinking,
                )
                if evaluation_info and "scores" in evaluation_info:
                    valid_evaluation_count += 1
                    original_scores = evaluation_info["scores"]
                    final_scores = evaluation_info.get("corrected_scores", original_scores)
                    for key, value in original_scores.items():
                        try:
                            numeric_value = float(value)
                            accumulated_original_scores[key] = accumulated_original_scores.get(key, 0.0) + numeric_value
                            scenario_original_scores[key] = min(
                                scenario_original_scores.get(key, numeric_value),
                                numeric_value,
                            )
                        except ValueError:
                            pass
                    for key, value in final_scores.items():
                        try:
                            numeric_value = float(value)
                            accumulated_final_scores[key] = accumulated_final_scores.get(key, 0.0) + numeric_value
                            scenario_corrected_scores[key] = min(
                                scenario_corrected_scores.get(key, numeric_value),
                                numeric_value,
                            )
                        except ValueError:
                            pass
                check_time = time.time() - check_start_time
                history_log["user_response_time_seconds"] += check_time
                print(f"⏱️ [Time] Check phase (Turn {turn}): {check_time:.3f} seconds")

            print(f"👤 Final User Response: {user_reply}")
            log_entry = {"role": "user", "turn": turn, "content": user_reply}
            if evaluation_info:
                log_entry["evaluation"] = evaluation_info
            history_log["dialogue"].append(log_entry)
            if contains_stop_signal(str(user_reply)):
                print("🛑 Stop signal detected")
                break

            service_history.append({"role": "user", "content": str(user_reply)})
            user_messages.append({"role": "assistant", "content": str(user_reply)})

            current_user_reply = str(user_reply)
            current_service_history = [dict(msg) for msg in service_history]
            current_summary = summarized_history_str

            def generate_summary_task(agent_response_for_summary: str) -> str | None:
                if not args.summary_user:
                    return None
                summary_start = time.time()
                prompt = USER_TURN_SUMMARY_PROMPT.format(
                    user_instruction=user_instruction,
                    agent_response=agent_response_for_summary,
                    user_response=current_user_reply,
                    previous_summary=current_summary if current_summary else "None",
                )
                print(f"🧾 Generating dialogue summary (Turn {turn})...")
                summary, _, _ = call_llm(
                    [{"role": "user", "content": prompt}],
                    agent_type="user",
                    service_model_name=args.user_model_name,
                    temperature=args.user_temperature,
                    enable_thinking=args.user_enable_thinking,
                    thinking_budget=args.user_thinking_budget,
                    preserve_thinking=args.user_preserve_thinking,
                )
                summary_time = time.time() - summary_start
                print(f"⏱️ [Time] Summary generation (Turn {turn}): {summary_time:.3f} seconds")
                print(f"🧾 Turn {turn} Summary: {summary}")
                return str(summary)

            def process_agent_task() -> dict[str, Any]:
                agent_start = time.time()
                inner_input_tokens = 0
                inner_output_tokens = 0
                inner_calls = 0
                inner_rounds = 0
                agent_final_reply = ""
                local_tool_logs = []
                local_dialogue_logs = []
                local_correction_logs = []
                local_service_history = [dict(msg) for msg in current_service_history]
                latest_correction_frames: list[SampledFrame] = []
                total_tool_calls_so_far = tool_calls_count
                frames_sent_this_turn = False
                force_attach_frames = False
                frame_attached_calls = 0
                visual_context_requests = 0
                visual_context_recovery_attempts = 0
                correction_rounds = 0
                correction_input_tokens = 0
                correction_output_tokens = 0

                def log_correction(record: dict[str, Any]) -> None:
                    local_correction_logs.append(record)
                    write_correction_log(correction_log_file, record)

                def review_feedback(
                    decision: CorrectionDecision,
                    *,
                    proposed_kind: str,
                    rejected_output: Any,
                ) -> str:
                    call_hint = ""
                    if decision.calls:
                        call_hint = "\nSuggested official tool calls for replanning:\n" + canonical_tool_call_text(decision.calls)
                    feedback = compact_decision_feedback(decision)
                    return (
                        f"Internal preflight review for your previous {proposed_kind}: {decision.decision}\n"
                        "Rejected proposed output:\n"
                        f"{format_json_for_feedback(rejected_output)}\n"
                        "Review summary:\n"
                        f"{format_json_for_feedback(feedback)}\n"
                        "Your previous proposed output was not executed or shown to the user. "
                        "Treat this as an explicit failed audit of the exact proposed output above. "
                        "Continue from the current turn context and currently accumulated tool results. "
                        "If more database evidence is needed, output official tool calls in the required JSON format; "
                        "If enough evidence exists, answer the user directly. "
                        "Do not output NEED_VISUAL_CONTEXT in response to this review; if frames were already used, "
                        "continue from your prior visual hypothesis and verify it with official tools. "
                        "Do not repeat the same rejected output unless the "
                        "review reason explicitly says only formatting was wrong. "
                        "Do not claim rejected tool calls were executed."
                        f"{call_hint}"
                    )

                def maybe_review_tool_batch(proposed_calls: list[dict[str, Any]]) -> CorrectionDecision:
                    if not args.enable_correction_agent or correction_client is None:
                        return CorrectionDecision(decision="APPROVE", reason="Correction agent disabled.")
                    if args.correction_auto_approve_read_only:
                        deterministic_approval = deterministic_batch_approval(proposed_calls)
                        if deterministic_approval:
                            return CorrectionDecision(decision="APPROVE", reason=deterministic_approval)
                    deterministic_feedback = deterministic_batch_feedback(proposed_calls)
                    if deterministic_feedback:
                        return CorrectionDecision(decision="REJECT", reason=deterministic_feedback)
                    audit_context = build_audit_context(
                        scenario=args.scenario,
                        scenario_number=args.scenario_number,
                        task_id=task_id,
                        turn=turn,
                        latest_user_message=current_user_reply,
                        summarized_history="",
                        service_history=filtered_dialogue_history(local_service_history),
                        service_prompt=service_agent_sys_prompt,
                        tool_catalog=tools_list,
                        key_frames=[],
                        service_frames_attached=frames_sent_this_turn,
                        tool_logs=local_tool_logs,
                        prior_tool_logs=history_log["tool_calls"],
                        proposed=proposed_calls,
                        proposed_kind="tool_calls",
                        max_tool_log_entries=args.correction_max_tool_log_entries,
                        max_tool_result_chars=args.correction_max_tool_result_chars,
                        max_audit_context_chars=args.correction_max_audit_context_chars,
                    )
                    try:
                        decision = review_with_agent(
                            correction_client,
                            system_prompt=correction_system_prompt,
                            audit_context=audit_context,
                        )
                        decision.audit_context_stats = audit_context_stats(audit_context)  # type: ignore[attr-defined]
                        return sanitize_correction_revise(decision, proposed_calls)
                    except Exception as exc:
                        return failure_decision(exc, failure_policy=args.correction_failure_policy)

                def maybe_review_reply(proposed_reply: str) -> CorrectionDecision:
                    if not args.enable_correction_agent or correction_client is None:
                        return CorrectionDecision(decision="APPROVE", reason="Correction agent disabled.")
                    deterministic_feedback = deterministic_reply_feedback(
                        proposed_reply,
                        history_log["tool_calls"] + local_tool_logs,
                    )
                    if deterministic_feedback:
                        return CorrectionDecision(decision="REJECT", reason=deterministic_feedback)
                    audit_context = build_audit_context(
                        scenario=args.scenario,
                        scenario_number=args.scenario_number,
                        task_id=task_id,
                        turn=turn,
                        latest_user_message=current_user_reply,
                        summarized_history="",
                        service_history=filtered_dialogue_history(local_service_history),
                        service_prompt=service_agent_sys_prompt,
                        tool_catalog=tools_list,
                        key_frames=[],
                        service_frames_attached=frames_sent_this_turn,
                        tool_logs=local_tool_logs,
                        prior_tool_logs=history_log["tool_calls"],
                        proposed=proposed_reply,
                        proposed_kind="final_reply",
                        max_tool_log_entries=args.correction_max_tool_log_entries,
                        max_tool_result_chars=args.correction_max_tool_result_chars,
                        max_audit_context_chars=args.correction_max_audit_context_chars,
                    )
                    try:
                        decision = review_with_agent(
                            correction_client,
                            system_prompt=correction_system_prompt,
                            audit_context=audit_context,
                        )
                        decision.audit_context_stats = audit_context_stats(audit_context)  # type: ignore[attr-defined]
                        if frames_sent_this_turn and is_stale_visual_context_rejection(decision):
                            return CorrectionDecision(
                                decision="APPROVE",
                                reason=(
                                    "Correction rejection ignored: service already received frames this turn; "
                                    "visual recognition/key-frame availability is outside correction scope."
                                ),
                                input_tokens=decision.input_tokens,
                                output_tokens=decision.output_tokens,
                                raw_text=decision.raw_text,
                            )
                        return decision
                    except Exception as exc:
                        return failure_decision(exc, failure_policy=args.correction_failure_policy)

                def finalize_after_inner_tool_limit() -> None:
                    nonlocal inner_input_tokens
                    nonlocal inner_output_tokens
                    nonlocal correction_input_tokens
                    nonlocal correction_output_tokens
                    nonlocal correction_rounds
                    nonlocal inner_rounds
                    nonlocal agent_final_reply

                    local_service_history.append(
                        {
                            "role": "user",
                            "content": (
                                "Internal budget note: the tool-round budget for this user turn is exhausted. "
                                "Do not call more tools. Do not output NEED_VISUAL_CONTEXT. Produce one concise "
                                "user-visible final reply using only the dialogue, visual hypotheses, and tool "
                                "results already available. If the evidence is incomplete, state the limitation "
                                "briefly and answer only what is supported."
                            ),
                        }
                    )
                    agent_reply, agent_input_tokens, agent_output_tokens = call_service_model(
                        service_client,
                        instructions=service_agent_sys_prompt,
                        service_history=local_service_history,
                        frames=frames,
                        attach_frames=False,
                        image_detail=args.image_detail,
                        frame_header=None,
                    )
                    inner_input_tokens += agent_input_tokens
                    inner_output_tokens += agent_output_tokens
                    agent_reply = str(agent_reply or "[Empty model response]")
                    print(f"🤖 Tested Agent Finalize: {agent_reply}")

                    is_tool, _tool_call_obj = detect_tool_call(agent_reply, check_tool_call)
                    if is_visual_context_request(agent_reply) or is_tool:
                        fallback_reply = (
                            "I could not complete the request within the internal tool-round budget. "
                            "The available tool evidence is incomplete, so I cannot give a reliable final answer."
                        )
                        print(f"💬 Tested Agent Reply: {concise_text(fallback_reply)}")
                        inner_rounds += 1
                        local_dialogue_logs.append({"role": "agent", "turn": turn, "content": fallback_reply})
                        local_service_history.append({"role": "assistant", "content": fallback_reply})
                        agent_final_reply = fallback_reply
                        return

                    decision = maybe_review_reply(agent_reply)
                    correction_input_tokens += decision.input_tokens
                    correction_output_tokens += decision.output_tokens
                    if args.enable_correction_agent:
                        record = {
                            "task_id": task_id,
                            "turn": turn,
                            "stage": "reply",
                            "proposed": agent_reply,
                            "decision": decision.decision,
                            "reason": decision.reason,
                            "input_tokens": decision.input_tokens,
                            "output_tokens": decision.output_tokens,
                            "audit_context": getattr(decision, "audit_context_stats", None),
                            "error": decision.error,
                            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        }
                        log_correction(record)
                        context_note = ""
                        context_stats = getattr(decision, "audit_context_stats", None)
                        if context_stats:
                            context_note = (
                                f" context_chars={context_stats.get('chars')} "
                                f"context_truncated={context_stats.get('context_truncated')}"
                            )
                        print(
                            f"🧭 [Correction] Finalize reply decision={decision.decision}: "
                            f"{format_json_for_feedback(compact_decision_feedback(decision))}{context_note}"
                        )
                    if not decision.approved:
                        if correction_rounds >= args.max_correction_rounds:
                            if args.correction_on_max_reply_rounds == "stop":
                                agent_final_reply = "[Interaction stopped: correction rounds exceeded]"
                                return
                            print("⚠️ [Correction] Max reply rounds exceeded; accepting finalize reply.")
                        else:
                            correction_rounds += 1
                            feedback = review_feedback(
                                decision,
                                proposed_kind="reply",
                                rejected_output=agent_reply,
                            )
                            local_service_history.append({"role": "assistant", "content": agent_reply})
                            local_service_history.append({"role": "user", "content": feedback})
                            fallback_reply = (
                                "I could not complete the request within the internal tool-round budget. "
                                "The available tool evidence is incomplete, so I cannot give a reliable final answer."
                            )
                            print(f"💬 Tested Agent Reply: {concise_text(fallback_reply)}")
                            inner_rounds += 1
                            local_dialogue_logs.append({"role": "agent", "turn": turn, "content": fallback_reply})
                            local_service_history.append({"role": "assistant", "content": fallback_reply})
                            agent_final_reply = fallback_reply
                            return

                    print(f"💬 Tested Agent Reply: {concise_text(agent_reply)}")
                    inner_rounds += 1
                    local_dialogue_logs.append({"role": "agent", "turn": turn, "content": agent_reply})
                    local_service_history.append({"role": "assistant", "content": agent_reply})
                    agent_final_reply = agent_reply

                for _ in range(args.max_inner_tool_rounds):
                    attach_frames = should_attach_frames_for_call(
                        args,
                        turn=turn,
                        latest_user_message=current_user_reply,
                        frames_sent_this_turn=frames_sent_this_turn,
                        force_attach=force_attach_frames,
                    )
                    frames_for_call = frames
                    frame_header = None
                    if attach_frames:
                        frame_header = (
                            "VISUAL CONTEXT IS ATTACHED TO THIS MESSAGE. "
                            "Do not output NEED_VISUAL_CONTEXT. Inspect the chronological frames, "
                            "identify the visual referent as best as possible, then call official "
                            "read-only tools if database evidence is needed."
                        )
                    force_attach_frames = False
                    agent_reply, agent_input_tokens, agent_output_tokens = call_service_model(
                        service_client,
                        instructions=service_agent_sys_prompt,
                        service_history=local_service_history,
                        frames=frames_for_call,
                        attach_frames=attach_frames,
                        image_detail=args.image_detail,
                        frame_header=frame_header,
                    )
                    frames_sent_this_turn = frames_sent_this_turn or attach_frames
                    if attach_frames:
                        frame_attached_calls += 1
                    inner_input_tokens += agent_input_tokens
                    inner_output_tokens += agent_output_tokens
                    agent_reply = str(agent_reply or "[Empty model response]")
                    print(f"🤖 Tested Agent: {agent_reply}")

                    if is_visual_context_request(agent_reply):
                        visual_context_requests += 1
                        if attach_frames:
                            if visual_context_recovery_attempts < 1:
                                visual_context_recovery_attempts += 1
                                local_service_history.append({"role": "assistant", "content": agent_reply})
                                local_service_history.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "Internal routing note: your previous response requested visual context "
                                            "even though frames were attached. The next retry will attach the frames "
                                            "again. Do not output NEED_VISUAL_CONTEXT. Inspect the frames, identify "
                                            "the visual referent as best as possible, and call official read-only "
                                            "tools if database evidence is needed."
                                        ),
                                    }
                                )
                                force_attach_frames = True
                                print(
                                    "🖼️ [Frames] Visual context was already attached; "
                                    "retrying once with a stricter frame instruction."
                                )
                                continue
                            agent_final_reply = "[Interaction stopped: visual context requested despite attached frames]"
                            break
                        if args.frame_attach_policy != "never" and visual_context_requests <= args.max_visual_context_requests:
                            force_attach_frames = True
                            print("🖼️ [Frames] Service agent requested visual context; retrying this turn with frames.")
                            continue
                        agent_final_reply = "[Interaction stopped: visual context request repeated]"
                        break

                    is_tool, tool_call_obj = detect_tool_call(agent_reply, check_tool_call)
                    if attach_frames:
                        parsed_correction_frames = parse_key_frames_from_reply(
                            agent_reply,
                            frames,
                            max_frames=3,
                        )
                        if parsed_correction_frames:
                            latest_correction_frames = parsed_correction_frames
                            print(
                                f"🖼️ [Service Key Frames] {[f.frame_id for f in latest_correction_frames]} "
                                "not sent to correction"
                            )
                        else:
                            latest_correction_frames = []
                            print("🖼️ [Service Key Frames] none provided by service agent")
                    else:
                        latest_correction_frames = []
                    if not is_tool:
                        latest_correction_frames = []
                        decision = maybe_review_reply(agent_reply)
                        correction_input_tokens += decision.input_tokens
                        correction_output_tokens += decision.output_tokens
                        if args.enable_correction_agent:
                            record = {
                                "task_id": task_id,
                                "turn": turn,
                                "stage": "reply",
                                "proposed": agent_reply,
                                "decision": decision.decision,
                                "reason": decision.reason,
                                "input_tokens": decision.input_tokens,
                                "output_tokens": decision.output_tokens,
                                "audit_context": getattr(decision, "audit_context_stats", None),
                                "error": decision.error,
                                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                            }
                            log_correction(record)
                            context_note = ""
                            context_stats = getattr(decision, "audit_context_stats", None)
                            if context_stats:
                                context_note = (
                                    f" context_chars={context_stats.get('chars')} "
                                    f"context_truncated={context_stats.get('context_truncated')}"
                                )
                            print(
                                f"🧭 [Correction] Reply decision={decision.decision}: "
                                f"{format_json_for_feedback(compact_decision_feedback(decision))}{context_note}"
                            )
                        if not decision.approved:
                            if correction_rounds >= args.max_correction_rounds:
                                if args.correction_on_max_reply_rounds == "stop":
                                    agent_final_reply = "[Interaction stopped: correction rounds exceeded]"
                                    break
                                print("⚠️ [Correction] Max reply rounds exceeded; accepting proposed reply.")
                            else:
                                correction_rounds += 1
                                feedback = review_feedback(
                                    decision,
                                    proposed_kind="reply",
                                    rejected_output=agent_reply,
                                )
                                local_service_history.append({"role": "assistant", "content": agent_reply})
                                local_service_history.append({"role": "user", "content": feedback})
                                force_attach_frames = False
                                continue
                        print(f"💬 Tested Agent Reply: {concise_text(agent_reply)}")
                        inner_rounds += 1
                        local_dialogue_logs.append({"role": "agent", "turn": turn, "content": agent_reply})
                        local_service_history.append({"role": "assistant", "content": agent_reply})
                        agent_final_reply = agent_reply
                        break

                    proposed_calls = normalize_calls(tool_call_obj)
                    if not is_strict_tool_call_response(agent_reply):
                        decision = CorrectionDecision(
                            decision="REJECT",
                            reason=(
                                "decision: REJECT\n"
                                "error_type: tool_schema\n"
                                "visible_evidence: not evaluated; the output mixed a tool call with extra text.\n"
                                "reason: Tool-call messages must be exactly one JSON value with no prose before or after it.\n"
                                "suggestion: Re-emit only the JSON tool call now, then answer after the tool result.\n"
                                "replan: Output the same intended tool call as strict JSON only."
                            ),
                        )
                    else:
                        decision = maybe_review_tool_batch(proposed_calls)
                    correction_input_tokens += decision.input_tokens
                    correction_output_tokens += decision.output_tokens
                    if args.enable_correction_agent:
                        record = {
                            "task_id": task_id,
                            "turn": turn,
                            "stage": "tool_calls",
                            "proposed": proposed_calls,
                            "decision": decision.decision,
                            "reason": decision.reason,
                            "replacement_calls": decision.calls,
                            "input_tokens": decision.input_tokens,
                            "output_tokens": decision.output_tokens,
                            "audit_context": getattr(decision, "audit_context_stats", None),
                            "error": decision.error,
                            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        }
                        log_correction(record)
                        context_note = ""
                        context_stats = getattr(decision, "audit_context_stats", None)
                        if context_stats:
                            context_note = (
                                f" context_chars={context_stats.get('chars')} "
                                f"context_truncated={context_stats.get('context_truncated')}"
                            )
                        print(
                            f"🧭 [Correction] Tool batch decision={decision.decision}: "
                            f"{format_json_for_feedback(compact_decision_feedback(decision))}{context_note}"
                        )

                    approved_calls = proposed_calls
                    if decision.decision == "REVISE" and decision.calls:
                        approved_calls = decision.calls
                    elif not decision.approved:
                        if correction_rounds >= args.max_correction_rounds:
                            rejected_state_change = any(
                                is_state_changing_tool(str(call.get("tool_name") or call.get("name") or ""))
                                for call in proposed_calls
                            )
                            if rejected_state_change:
                                agent_final_reply = "[Interaction stopped: correction rejected a state-changing tool batch]"
                                print("🛑 [Correction] Rejected state-changing tool batch was not executed.")
                                break
                            if args.correction_on_max_tool_rounds == "stop":
                                agent_final_reply = "[Interaction stopped: correction rounds exceeded]"
                                break
                            print("⚠️ [Correction] Max rounds exceeded; executing proposed tool batch.")
                        else:
                            correction_rounds += 1
                            feedback = review_feedback(
                                decision,
                                proposed_kind="tool_calls",
                                rejected_output=agent_reply,
                            )
                            local_service_history.append({"role": "assistant", "content": agent_reply})
                            local_service_history.append({"role": "user", "content": feedback})
                            force_attach_frames = False
                            continue
                    latest_correction_frames = []

                    safe_calls, repeated_calls = split_repeated_state_changes(
                        approved_calls,
                        prior_tool_logs=history_log["tool_calls"],
                        current_tool_logs=local_tool_logs,
                        latest_user_message=current_user_reply,
                    )
                    if repeated_calls:
                        repeat_feedback = (
                            "Internal repeat guard: the following state-changing tool call(s) already "
                            "succeeded earlier in this task and the current user message does not "
                            "explicitly ask for an additional quantity or a new repeated change:\n"
                            f"{canonical_tool_call_text(repeated_calls)}\n"
                            "Do not execute these duplicate mutations. Use read-only tools to verify "
                            "current state if needed, or answer based on the completed state."
                        )
                        print(f"🛡️ [Repeat Guard] blocked duplicate mutation(s): {canonical_tool_call_text(repeated_calls)}")
                        if correction_rounds < args.max_correction_rounds:
                            correction_rounds += 1
                            local_service_history.append({"role": "assistant", "content": canonical_tool_call_text(approved_calls)})
                            local_service_history.append({"role": "user", "content": repeat_feedback})
                            force_attach_frames = False
                            continue
                        approved_calls = safe_calls
                        if not approved_calls:
                            local_service_history.append({"role": "assistant", "content": canonical_tool_call_text(repeated_calls)})
                            local_service_history.append({"role": "user", "content": repeat_feedback})
                            continue

                    calls_this_round = len(approved_calls)
                    if total_tool_calls_so_far + inner_calls + calls_this_round > args.max_tool_calls:
                        agent_final_reply = "[Interaction stopped: tool calls exceeded limit]"
                        break
                    inner_calls += calls_this_round
                    print(f"🛠️ Tested Agent Tool Call: {canonical_tool_call_text(approved_calls)}")
                    tool_results = execute_tool(db, approved_calls)
                    local_tool_logs.append(
                        {
                            "turn": turn,
                            "calls": approved_calls,
                            "results": tool_results,
                        }
                    )
                    combined_result = "; ".join(res.get("content", str(res)) for res in tool_results)
                    local_service_history.append(
                        {"role": "assistant", "content": canonical_tool_call_text(approved_calls)}
                    )
                    local_service_history.append({"role": "user", "content": f"Tool execution result: {combined_result}"})
                else:
                    finalize_after_inner_tool_limit()

                return {
                    "reply": agent_final_reply,
                    "input_tokens": inner_input_tokens,
                    "output_tokens": inner_output_tokens,
                    "calls": inner_calls,
                    "rounds": inner_rounds,
                    "tool_logs": local_tool_logs,
                    "dialogue_logs": local_dialogue_logs,
                    "correction_logs": local_correction_logs,
                    "correction_input_tokens": correction_input_tokens,
                    "correction_output_tokens": correction_output_tokens,
                    "frame_attached_calls": frame_attached_calls,
                    "visual_context_requests": visual_context_requests,
                    "time": time.time() - agent_start,
                    "updated_history": local_service_history,
                }

            try:
                agent_res = process_agent_task()
                visible_agent_reply = bool(agent_res.get("dialogue_logs"))
                if visible_agent_reply:
                    turn_summary = generate_summary_task(str(agent_res.get("reply", "")))
                else:
                    turn_summary = None
            except Exception as exc:
                task_error = exc
                history_log["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "turn": turn,
                    "stage": "service_or_summary",
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                }
                print(f"❌ [Task Error] Task {task_id} failed at turn {turn}: {exc}")
                break

            input_tokens_total += agent_res["input_tokens"]
            output_tokens_total += agent_res["output_tokens"]
            tool_calls_count += agent_res["calls"]
            rounds_count += agent_res["rounds"]
            history_log["agent_response_time_seconds"] += agent_res["time"]
            history_log["tool_calls"].extend(agent_res["tool_logs"])
            history_log["dialogue"].extend(agent_res["dialogue_logs"])
            history_log["frame_attached_calls"] += agent_res.get("frame_attached_calls", 0)
            history_log["visual_context_requests"] += agent_res.get("visual_context_requests", 0)
            if args.enable_correction_agent:
                history_log.setdefault("correction_input_tokens", 0)
                history_log.setdefault("correction_output_tokens", 0)
                history_log["correction_input_tokens"] += agent_res.get("correction_input_tokens", 0)
                history_log["correction_output_tokens"] += agent_res.get("correction_output_tokens", 0)
                if args.include_correction_trace:
                    history_log.setdefault("correction_trace", []).extend(agent_res.get("correction_logs", []))
            service_history = agent_res["updated_history"]
            last_agent_response_for_check = agent_res["reply"]
            print(f"⏱️ [Time] Agent response generation (Turn {turn}): {agent_res['time']:.3f} seconds")

            if not visible_agent_reply:
                print(
                    "🛑 [Turn Stop] Service did not produce a user-visible final reply; "
                    "skipping summary and stopping this task."
                )
                history_log["error"] = {
                    "type": "NoVisibleAgentReply",
                    "message": str(agent_res.get("reply", "")),
                    "turn": turn,
                    "stage": "service_final_reply",
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                }
                break

            if args.summary_user and turn_summary:
                summarized_history_str = f"Turn {turn} Dialogue Summary of completed steps: {turn_summary}\n"

            user_agent_sys_prompt = USER_TEXT_ONLY_PROMPT_EASY.format(
                user_instruction=user_instruction,
                image_description=image_description,
                original_user_response="",
                evaluation_feedback="",
                history_summary=summarized_history_str,
                service_agent_response=last_agent_response_for_check,
            )
            user_messages[0]["content"] = user_agent_sys_prompt
            if args.summary_user and turn_summary:
                user_messages = [
                    {"role": "system", "content": user_agent_sys_prompt},
                    {
                        "role": "user",
                        "content": "Please continue the conversation in the first person according to the original settings based on the summary and latest response.",
                    },
                ]
            else:
                user_messages.append({"role": "user", "content": last_agent_response_for_check})

        if executor is not None:
            executor.shutdown(wait=True)
        history_log["rounds_count"] = rounds_count
        history_log["input_tokens"] = input_tokens_total
        history_log["output_tokens"] = output_tokens_total
        history_log["tokens_consumed"] = input_tokens_total + output_tokens_total
        history_log["tool_calls_count"] = tool_calls_count
        if scenario_original_scores:
            history_log["original_scores"] = scenario_original_scores
        if scenario_corrected_scores:
            history_log["corrected_scores"] = scenario_corrected_scores
        if valid_evaluation_count > 0:
            history_log["user_performance"] = {
                **{
                    f"original_{key}_avg": round(value / valid_evaluation_count, 2)
                    for key, value in accumulated_original_scores.items()
                },
                **{
                    f"final_{key}_avg": round(value / valid_evaluation_count, 2)
                    for key, value in accumulated_final_scores.items()
                },
            }
        else:
            history_log["user_performance"] = {}
        history_log["execution_time_seconds"] = round(time.time() - start_time, 3)
        all_results = [
            result
            for result in all_results
            if int(result.get("task_id", -1)) != task_id
        ]
        all_results.append(history_log)
        all_results.sort(key=lambda result: int(result.get("task_id", 10**9)))
        save_results(output_path, all_results)
        print(f"💾 [Checkpoint] Saved {len(all_results)} result records to: {output_path}")
        if task_error is not None and not args.continue_on_task_error:
            raise RuntimeError(f"Task {task_id} failed; checkpoint saved to {output_path}") from task_error

    print(f"\n✅ Completed! Results saved to: {output_path}")
    print("📊 Statistics Summary:")
    for idx, result in enumerate(all_results, start=1):
        print(
            f"  Task {idx}: {result['rounds_count']} dialogue rounds, "
            f"{result['input_tokens']} input tokens, {result['output_tokens']} output tokens, "
            f"{result['tool_calls_count']} tool calls, {result['execution_time_seconds']} seconds"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GPT-5.5 frame-based service-agent EgoBench simulation")
    parser.add_argument("--user_model_name", default=DEFAULT_USER_MODEL_NAME)
    parser.add_argument(
        "--user_api_key",
        default=(
            os.environ.get("USER_API_KEY")
            or os.environ.get("SERVICE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("API_KEY")
        ),
    )
    parser.add_argument(
        "--user_api_base_url",
        default=(
            os.environ.get("USER_API_BASE_URL")
            or os.environ.get("SERVICE_API_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("LLM_API_BASE_URL")
        ),
    )
    parser.add_argument(
        "--user_temperature",
        type=float,
        default=float(os.environ.get("USER_TEMPERATURE", "0.0")),
        help="Sampling temperature for user-model generation, user checks/corrections, and summaries.",
    )
    parser.add_argument(
        "--user_enable_thinking",
        action=argparse.BooleanOptionalAction,
        default=optional_bool_env("USER_ENABLE_THINKING"),
        help=(
            "Qwen/DashScope user-model thinking switch. Omit to use the provider default; "
            "use --user_enable_thinking or --no-user_enable_thinking to force it."
        ),
    )
    parser.add_argument(
        "--user_thinking_budget",
        type=int,
        default=optional_int_env("USER_THINKING_BUDGET"),
        help="Optional Qwen/DashScope thinking_budget for the user model.",
    )
    parser.add_argument(
        "--user_preserve_thinking",
        action=argparse.BooleanOptionalAction,
        default=optional_bool_env("USER_PRESERVE_THINKING"),
        help="Optional Qwen/DashScope preserve_thinking flag for user-model chat history.",
    )
    parser.add_argument("--service_model_name", default=DEFAULT_SERVICE_MODEL_NAME)
    parser.add_argument(
        "--service_api_key",
        default=(
            os.environ.get("SERVICE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        ),
    )
    parser.add_argument(
        "--service_api_base_url",
        default=(
            os.environ.get("SERVICE_API_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        ),
    )
    parser.add_argument("--service_timeout", type=int, default=600)
    parser.add_argument("--service_max_retries", type=int, default=8)
    parser.add_argument("--service_retry_base_delay", type=float, default=30.0)
    parser.add_argument("--service_retry_max_delay", type=float, default=180.0)
    parser.add_argument("--service_retry_after_cap", type=float, default=300.0)
    parser.add_argument("--service_max_output_tokens", type=int, default=32768)
    parser.add_argument("--service_temperature", type=float, default=0.0)
    parser.add_argument(
        "--service_reasoning_effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default=os.environ.get("SERVICE_REASONING_EFFORT", "low"),
        help="OpenAI Responses reasoning.effort for the service agent. Use 'none' to omit the reasoning object.",
    )
    parser.add_argument("--log_service_payload_size", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--service_payload_warn_mb", type=float, default=2.5)
    parser.add_argument("--enable_correction_agent", action="store_true")
    parser.add_argument(
        "--correction_api_type",
        choices=["responses", "response", "chat_completions", "chat_completion"],
        default=os.environ.get("CORRECTION_API_TYPE") or "responses",
        help="Use responses for GPT-5.5 correction or chat_completions for DeepSeek/OpenAI-compatible chat APIs.",
    )
    parser.add_argument("--correction_model_name", default=None)
    parser.add_argument(
        "--correction_api_key",
        default=None,
    )
    parser.add_argument(
        "--correction_api_base_url",
        default=None,
    )
    parser.add_argument("--correction_timeout", type=int, default=300)
    parser.add_argument("--correction_max_retries", type=int, default=3)
    parser.add_argument("--correction_retry_base_delay", type=float, default=10.0)
    parser.add_argument("--correction_retry_max_delay", type=float, default=60.0)
    parser.add_argument("--correction_retry_after_cap", type=float, default=120.0)
    parser.add_argument("--correction_max_output_tokens", type=int, default=2048)
    parser.add_argument("--correction_temperature", type=float, default=0.0)
    parser.add_argument(
        "--correction_thinking",
        choices=["enabled", "disabled", "none"],
        default=os.environ.get("CORRECTION_THINKING") or os.environ.get("DEEPSEEK_THINKING") or "disabled",
    )
    parser.add_argument(
        "--correction_reasoning_effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh", "max"],
        default=os.environ.get("CORRECTION_REASONING_EFFORT") or os.environ.get("DEEPSEEK_REASONING_EFFORT") or "medium",
    )
    parser.add_argument("--max_correction_rounds", type=int, default=5)
    parser.add_argument("--correction_failure_policy", choices=["approve", "reject"], default="approve")
    parser.add_argument("--correction_on_max_rounds", choices=["execute", "stop"], default="execute")
    parser.add_argument("--correction_on_max_tool_rounds", choices=["execute", "stop"], default=None)
    parser.add_argument("--correction_on_max_reply_rounds", choices=["accept", "stop"], default="accept")
    parser.add_argument(
        "--correction_max_tool_log_entries",
        type=int,
        default=0,
        help="Deprecated no-op: correction audit context now includes all current-turn tool log entries.",
    )
    parser.add_argument(
        "--correction_max_tool_result_chars",
        type=int,
        default=800,
        help="Deprecated no-op: correction audit context now includes full tool results.",
    )
    parser.add_argument(
        "--correction_max_audit_context_chars",
        type=int,
        default=120000,
        help="Deprecated no-op: correction audit context is no longer truncated.",
    )
    parser.add_argument("--correction_auto_approve_read_only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include_correction_trace", action="store_true")
    parser.add_argument("--scenario", choices=["retail", "kitchen", "restaurant", "order"], default="retail")
    parser.add_argument("--scenario_number", type=int, default=1)
    parser.add_argument("--num_tasks", type=int, default=0)
    parser.add_argument("--task_ids", type=parse_task_ids, default=None)
    parser.add_argument("--max_turns", type=int, default=10)
    parser.add_argument("--max_inner_tool_rounds", type=int, default=12)
    parser.add_argument("--max_tool_calls", type=int, default=200)
    parser.add_argument("--multi_agent_user", action="store_true")
    parser.add_argument("--summary_user", action="store_true")
    parser.add_argument("--parallel_summary_user", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue_on_task_error", action="store_true")
    parser.add_argument("--output_model_name", default=None)
    parser.add_argument("--frame_fps", type=float, default=2.0)
    parser.add_argument("--frame_max_side", type=int, default=1920)
    parser.add_argument(
        "--frame_rotation",
        choices=["none", "clockwise", "counterclockwise", "180"],
        default="none",
        help="Rotate sampled frames after scaling. Use counterclockwise for restaurant menu videos that appear sideways.",
    )
    parser.add_argument("--jpeg_quality", type=int, default=3)
    parser.add_argument("--max_frames", type=int, default=0)
    parser.add_argument("--image_detail", choices=["low", "auto", "high"], default="high")
    parser.add_argument("--frames_each_turn", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--frame_attach_policy",
        choices=["each_turn", "first_turn", "auto", "never"],
        default=None,
        help=(
            "Controls when sampled frames are attached to service-agent calls. "
            "Default is 'auto' for NEED_VISUAL_CONTEXT-driven attachment."
        ),
    )
    parser.add_argument(
        "--max_visual_context_requests",
        type=int,
        default=6,
        help="Maximum internal NEED_VISUAL_CONTEXT retries per user turn before stopping that turn.",
    )
    parser.add_argument("--refresh_frames", action="store_true")
    parser.add_argument(
        "--frame_cache_dir",
        default=str(PROJECT_ROOT / "experiments" / "gpt55_frame_service_runner" / "cache" / "frames"),
    )
    args = parser.parse_args()
    if args.correction_on_max_tool_rounds is None:
        args.correction_on_max_tool_rounds = args.correction_on_max_rounds
    if args.frame_attach_policy is None:
        # New default: lazy visual attachment. Service decides per-turn by emitting NEED_VISUAL_CONTEXT.
        if args.frames_each_turn is True:
            args.frame_attach_policy = "each_turn"
        elif args.frames_each_turn is False:
            args.frame_attach_policy = "never"
        else:
            args.frame_attach_policy = "auto"
    correction_api_aliases = {
        "response": "responses",
        "responses": "responses",
        "chat_completion": "chat_completions",
        "chat_completions": "chat_completions",
    }
    args.correction_api_type = correction_api_aliases[args.correction_api_type]
    if args.correction_api_type == "responses":
        args.correction_model_name = args.correction_model_name or args.service_model_name or env_default_model()
        args.correction_api_key = args.correction_api_key or args.service_api_key
        args.correction_api_base_url = args.correction_api_base_url or args.service_api_base_url
    else:
        args.correction_model_name = args.correction_model_name or env_chat_completions_model()
        args.correction_api_key = (
            args.correction_api_key
            or os.environ.get("CORRECTION_API_KEY")
            or os.environ.get("Deepseek_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
        )
        args.correction_api_base_url = (
            args.correction_api_base_url
            or os.environ.get("CORRECTION_API_BASE_URL")
            or os.environ.get("Deepseek_SERVICE_API_BASE_URL")
            or os.environ.get("DEEPSEEK_API_BASE_URL")
            or "https://api.deepseek.com"
        )
    return args


def main() -> None:
    args = parse_args()
    input_json = PROJECT_ROOT / "scenarios" / "final" / f"{args.scenario}{args.scenario_number}.json"
    tool_info_json = PROJECT_ROOT / "tools" / args.scenario / f"{args.scenario}_tools.json"
    output_model_name = args.output_model_name or f"gpt55-frame-{slugify_name(args.service_model_name)}-{timestamp_tag()}-{args.scenario}"
    output_json = PROJECT_ROOT / "results" / output_model_name / f"{args.scenario}{args.scenario_number}_easy.json"
    run_simulation(str(input_json), str(tool_info_json), str(output_json), args)


if __name__ == "__main__":
    main()
