#!/usr/bin/env python3
"""
Visual observer HTTP server.

Current production path:
1. ask a first-stage video model to locate the event that grounds the user request,
2. extract an ordered short frame sequence from the original video at original size,
3. ask a second-stage vision model to identify the visible anchor from those frames,
4. return compact visual key/value facts for the tool-using agent.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.visual_observer_runner.prompts import (  # noqa: E402
    build_qwen_event_prompt,
    build_qwen_sequence_prompt,
    build_qwen_video_event_prompt,
)

DEFAULT_CACHE_DIR = CURRENT_FILE.parent / "cache" / "visual_observer"
DEFAULT_FONT = "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"

ALLOWED_VISUAL_KEYS = {
    "product_name",
    "dish_name",
    "ingredient_name",
    "recipe_name",
    "category",
    "set_meal_name",
    "visible_region",
}

def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[len("export ") :].strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def now_tag() -> str:
    return time.strftime("%Y%m%d%H%M%S", time.localtime())


def stable_hash(value: Any, length: int = 16) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def slugify_name(value: Any, fallback: str = "item") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    slug = slug.strip("-._")
    return slug or fallback


def experiment_cache_dir(base_cache_dir: Path, payload: dict[str, Any]) -> Path:
    experiment_id = payload.get("experiment_id") or payload.get("run_id") or payload.get("output_model_name")
    timestamp = payload.get("experiment_timestamp") or payload.get("run_timestamp")
    if not experiment_id:
        experiment_id = f"standalone-{now_tag()}-{stable_hash(payload, 8)}"
    if not timestamp:
        timestamp = now_tag()
    return base_cache_dir / "runs" / slugify_name(timestamp, "run") / slugify_name(experiment_id, "experiment")


def ensure_run_dirs(cache_dir: Path) -> None:
    for name in ("labeled_videos", "event_frames", "keyframes", "traces"):
        (cache_dir / name).mkdir(parents=True, exist_ok=True)


def scenario_trace_key(payload: dict[str, Any]) -> str:
    task_id = str(payload.get("task_id") or "")
    match = re.match(r"^([A-Za-z]+[0-9]+)(?:_|$)", task_id)
    if match:
        return slugify_name(match.group(1).lower(), "scenario")
    return slugify_name(payload.get("scenario") or "scenario", "scenario")


def task_turn_key(payload: dict[str, Any]) -> tuple[str, str | None]:
    task_id = str(payload.get("task_id") or "task")
    match = re.match(r"^(.+)_turn(\d+)$", task_id)
    if match:
        turn_key = f"turn{match.group(2)}"
        request_key = payload.get("request_key")
        if not request_key:
            request_key = stable_hash(
                {
                    "current_user_message": payload.get("current_user_message"),
                    "referent_hint": payload.get("referent_hint"),
                },
                8,
            )
        return slugify_name(match.group(1), "task"), f"{turn_key}_{slugify_name(request_key, 'request')}"
    return slugify_name(task_id, "task"), None


def write_scenario_trace(cache_dir: Path, payload: dict[str, Any], trace: dict[str, Any]) -> Path:
    trace_dir = cache_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{scenario_trace_key(payload)}.json"
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
    else:
        doc = {
            "schema_version": "visual_observer_scenario_trace_v2",
            "scenario": payload.get("scenario"),
            "scenario_key": scenario_trace_key(payload),
            "experiment_id": cache_dir.name,
            "experiment_timestamp": cache_dir.parent.name,
            "experiment_cache_dir": str(cache_dir),
            "created_at": now,
            "updated_at": now,
            "tasks": {},
        }
    doc["updated_at"] = now
    task_key, turn_key = task_turn_key(payload)
    task_entry = doc.setdefault("tasks", {}).setdefault(
        task_key,
        {"task_key": task_key, "turns": {}, "observations": []},
    )
    if turn_key:
        trace.setdefault("turn_label", re.sub(r"_.*$", "", turn_key))
        trace.setdefault("observer_request_key", turn_key)
        task_entry.setdefault("turns", {})[turn_key] = trace
    else:
        task_entry.setdefault("observations", []).append(trace)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def local_video_path(video_path: str) -> Path:
    if is_url(video_path):
        raise ValueError("aura_qwenvl_observer requires a local video_path for frame extraction")
    path = Path(video_path)
    if path.exists():
        return path.resolve()
    candidate = PROJECT_ROOT / "videos" / video_path
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"video not found: {video_path}")


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def command_output(command: list[str]) -> str:
    return subprocess.check_output(command, stderr=subprocess.PIPE, text=True).strip()


def video_duration_seconds(video_path: Path) -> float:
    text = command_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    return max(0.0, float(text))


def make_labeled_video(video_path: Path, cache_dir: Path, fps: float, fontfile: str, refresh: bool) -> Path:
    labeled_dir = cache_dir / "labeled_videos"
    labeled_dir.mkdir(parents=True, exist_ok=True)
    key = stable_hash({"video": str(video_path), "mtime": video_path.stat().st_mtime, "fps": fps})
    output_path = labeled_dir / f"{video_path.stem}_{fps:g}fps_{key}.mp4"
    if output_path.exists() and not refresh:
        return output_path
    escaped_font = fontfile.replace(":", "\\:")
    draw = (
        f"fps={fps},"
        f"drawtext=fontfile={escaped_font}:"
        "text='F%{n} %{pts\\:hms}':"
        "x=20:y=20:fontsize=80:fontcolor=yellow:box=1:boxcolor=black@0.70"
    )
    run_command(["ffmpeg", "-y", "-i", str(video_path), "-vf", draw, "-an", str(output_path)])
    return output_path


def keyframe_output_name(
    scenario: str,
    task_id: str,
    timestamp: float,
    referent_index: int,
    frame_index: int,
    request_key: str | None = None,
) -> str:
    scene_part = slugify_name(scenario or "scene", "scene")
    task_part = slugify_name(task_id or "task", "task")
    request_part = slugify_name(request_key or "", "")
    request_prefix = f"-{request_part}" if request_part else ""
    return f"{scene_part}-{task_part}{request_prefix}-t{timestamp:.2f}-r{referent_index:02d}-k{frame_index:02d}.png"


def event_frame_output_name(scenario: str, task_id: str, frame_index: int, timestamp: float) -> str:
    scene_part = slugify_name(scenario or "scene", "scene")
    task_part = slugify_name(task_id or "task", "task")
    return f"{scene_part}-{task_part}-event-F{frame_index:03d}-t{timestamp:.2f}.jpg"


def extract_frame(video_path: Path, timestamp: float, output_dir: Path, output_name: str, max_side: int | None = 1024) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name

    def try_extract(ts: float) -> bool:
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, ts):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
        ]
        if max_side is not None and max_side > 0:
            command.extend(["-vf", f"scale={max_side}:{max_side}:force_original_aspect_ratio=decrease"])
        if output_path.suffix.lower() in {".jpg", ".jpeg"}:
            command.extend(["-q:v", "2"])
        command.append(str(output_path))
        run_command(command)
        return output_path.exists() and output_path.stat().st_size > 0

    for candidate in (timestamp, timestamp - 0.25, timestamp - 0.5, timestamp - 1.0):
        if candidate >= 0 and try_extract(candidate):
            return output_path
    raise FileNotFoundError(f"failed to extract frame near {timestamp:.3f}s from {video_path}")


def event_frame_timestamps(video_path: Path, fps: float, max_frames: int) -> list[float]:
    duration = video_duration_seconds(video_path)
    if duration <= 0 or max_frames <= 0:
        return []
    effective_fps = max(0.1, fps)
    target_count = max(1, int(duration * effective_fps))
    count = min(max_frames, target_count)
    # Avoid sampling the exact video duration; ffmpeg often returns no frame at EOF.
    end = max(0.0, duration - min(0.25, 0.5 / effective_fps))
    return evenly_spaced(0.0, end, count)


def sample_event_frames(
    video_path: Path,
    scenario: str,
    task_id: str,
    frame_dir: Path,
    fps: float,
    max_frames: int,
    frame_max_side: int,
) -> list[dict[str, Any]]:
    records = []
    for idx, timestamp in enumerate(event_frame_timestamps(video_path, fps, max_frames)):
        name = event_frame_output_name(scenario, task_id, idx, timestamp)
        records.append(
            {
                "frame_id": f"F{idx:03d}",
                "timestamp": timestamp,
                "path": extract_frame(video_path, timestamp, frame_dir, name, frame_max_side),
            }
        )
    return records


def local_image_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def local_video_file_url(path: Path) -> str:
    return path.resolve().as_uri()


def is_local_api_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def qwen_image_url(path: Path, base_url: str | None) -> str:
    if is_local_api_base_url(base_url):
        return path.resolve().as_uri()
    return local_image_data_url(path)


def load_video_url_mapping(raw_mapping: str | None = None) -> dict[str, str]:
    raw_mapping = raw_mapping if raw_mapping is not None else os.environ.get("VIDEO_URL_MAPPING", "")
    if not raw_mapping:
        return {}
    try:
        parsed = json.loads(raw_mapping)
    except json.JSONDecodeError:
        print("[Warning] Failed to parse VIDEO_URL_MAPPING for observer qwen_video URL mode.")
        return {}
    if not isinstance(parsed, dict):
        print("[Warning] VIDEO_URL_MAPPING must be a JSON object.")
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def public_video_url(path: Path, args: argparse.Namespace) -> str:
    filename = path.name
    mapping = load_video_url_mapping(args.video_url_mapping)
    if filename in mapping:
        return mapping[filename]

    base_url = args.video_url_base or os.environ.get("OBSERVER_VIDEO_URL_BASE") or os.environ.get("VIDEO_URL_BASE")
    if base_url:
        return f"{base_url.rstrip('/')}/{quote(filename)}"

    raise ValueError(
        f"No public URL configured for video {filename!r}. "
        "Set VIDEO_URL_MAPPING, OBSERVER_VIDEO_URL_BASE, or VIDEO_URL_BASE."
    )


def qwen_video_url(video_path: Path, base_url: str, args: argparse.Namespace) -> str:
    mode = args.qwen_video_url_mode
    if mode == "local":
        return local_video_file_url(video_path)
    if mode == "url":
        return public_video_url(video_path, args)
    if is_local_api_base_url(base_url):
        return local_video_file_url(video_path)
    return public_video_url(video_path, args)


def qwen_vl_env(args: argparse.Namespace, stage: str = "event") -> tuple[str, str, str]:
    stage = stage.lower()
    if stage not in {"event", "detail"}:
        raise ValueError(f"unsupported QwenVL stage: {stage}")

    stage_api_key = (
        getattr(args, f"qwen_{stage}_api_key", None)
        or os.environ.get(f"QW_{stage.upper()}_OBSERVER_API_KEY")
        or (os.environ.get("QW_OBSERVER_API_KEY") if stage == "detail" else None)
    )
    stage_base_url = (
        getattr(args, f"qwen_{stage}_api_base_url", None)
        or os.environ.get(f"QW_{stage.upper()}_OBSERVER_API_BASE_URL")
        or (os.environ.get("QW_OBSERVER_API_BASE_URL") if stage == "detail" else None)
    )
    stage_model = (
        getattr(args, f"qwen_{stage}_model", None)
        or os.environ.get(f"QW_{stage.upper()}_OBSERVER_MODEL_NAME")
        or (os.environ.get("QW_OBSERVER_MODEL_NAME") if stage == "detail" else None)
    )

    api_key = (
        stage_api_key
        or args.qwen_api_key
        or os.environ.get("QWEN_VL_API_KEY")
        or os.environ.get("QW_SERVICE_API_KEY")
        or os.environ.get("QW_API_KEY")
        or os.environ.get("SERVICE_API_KEY")
        or os.environ.get("API_KEY")
        or "EMPTY"
    )
    base_url = (
        stage_base_url
        or args.qwen_api_base_url
        or os.environ.get("QWEN_VL_API_BASE_URL")
        or os.environ.get("QW_SERVICE_API_BASE_URL")
        or os.environ.get("QW_LLM_API_BASE_URL")
        or os.environ.get("SERVICE_API_BASE_URL")
        or os.environ.get("LLM_API_BASE_URL")
    )
    model = (
        stage_model
        or args.qwen_model
        or (os.environ.get("QW_OBSERVER_MODEL_NAME") if stage == "event" else None)
        or os.environ.get("QWEN_VL_MODEL")
        or os.environ.get("QW_SERVICE_MODEL_NAME")
        or "qwen3-vl-225b"
    )
    if not base_url:
        raise ValueError("QwenVL base URL is not configured")
    return api_key, base_url, model


def qwen_generation_config(args: argparse.Namespace, stage: str) -> dict[str, Any]:
    temperature = getattr(args, f"qwen_{stage}_temperature", None)
    max_tokens = getattr(args, f"qwen_{stage}_max_tokens", None)
    enable_thinking = getattr(args, f"qwen_{stage}_enable_thinking", None)
    thinking_budget = getattr(args, f"qwen_{stage}_thinking_budget", None)
    high_resolution_images = getattr(args, f"qwen_{stage}_high_resolution_images", "off")
    global_thinking = args.qwen_enable_thinking
    global_thinking_mode = getattr(args, "qwen_thinking", "off")
    if global_thinking_mode == "on":
        global_thinking = True
    elif global_thinking_mode == "off":
        global_thinking = False

    stage_thinking_mode = getattr(args, f"qwen_{stage}_thinking", "inherit")
    if stage_thinking_mode == "on":
        resolved_enable_thinking = True
    elif stage_thinking_mode == "off":
        resolved_enable_thinking = False
    else:
        resolved_enable_thinking = global_thinking if enable_thinking is None else enable_thinking

    return {
        "temperature": args.qwen_temperature if temperature is None else temperature,
        "max_tokens": args.qwen_max_tokens if max_tokens is None else max_tokens,
        "enable_thinking": resolved_enable_thinking,
        "thinking_budget": args.qwen_thinking_budget if thinking_budget is None else thinking_budget,
        "include_reasoning": args.qwen_include_reasoning,
        "vl_high_resolution_images": high_resolution_images == "on",
    }


def is_dashscope_base_url(base_url: str | None) -> bool:
    host = urlparse(base_url or "").netloc.lower()
    return "dashscope" in host or "aliyuncs.com" in host


def qwen_extra_body(generation: dict[str, Any], base_url: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    thinking_budget = generation.get("thinking_budget")
    if is_dashscope_base_url(base_url):
        body["enable_thinking"] = generation["enable_thinking"]
        if generation["enable_thinking"] and thinking_budget is not None:
            body["thinking_budget"] = thinking_budget
    else:
        body["chat_template_kwargs"] = {
            "enable_thinking": generation["enable_thinking"],
        }
        if generation.get("include_reasoning"):
            body["include_reasoning"] = True
        if generation["enable_thinking"] and thinking_budget is not None:
            body["thinking_token_budget"] = thinking_budget
    if generation.get("vl_high_resolution_images"):
        body["vl_high_resolution_images"] = True
    return body


def build_scene_description(scenario: str, image_description: str) -> str:
    return image_description or "N/A"


TEMPORAL_ORDINAL_PATTERN = re.compile(
    r"\b(first|second|third|fourth|fifth|last|previous|next|before|after|sequence|ordered|ordinal)\b",
    re.IGNORECASE,
)
TEMPORAL_ACTION_PATTERN = re.compile(
    r"\b(point(?:ed|ing)?|touch(?:ed|ing)?|tap(?:ped|ping)?|click(?:ed|ing)?|press(?:ed|ing)?|"
    r"pick(?:ed|ing)?|select(?:ed|ing)?|choose|chose|chosen|grab(?:bed|bing)?|hold(?:ing)?|held|"
    r"open(?:ed|ing)?|close(?:d|ing)?|move(?:d|ing)?|place(?:d|ing)?|put|take|took|taken|"
    r"show(?:ed|ing)?|indicat(?:ed|ing)?|gesture(?:d|ing)?)\b",
    re.IGNORECASE,
)


def is_temporal_action_request(current_user_message: str) -> bool:
    text = current_user_message or ""
    return bool(TEMPORAL_ORDINAL_PATTERN.search(text) and TEMPORAL_ACTION_PATTERN.search(text))


def effective_event_backend(args: argparse.Namespace, current_user_message: str) -> tuple[str, str | None]:
    backend = args.event_localizer_backend
    if backend == "qwen_video" and is_temporal_action_request(current_user_message):
        temporal_backend = getattr(args, "temporal_event_backend", "qwen_frames")
        if temporal_backend in {"qwen_frames", "qwen_video"} and temporal_backend != backend:
            return temporal_backend, (
                "temporal_action_request: ordinal/action wording is routed to labeled frame sequence "
                "so event ordering is explicit."
            )
    return backend, None


def extract_json_object(text: str) -> Any:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(stripped)
    except Exception:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except Exception:
            pass
    return None


def aura_observation_payload(aura_response: dict[str, Any]) -> dict[str, Any]:
    observation = aura_response.get("observation", aura_response)
    if isinstance(observation, dict) and "raw" in observation:
        parsed = extract_json_object(str(observation.get("raw", "")))
        return parsed if isinstance(parsed, dict) else observation
    return observation if isinstance(observation, dict) else {"raw": observation}


def coerce_list(value: Any, max_items: int | None = None) -> list[Any]:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    elif isinstance(value, str):
        parsed = extract_json_object(value)
        if isinstance(parsed, list):
            items = parsed
        elif "," in value:
            items = [part.strip() for part in value.split(",") if part.strip()]
        elif value.strip():
            items = [value.strip()]
        else:
            items = []
    else:
        items = [value]
    return items[:max_items] if max_items is not None else items


def normalize_confidence(value: Any) -> str | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value).strip().lower()
    if text in {"low", "medium", "high"}:
        return text
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        return text or None


def normalize_event_type(event_type: Any, ordinal: Any, referent: str) -> str:
    base = str(event_type or "").strip().lower()
    ref = referent.lower()
    if "point" in base or "point" in ref:
        if ordinal and str(ordinal).lower() not in {"null", "none"}:
            return "ordinal_pointing"
        if "final" in ref or "last" in ref:
            return "final_pointing"
        return "pointing"
    if "hold" in base or "holding" in ref:
        return "holding_object"
    if "menu" in base or "section" in ref or "foldout" in ref:
        return "menu_region_reference"
    if "state" in base:
        return "object_state"
    return base or "visual_reference"


def default_downstream_instruction(user_referent: str, event_type: str | None = None) -> str:
    if event_type:
        return (
            f"These frames show the localized {event_type} event for: {user_referent}. "
            "Identify the visible anchor involved in this event."
        )
    return f"These frames show {user_referent}. Identify the visible anchor involved in this event."


def clean_downstream_instruction(value: Any, user_referent: str, event_type: str | None = None) -> str:
    text = str(value or "").strip()
    lower = text.lower()
    placeholder_patterns = (
        "...",
        "please identify ...",
        "these frames show ...",
        "these frames show the localized visual event",
    )
    if not text or any(pattern in lower for pattern in placeholder_patterns):
        return default_downstream_instruction(user_referent, event_type)
    return text


def frame_id_to_timestamp(frame_id: Any, fps: float) -> float | None:
    if not frame_id:
        return None
    match = re.search(r"F\s*(\d+)", str(frame_id), re.IGNORECASE)
    return int(match.group(1)) / fps if match else None


def parse_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"F\s*\d+", text, re.IGNORECASE):
        return None
    try:
        return float(text.rstrip("s"))
    except ValueError:
        pass
    match = re.search(r"(?:(\d+):)?(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return (int(match.group(1)) * 60 if match.group(1) else 0) + float(match.group(2))


def parse_time_range_endpoint(value: Any, endpoint: str) -> float | None:
    if value is None:
        return None
    matches = re.findall(r"(?:(\d+):)?(\d+(?:\.\d+)?)", str(value))
    if not matches:
        return None
    seconds = [(int(minute) * 60 if minute else 0) + float(second) for minute, second in matches]
    if endpoint == "start":
        return seconds[0]
    if endpoint == "midpoint" and len(seconds) >= 2:
        return (seconds[0] + seconds[-1]) / 2
    return seconds[-1]


def parse_event_time_range(ref: dict[str, Any]) -> dict[str, float | None]:
    raw = ref.get("event_time_range") or ref.get("event_segment") or ref.get("time_segment")
    start = None
    end = None
    if isinstance(raw, dict):
        start = parse_timestamp(raw.get("start") or raw.get("start_time"))
        end = parse_timestamp(raw.get("end") or raw.get("end_time"))
    elif raw is not None:
        start = parse_time_range_endpoint(raw, "start")
        end = parse_time_range_endpoint(raw, "end")
    if start is None:
        start = parse_time_range_endpoint(ref.get("time_range"), "start")
    if end is None:
        end = parse_time_range_endpoint(ref.get("time_range"), "end")
    return {"start": start, "end": end}


def parse_timestamp_list(value: Any, labeled_fps: float) -> list[float]:
    timestamps = []
    for item in coerce_list(value, max_items=8):
        timestamp = None
        if isinstance(item, dict):
            timestamp = frame_id_to_timestamp(item.get("frame_id"), labeled_fps)
            if timestamp is None:
                timestamp = parse_timestamp(item.get("timestamp") or item.get("time"))
        else:
            timestamp = frame_id_to_timestamp(item, labeled_fps)
            if timestamp is None:
                timestamp = parse_timestamp(item)
        if timestamp is not None and timestamp not in timestamps:
            timestamps.append(round(max(0.0, float(timestamp)), 3))
    return timestamps


def first_present(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def normalize_order_marker(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    ordinal_words = {"first": "1", "second": "2", "third": "3", "fourth": "4", "last": "last"}
    return ordinal_words.get(text, text)


def visual_referent_hint(current_user_message: str) -> str | None:
    match = re.search(r"visual referent to resolve\s*:\s*(.+)", current_user_message or "", flags=re.IGNORECASE)
    if not match:
        return None
    hint = match.group(1).strip()
    return hint or None


def sanitize_target_region_for_detail(target_region: Any, event_type: Any) -> Any:
    if target_region in (None, ""):
        return target_region
    text = str(target_region)
    if "point" not in str(event_type or "").lower():
        return text
    lowered = text.lower()
    for marker in [", specifically", "; specifically", " specifically "]:
        idx = lowered.find(marker)
        if idx > 0:
            return text[:idx].strip().rstrip(",;:")
    return text


def clean_event_keyframes(ref: dict[str, Any], labeled_fps: float, max_items: int = 3) -> list[dict[str, Any]]:
    keyframes = []
    for keyframe in coerce_list(ref.get("best_keyframes") or ref.get("keyframes"), max_items=max_items):
        if not isinstance(keyframe, dict):
            continue
        timestamp = frame_id_to_timestamp(keyframe.get("frame_id"), labeled_fps)
        if timestamp is None:
            timestamp = parse_timestamp(keyframe.get("timestamp") or keyframe.get("time"))
        keyframes.append(
            {
                "frame_id": keyframe.get("frame_id"),
                "timestamp": timestamp,
                "target_region": keyframe.get("target_region") or ref.get("target_region"),
                "reason": keyframe.get("reason"),
            }
        )

    if not keyframes:
        anchor_timestamp = parse_timestamp(
            first_present(ref, ["anchor_timestamp", "best_timestamp", "timestamp", "time"])
        )
        if anchor_timestamp is not None:
            keyframes.append(
                {
                    "frame_id": ref.get("frame_id"),
                    "timestamp": anchor_timestamp,
                    "target_region": ref.get("target_region"),
                    "reason": ref.get("boundary_reason") or ref.get("reason"),
                }
            )
    return keyframes


def clean_candidate_event(candidate: dict[str, Any], labeled_fps: float) -> dict[str, Any]:
    event_order = first_present(candidate, ["event_order", "candidate_order", "order", "request_order"])
    user_referent = str(candidate.get("referent") or candidate.get("user_referent") or candidate.get("target") or "")
    ordinal = candidate.get("ordinal")
    event_type = normalize_event_type(candidate.get("event_type"), ordinal, user_referent)
    event_time_range = parse_event_time_range(candidate)
    keyframes = clean_event_keyframes(candidate, labeled_fps)
    sequence_timestamps = parse_timestamp_list(
        candidate.get("sequence_timestamps") or candidate.get("ordered_timestamps") or candidate.get("frame_sequence"),
        labeled_fps,
    )
    if not sequence_timestamps and keyframes:
        sequence_timestamps = [round(float(kf["timestamp"]), 3) for kf in keyframes if kf.get("timestamp") is not None]
    return {
        "event_order": event_order,
        "event_type": event_type,
        "ordinal": ordinal,
        "event_time_range": event_time_range,
        "time_range": candidate.get("time_range"),
        "anchor_timestamp": parse_timestamp(first_present(candidate, ["anchor_timestamp", "best_timestamp"])),
        "target_region": sanitize_target_region_for_detail(candidate.get("target_region"), event_type),
        "detail_needed": coerce_list(candidate.get("detail_needed"), max_items=8),
        "sequence_timestamps": sequence_timestamps,
        "downstream_instruction": candidate.get("downstream_instruction")
        or candidate.get("vision_instruction")
        or candidate.get("next_model_instruction"),
        "keyframes": keyframes,
        "boundary_reason": candidate.get("boundary_reason") or candidate.get("reason"),
        "uncertainty": candidate.get("uncertainty"),
    }


def clean_candidate_events(observation: dict[str, Any], labeled_fps: float) -> list[dict[str, Any]]:
    raw_candidates = observation.get("candidate_events") or observation.get("candidates") or []
    if not isinstance(raw_candidates, list):
        raw_candidates = [raw_candidates]
    cleaned = []
    for candidate in raw_candidates:
        if isinstance(candidate, dict):
            cleaned.append(clean_candidate_event(candidate, labeled_fps))
    return cleaned


def selected_candidate_event(
    candidate_events: list[dict[str, Any]],
    selected_order: Any,
) -> dict[str, Any] | None:
    if not candidate_events:
        return None
    marker = normalize_order_marker(selected_order)
    if marker is not None:
        for candidate in candidate_events:
            if normalize_order_marker(candidate.get("event_order")) == marker:
                return candidate
        if marker.isdigit():
            idx = int(marker) - 1
            if 0 <= idx < len(candidate_events):
                return candidate_events[idx]
    return candidate_events[0]


def candidate_to_referent(
    candidate: dict[str, Any],
    current_user_message: str,
    selection_rule: Any,
) -> dict[str, Any]:
    user_referent = str(visual_referent_hint(current_user_message) or candidate.get("user_referent") or current_user_message)
    event_type = candidate.get("event_type") or normalize_event_type(None, candidate.get("ordinal"), user_referent)
    return {
        "user_referent": user_referent,
        "event_type": event_type,
        "ordinal": candidate.get("ordinal"),
        "selected_event_order": candidate.get("event_order"),
        "selection_rule": selection_rule,
        "event_time_range": candidate.get("event_time_range"),
        "time_range": candidate.get("time_range"),
        "target_region": sanitize_target_region_for_detail(candidate.get("target_region"), event_type),
        "detail_needed": candidate.get("detail_needed") or ["identify anchor"],
        "sequence_timestamps": candidate.get("sequence_timestamps") or [],
        "downstream_instruction": clean_downstream_instruction(
            candidate.get("downstream_instruction"),
            user_referent,
            event_type,
        ),
        "keyframes": candidate.get("keyframes") or [],
        "uncertainty": candidate.get("uncertainty"),
        "selection_boundary_reason": candidate.get("boundary_reason"),
    }


def evenly_spaced(start: float, end: float, count: int) -> list[float]:
    if count <= 1 or end <= start:
        return [round(max(0.0, start), 3)]
    step = (end - start) / (count - 1)
    return [round(max(0.0, start + step * idx), 3) for idx in range(count)]


def append_unique_timestamp(items: list[float], value: float) -> None:
    rounded = round(max(0.0, float(value)), 3)
    if rounded not in items:
        items.append(rounded)


def limit_timestamps(items: list[float], max_frames: int) -> list[float]:
    if max_frames <= 0:
        return []
    if len(items) <= max_frames:
        return items
    if max_frames == 1:
        return [items[0]]

    middle_slots = max_frames - 2
    head_slots = middle_slots // 2
    tail_slots = middle_slots - head_slots
    middle = items[1:-1]
    limited = [items[0]]
    for value in middle[:head_slots]:
        append_unique_timestamp(limited, value)
    for value in middle[-tail_slots:] if tail_slots else []:
        append_unique_timestamp(limited, value)
    append_unique_timestamp(limited, items[-1])
    return limited


def sample_timestamps_from_range(
    start: float,
    end: float,
    fps: float,
    max_frames: int,
    boundary_offset: float,
) -> list[float]:
    if max_frames <= 0:
        return []
    start = max(0.0, float(start))
    end = max(start, float(end))
    effective_fps = max(0.1, float(fps))
    interval = 1.0 / effective_fps
    offset = max(0.0, float(boundary_offset))

    timestamps: list[float] = []
    if offset:
        append_unique_timestamp(timestamps, start - offset)

    current = start
    while current <= end + 1e-6:
        append_unique_timestamp(timestamps, current)
        current += interval

    if offset:
        append_unique_timestamp(timestamps, end + offset)

    return limit_timestamps(timestamps, max_frames)


def first_keyframe_timestamp(referent: dict[str, Any]) -> float | None:
    for keyframe in referent.get("keyframes", []):
        if isinstance(keyframe, dict) and keyframe.get("timestamp") is not None:
            return float(keyframe["timestamp"])
    return None


def sample_timestamps_around_anchor(
    start: float,
    end: float,
    anchor: float,
    fps: float,
    max_frames: int,
) -> list[float]:
    if max_frames <= 0:
        return []
    start = max(0.0, float(start))
    end = max(start, float(end))
    anchor = min(max(float(anchor), start), end)
    effective_fps = max(0.1, float(fps))
    interval = 1.0 / effective_fps

    timestamps = [anchor]
    step = 1
    while len(timestamps) < max_frames:
        added = False
        left = anchor - interval * step
        right = anchor + interval * step
        if left > start + 1e-6:
            append_unique_timestamp(timestamps, left)
            added = True
        elif left <= start + 1e-6:
            append_unique_timestamp(timestamps, start)
        if len(timestamps) >= max_frames:
            break
        if right < end - 1e-6:
            append_unique_timestamp(timestamps, right)
            added = True
        elif right >= end - 1e-6:
            append_unique_timestamp(timestamps, end)
        if not added and (start in timestamps or round(start, 3) in timestamps) and (end in timestamps or round(end, 3) in timestamps):
            break
        step += 1

    return sorted(timestamps)


def event_sequence_timestamps(
    referent: dict[str, Any],
    max_frames: int,
    window_seconds: float,
    sample_fps: float,
    boundary_offset: float,
) -> list[float]:
    event_range = referent.get("event_time_range") or {}
    start = event_range.get("start") if isinstance(event_range, dict) else None
    end = event_range.get("end") if isinstance(event_range, dict) else None
    anchor = first_keyframe_timestamp(referent)
    if start is not None and end is not None and float(end) > float(start):
        sample_start = max(0.0, float(start) - max(0.0, float(boundary_offset)))
        sample_end = float(end) + max(0.0, float(boundary_offset))
        if anchor is not None:
            return sample_timestamps_around_anchor(sample_start, sample_end, anchor, sample_fps, max_frames)
        return sample_timestamps_from_range(float(start), float(end), sample_fps, max_frames, boundary_offset)

    explicit = referent.get("sequence_timestamps") or referent.get("ordered_timestamps")
    timestamps = [parse_timestamp(item) for item in coerce_list(explicit, max_items=max_frames)]
    timestamps = [round(max(0.0, float(item)), 3) for item in timestamps if item is not None]
    if timestamps:
        return timestamps[:max_frames]

    center = anchor if anchor is not None else start or end
    if center is None:
        return []
    half = max(0.0, window_seconds / 2.0)
    return evenly_spaced(max(0.0, float(center) - half), float(center) + half, max_frames)


def clean_aura_plan(aura_response: dict[str, Any], current_user_message: str, labeled_fps: float) -> dict[str, Any]:
    observation = aura_observation_payload(aura_response)
    referent_hint = visual_referent_hint(current_user_message)
    candidate_events: list[dict[str, Any]] = []
    selected_event_order = None
    selection_rule = None
    visual_reference_type = None
    selected_candidate: dict[str, Any] | None = None
    if isinstance(observation, dict):
        candidate_events = clean_candidate_events(observation, labeled_fps)
        selected_event_order = first_present(
            observation,
            ["selected_event_order", "selected_candidate_order", "selected_request_order", "selected_order"],
        )
        selection_rule = observation.get("selection_rule")
        visual_reference_type = observation.get("visual_reference_type")
        selected_candidate = selected_candidate_event(candidate_events, selected_event_order)

    raw_refs = []
    if isinstance(observation, dict):
        raw_refs = observation.get("referents") or observation.get("resolved_referents") or observation.get("visual_referents") or []
    if not isinstance(raw_refs, list):
        raw_refs = [raw_refs]

    cleaned_refs = []
    for ref in raw_refs:
        if not isinstance(ref, dict):
            continue
        user_referent = str(ref.get("referent") or ref.get("user_referent") or current_user_message)
        ordinal = ref.get("ordinal")
        event_type = normalize_event_type(ref.get("event_type"), ordinal, user_referent)
        event_time_range = parse_event_time_range(ref)
        sequence_timestamps = parse_timestamp_list(
            ref.get("sequence_timestamps") or ref.get("ordered_timestamps") or ref.get("frame_sequence"),
            labeled_fps,
        )
        keyframes = clean_event_keyframes(ref, labeled_fps)

        if not sequence_timestamps and keyframes:
            sequence_timestamps = [round(float(kf["timestamp"]), 3) for kf in keyframes if kf.get("timestamp") is not None]

        cleaned_refs.append(
            {
                "user_referent": user_referent,
                "event_type": event_type,
                "ordinal": ordinal,
                "selected_event_order": ref.get("selected_event_order") or selected_event_order,
                "selection_rule": ref.get("selection_rule") or selection_rule,
                "event_time_range": event_time_range,
                "time_range": ref.get("time_range"),
                "target_region": sanitize_target_region_for_detail(
                    ref.get("target_region") or (keyframes[0].get("target_region") if keyframes else None),
                    event_type,
                ),
                "detail_needed": coerce_list(ref.get("detail_needed"), max_items=8),
                "sequence_timestamps": sequence_timestamps,
                "downstream_instruction": clean_downstream_instruction(
                    ref.get("downstream_instruction") or ref.get("vision_instruction") or ref.get("next_model_instruction"),
                    user_referent,
                    event_type,
                ),
                "keyframes": keyframes,
                "uncertainty": ref.get("uncertainty"),
            }
        )

    if selected_candidate:
        selected_ref = candidate_to_referent(selected_candidate, current_user_message, selection_rule)
        if cleaned_refs:
            existing = cleaned_refs[0]
            selected_ref.update(
                {
                    "user_referent": referent_hint or existing.get("user_referent") or selected_ref.get("user_referent"),
                    "event_type": existing.get("event_type") or selected_ref.get("event_type"),
                    "ordinal": existing.get("ordinal") or selected_ref.get("ordinal"),
                    "detail_needed": existing.get("detail_needed") or selected_ref.get("detail_needed"),
                    "downstream_instruction": existing.get("downstream_instruction")
                    or selected_ref.get("downstream_instruction"),
                    "uncertainty": existing.get("uncertainty") or selected_ref.get("uncertainty"),
                }
            )
        cleaned_refs = [selected_ref]
    else:
        cleaned_refs = cleaned_refs[:1]

    return {
        "current_visual_request": (
            observation.get("current_visual_request") or observation.get("current_request")
            if isinstance(observation, dict)
            else current_user_message
        ),
        "visual_reference_type": visual_reference_type,
        "selection_rule": selection_rule,
        "candidate_events": candidate_events,
        "selected_event_order": selected_event_order,
        "referents": cleaned_refs,
        "uncertainties": observation.get("uncertainties") if isinstance(observation, dict) else None,
    }


def parse_vision_text(text: str) -> Any:
    content = strip_qwen_reasoning_prefix(text)
    parsed = extract_json_object(content)
    if parsed is not None:
        return parsed
    return {"raw_text": content, "raw_model_content": text} if content != text else {"raw_text": text}


def strip_qwen_reasoning_prefix(text: str) -> str:
    if not isinstance(text, str):
        return ""
    if "</think>" not in text:
        return text
    return text.rsplit("</think>", 1)[-1].lstrip()


def clean_vision_detail(detail: Any) -> dict[str, Any]:
    if not isinstance(detail, dict):
        detail = {"raw_text": str(detail)}
    cleaned = dict(detail)
    if "confidence" in cleaned:
        cleaned["confidence"] = normalize_confidence(cleaned.get("confidence"))
    if str(cleaned.get("uncertainty")).lower() in {"none", "null", ""}:
        cleaned["uncertainty"] = None
    return cleaned


def infer_visual_key(referent: dict[str, Any] | None, current_user_message: str = "") -> str:
    text = " ".join(
        str(value or "")
        for value in (
            (referent or {}).get("user_referent"),
            (referent or {}).get("target_region"),
            (referent or {}).get("downstream_instruction"),
            current_user_message,
        )
    ).lower()
    if "category" in text or "section" in text or "title" in text:
        return "category"
    if "ingredient" in text:
        return "ingredient_name"
    if "recipe" in text:
        return "recipe_name"
    if "set meal" in text or "set_meal" in text:
        return "set_meal_name"
    if "dish" in text or "menu item" in text or "food" in text:
        return "dish_name"
    if "product" in text or "item" in text:
        return "product_name"
    return "visible_region"


def canonicalize_visual_value(value: str) -> str:
    text = str(value or "").strip().strip(",.;:")
    if not text:
        return text
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9 '&/().,-]*?)(?=\s*[\u3400-\u9fff])", text)
    if match:
        ascii_prefix = match.group(1).strip().strip(",.;:")
        if ascii_prefix:
            return ascii_prefix
    return text


def extract_json_string_field(raw_text: str, field_name: str) -> str | None:
    pattern = rf'"{re.escape(field_name)}"\s*:\s*"([^"]*)'
    match = re.search(pattern, raw_text or "", flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).replace("\\n", " ").strip()


def enrich_detail_from_raw_text(
    detail: dict[str, Any],
    referent: dict[str, Any],
    current_user_message: str,
) -> dict[str, Any]:
    if primary_visual_key_values(detail):
        return detail
    raw_text = str(detail.get("raw_text") or detail.get("raw_model_content") or "")
    target_identity = str(detail.get("target_identity") or "").strip()
    if not target_identity:
        target_identity = extract_json_string_field(raw_text, "target_identity") or ""
    target_identity = canonicalize_visual_value(target_identity)
    if not target_identity:
        return detail

    key = infer_visual_key(referent, current_user_message)
    enriched = dict(detail)
    enriched["target_identity"] = target_identity
    enriched["visual_key_values"] = [
        {
            "key": key,
            "value": target_identity,
            "confidence": "medium",
            "evidence": "Recovered target_identity from an incomplete detail-model response.",
        }
    ]
    enriched["parse_warning"] = "detail response was incomplete or not valid JSON; visual_key_values were recovered from target_identity"
    return enriched


def extract_visual_key_values(detail: Any) -> list[dict[str, Any]]:
    if not isinstance(detail, dict):
        return []
    raw_items = detail.get("visual_key_values") or detail.get("key_values") or detail.get("keyword_pairs") or []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []

    cleaned = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        value = item.get("value")
        if key not in ALLOWED_VISUAL_KEYS or value in (None, ""):
            continue
        cleaned.append(
            {
                "key": key,
                "value": str(value),
                "confidence": normalize_confidence(item.get("confidence")),
                "evidence": item.get("evidence"),
            }
        )
    return cleaned


def primary_visual_key_values(detail: Any) -> list[dict[str, Any]]:
    items = extract_visual_key_values(detail)
    if not isinstance(detail, dict) or not items:
        return items

    target_identity = str(detail.get("target_identity") or "").strip()
    if not target_identity:
        return items[:1]

    target_lower = target_identity.lower()
    exact_matches = [item for item in items if str(item.get("value") or "").strip().lower() == target_lower]
    if exact_matches:
        return exact_matches[:1]

    containing_matches = [
        item
        for item in items
        if target_lower in str(item.get("value") or "").strip().lower()
        or str(item.get("value") or "").strip().lower() in target_lower
    ]
    if containing_matches:
        return containing_matches[:1]

    first = items[0]
    return [
        {
            "key": first.get("key"),
            "value": target_identity,
            "confidence": first.get("confidence") or normalize_confidence(detail.get("confidence")) or "medium",
            "evidence": first.get("evidence") or detail.get("spatial_evidence") or "target_identity selected by the vision reader",
        }
    ]


def call_qwen_video_event_localizer(prompt: str, video_path: Path, args: argparse.Namespace) -> tuple[Any, str, Any]:
    from openai import OpenAI

    api_key, base_url, model = qwen_vl_env(args, stage="event")
    generation = qwen_generation_config(args, "event")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.qwen_timeout)
    video_url = qwen_video_url(video_path, base_url, args)
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "video_url", "video_url": {"url": video_url}, "fps": args.qwen_video_fps},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=generation["temperature"],
        max_tokens=generation["max_tokens"],
        extra_body=qwen_extra_body(generation, base_url),
    )
    text = response.choices[0].message.content or ""
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return raw, text, parse_vision_text(text)


def call_qwen_frame_event_localizer(prompt: str, frame_records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[Any, str, Any]:
    from openai import OpenAI

    api_key, base_url, model = qwen_vl_env(args, stage="event")
    generation = qwen_generation_config(args, "event")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.qwen_timeout)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for item in frame_records:
        frame_id = item.get("frame_id")
        timestamp = item.get("timestamp")
        path = Path(item["path"])
        content.append({"type": "text", "text": f"{frame_id}: timestamp={timestamp}s file={path.name}"})
        content.append({"type": "image_url", "image_url": {"url": qwen_image_url(path, base_url)}})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=generation["temperature"],
        max_tokens=generation["max_tokens"],
        extra_body=qwen_extra_body(generation, base_url),
    )
    text = response.choices[0].message.content or ""
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return raw, text, parse_vision_text(text)


def call_qwen_vl_sequence(prompt: str, frame_paths: list[Path], args: argparse.Namespace) -> tuple[Any, str, Any]:
    from openai import OpenAI

    api_key, base_url, model = qwen_vl_env(args, stage="detail")
    generation = qwen_generation_config(args, "detail")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.qwen_timeout)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for idx, frame_path in enumerate(frame_paths, start=1):
        content.append({"type": "text", "text": f"Frame {idx}: {frame_path.name}"})
        content.append({"type": "image_url", "image_url": {"url": qwen_image_url(frame_path, base_url)}})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=generation["temperature"],
        max_tokens=generation["max_tokens"],
        extra_body=qwen_extra_body(generation, base_url),
    )
    text = response.choices[0].message.content or ""
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return raw, text, parse_vision_text(text)


def compact_observation(plan: dict[str, Any], details: list[dict[str, Any]]) -> dict[str, Any]:
    visual_key_values = []
    for item in details:
        for kv in primary_visual_key_values(item.get("clean_detail")):
            if kv not in visual_key_values:
                visual_key_values.append(kv)
    return {
        "observer": "visual_event_qwen_sequence",
        "current_visual_request": plan.get("current_visual_request"),
        "visual_key_values": visual_key_values,
        "visual_referents": [
            {
                "user_referent": ref.get("user_referent"),
                "event_type": ref.get("event_type"),
                "ordinal": ref.get("ordinal"),
                "event_time_range": ref.get("event_time_range"),
                "time_range": ref.get("time_range"),
                "target_region": ref.get("target_region"),
                "downstream_instruction": ref.get("downstream_instruction"),
                "uncertainty": ref.get("uncertainty"),
            }
            for ref in plan.get("referents", [])
        ],
        "detail_evidence": [
            {
                "user_referent": item.get("user_referent"),
                "mode": item.get("detail_mode"),
                "anchor_timestamp": item.get("anchor_timestamp"),
                "sampling_strategy": item.get("sampling_strategy"),
                "timestamps": item.get("timestamps"),
                "sample_fps": item.get("sample_fps"),
                "boundary_offset": item.get("boundary_offset"),
                "frame_paths": item.get("frame_paths"),
                "target_region": item.get("target_region"),
                "details": item.get("clean_detail"),
            }
            for item in details
        ],
        "uncertainties": plan.get("uncertainties"),
    }


def compact_trace(trace: dict[str, Any]) -> dict[str, Any]:
    stages = trace.get("stages", {})
    event_stage = stages.get("event_localizer", {})
    vision_stage = stages.get("vision_details", [])
    compact_details = []
    for item in vision_stage if isinstance(vision_stage, list) else []:
        compact_details.append(
            {
                "referent_index": item.get("referent_index"),
                "status": item.get("status"),
                "detail_mode": item.get("detail_mode"),
                "qwen_base_url": item.get("qwen_base_url"),
                "qwen_model": item.get("qwen_model"),
                "generation": item.get("generation"),
                "extra_body": item.get("extra_body"),
                "user_referent": item.get("user_referent"),
                "anchor_timestamp": item.get("anchor_timestamp"),
                "sampling_strategy": item.get("sampling_strategy"),
                "timestamps": item.get("timestamps"),
                "target_region": item.get("target_region"),
                "sample_fps": item.get("sample_fps"),
                "boundary_offset": item.get("boundary_offset"),
                "scene_description": item.get("scene_description"),
                "frame_resize": item.get("frame_resize"),
                "frame_paths": item.get("frame_paths"),
                "elapsed_seconds": item.get("elapsed_seconds"),
                "error": item.get("error"),
                "clean_detail": item.get("clean_detail"),
            }
        )

    request = trace.get("request", {})
    compact = {
        "schema_version": "visual_observer_trace_compact_v2",
        "created_at": trace.get("created_at"),
        "status": trace.get("status"),
        "experiment_id": trace.get("experiment_id"),
        "experiment_timestamp": trace.get("experiment_timestamp"),
        "experiment_cache_dir": trace.get("experiment_cache_dir"),
        "request": {
            "task_id": request.get("task_id"),
            "request_key": request.get("request_key"),
            "scenario": request.get("scenario"),
            "video_path": request.get("video_path"),
            "image_description": request.get("image_description"),
            "current_user_message": request.get("current_user_message"),
        },
        "scene_description": trace.get("scene_description"),
        "stages": {
            "labeled_video": stages.get("labeled_video"),
            "event_localizer": {
                "backend": event_stage.get("backend"),
                "configured_backend": event_stage.get("configured_backend"),
                "backend_selection_reason": event_stage.get("backend_selection_reason"),
                "qwen_base_url": event_stage.get("qwen_base_url"),
                "qwen_model": event_stage.get("qwen_model"),
                "generation": event_stage.get("generation"),
                "extra_body": event_stage.get("extra_body"),
                "elapsed_seconds": event_stage.get("elapsed_seconds"),
                "video_path": event_stage.get("video_path"),
                "video_url": event_stage.get("video_url"),
                "video_fps": event_stage.get("video_fps"),
                "event_frame_fps": event_stage.get("event_frame_fps"),
                "event_max_frames": event_stage.get("event_max_frames"),
                "event_frames": event_stage.get("event_frames"),
                "clean_plan": event_stage.get("clean_plan"),
            },
            "vision_details": compact_details,
        },
        "observation": trace.get("observation"),
        "elapsed_seconds": trace.get("elapsed_seconds"),
    }
    if "error" in trace:
        compact["error"] = trace.get("error")
    if "traceback" in trace:
        compact["traceback"] = trace.get("traceback")
    return compact


def trace_for_storage(trace: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return trace if args.trace_detail == "full" else compact_trace(trace)


def run_observation(payload: dict[str, Any], args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    started = time.time()
    trace: dict[str, Any] = {
        "schema_version": "visual_observer_trace_v2",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "request": payload,
        "stages": {},
    }
    try:
        video_path = payload.get("video_path")
        if not video_path:
            return 400, {"error": "video_path is required"}

        scenario = str(payload.get("scenario") or "")
        task_id = str(payload.get("task_id") or "")
        current_user_message = str(payload.get("current_user_message") or "")
        image_description = str(payload.get("image_description") or "")
        scene_description = build_scene_description(scenario, image_description)
        trace["scene_description"] = scene_description
        event_backend, backend_selection_reason = effective_event_backend(args, current_user_message)

        local_video = local_video_path(video_path)
        cache_dir = experiment_cache_dir(Path(args.cache_dir), payload)
        ensure_run_dirs(cache_dir)
        trace["experiment_id"] = cache_dir.name
        trace["experiment_timestamp"] = cache_dir.parent.name
        trace["experiment_cache_dir"] = str(cache_dir)

        labeled_video: Path | None = None
        if event_backend == "qwen_frames":
            labeled_video = make_labeled_video(local_video, cache_dir, args.labeled_fps, args.fontfile, args.refresh)
            trace["stages"]["labeled_video"] = {"path": str(labeled_video), "fps": args.labeled_fps}
        else:
            trace["stages"]["labeled_video"] = {
                "path": None,
                "fps": None,
                "skipped": "qwen_video uses the original video directly.",
            }

        event_start = time.time()
        if event_backend == "qwen_frames":
            assert labeled_video is not None
            _, event_base_url, event_model = qwen_vl_env(args, stage="event")
            event_frame_dir = cache_dir / "event_frames"
            event_frames = sample_event_frames(
                labeled_video,
                scenario,
                task_id,
                event_frame_dir,
                args.event_frame_fps,
                args.event_max_frames,
                args.frame_max_side,
            )
            prompt = build_qwen_event_prompt(current_user_message, image_description, scenario)
            raw_response, text, parsed = call_qwen_frame_event_localizer(prompt, event_frames, args)
            event_data = {"observation": parsed if isinstance(parsed, dict) else {"raw": text}}
            clean_plan = clean_aura_plan(event_data, current_user_message, args.labeled_fps)
            event_stage = {
                "backend": "qwen_frames",
                "configured_backend": args.event_localizer_backend,
                "backend_selection_reason": backend_selection_reason,
                "qwen_base_url": event_base_url,
                "qwen_model": event_model,
                "generation": qwen_generation_config(args, "event"),
                "extra_body": qwen_extra_body(qwen_generation_config(args, "event"), event_base_url),
                "elapsed_seconds": round(time.time() - event_start, 3),
                "event_frame_fps": args.event_frame_fps,
                "event_max_frames": args.event_max_frames,
                "frame_max_side": args.frame_max_side,
                "event_frames": [
                    {
                        "frame_id": item.get("frame_id"),
                        "timestamp": item.get("timestamp"),
                        "path": str(item.get("path")),
                    }
                    for item in event_frames
                ],
                "prompt": prompt,
                "raw_response": raw_response,
                "raw_text": text,
                "parsed_response": parsed,
                "clean_plan": clean_plan,
            }
        elif event_backend == "qwen_video":
            _, event_base_url, event_model = qwen_vl_env(args, stage="event")
            prompt = build_qwen_video_event_prompt(current_user_message, image_description, scenario)
            raw_response, text, parsed = call_qwen_video_event_localizer(prompt, local_video, args)
            event_data = {"observation": parsed if isinstance(parsed, dict) else {"raw": text}}
            clean_plan = clean_aura_plan(event_data, current_user_message, args.labeled_fps)
            event_stage = {
                "backend": "qwen_video",
                "configured_backend": args.event_localizer_backend,
                "backend_selection_reason": backend_selection_reason,
                "qwen_base_url": event_base_url,
                "qwen_model": event_model,
                "generation": qwen_generation_config(args, "event"),
                "extra_body": qwen_extra_body(qwen_generation_config(args, "event"), event_base_url),
                "elapsed_seconds": round(time.time() - event_start, 3),
                "video_path": str(local_video),
                "video_url": qwen_video_url(local_video, event_base_url, args),
                "video_fps": args.qwen_video_fps,
                "request_level_fps": None,
                "prompt": prompt,
                "raw_response": raw_response,
                "raw_text": text,
                "parsed_response": parsed,
                "clean_plan": clean_plan,
            }
        trace["stages"]["event_localizer"] = event_stage
        trace["status"] = "event_completed"
        write_scenario_trace(cache_dir, payload, trace_for_storage(trace, args))

        detail_records = []
        frame_dir = cache_dir / "keyframes"
        request_key = str(payload.get("request_key") or "")
        for ref_idx, referent in enumerate(clean_plan.get("referents", [])):
            anchor_timestamp = first_keyframe_timestamp(referent)
            timestamps = event_sequence_timestamps(
                referent,
                args.sequence_frames,
                args.sequence_window_seconds,
                args.detail_sample_fps,
                args.detail_boundary_offset,
            )
            if not timestamps:
                continue
            frame_paths = []
            for frame_idx, timestamp in enumerate(timestamps):
                frame_name = keyframe_output_name(
                    scenario,
                    task_id,
                    float(timestamp),
                    ref_idx,
                    frame_idx,
                    request_key,
                )
                frame_paths.append(extract_frame(local_video, float(timestamp), frame_dir, frame_name, None))

            prompt = build_qwen_sequence_prompt(referent, current_user_message, image_description, scenario)
            _, detail_base_url, detail_model = qwen_vl_env(args, stage="detail")
            detail_record = {
                "referent_index": ref_idx,
                "status": "pending",
                "detail_mode": "qwen_sequence",
                "qwen_base_url": detail_base_url,
                "qwen_model": detail_model,
                "generation": qwen_generation_config(args, "detail"),
                "extra_body": qwen_extra_body(qwen_generation_config(args, "detail"), detail_base_url),
                "user_referent": referent.get("user_referent"),
                "anchor_timestamp": anchor_timestamp,
                "sampling_strategy": "anchor_within_event_range" if anchor_timestamp is not None else "event_range",
                "timestamps": timestamps,
                "target_region": referent.get("target_region"),
                "sample_fps": args.detail_sample_fps,
                "boundary_offset": args.detail_boundary_offset,
                "scene_description": scene_description,
                "frame_resize": "none",
                "frame_paths": [str(path) for path in frame_paths],
                "prompt": prompt,
                "elapsed_seconds": None,
                "error": None,
                "raw_response": None,
                "raw_text": "",
                "parsed_detail": None,
                "clean_detail": None,
            }
            detail_records.append(detail_record)
            trace["stages"]["vision_details"] = detail_records
            trace["status"] = "detail_pending"
            write_scenario_trace(cache_dir, payload, trace_for_storage(trace, args))

            detail_start = time.time()
            raw_response = None
            text = ""
            parsed: Any = None
            try:
                raw_response, text, parsed = call_qwen_vl_sequence(prompt, frame_paths, args)
                clean_detail = enrich_detail_from_raw_text(
                    clean_vision_detail(parsed),
                    referent,
                    current_user_message,
                )
                detail_error = None
            except Exception as exc:
                clean_detail = {
                    "error": str(exc),
                    "uncertainty": "QwenVL sequence understanding failed for this event segment.",
                }
                detail_error = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            detail_record.update(
                {
                    "status": "completed" if detail_error is None else "failed",
                    "elapsed_seconds": round(time.time() - detail_start, 3),
                    "error": detail_error,
                    "raw_response": raw_response,
                    "raw_text": text,
                    "parsed_detail": parsed,
                    "clean_detail": clean_detail,
                }
            )
            trace["status"] = "detail_completed" if detail_error is None else "detail_failed"
            write_scenario_trace(cache_dir, payload, trace_for_storage(trace, args))

        trace["stages"]["vision_details"] = detail_records
        trace["status"] = "completed"
        observation = compact_observation(clean_plan, detail_records)
        trace["observation"] = observation
        trace["elapsed_seconds"] = round(time.time() - started, 3)
        trace_path = write_scenario_trace(cache_dir, payload, trace_for_storage(trace, args))

        return 200, {
            "task_id": task_id,
            "video_path": video_path,
            "observer": "visual_event_qwen_sequence",
            "event_localizer_backend": args.event_localizer_backend,
            "effective_event_localizer_backend": event_backend,
            "experiment_id": cache_dir.name,
            "experiment_cache_dir": str(cache_dir),
            "elapsed_seconds": trace["elapsed_seconds"],
            "trace_path": str(trace_path),
            "observation": observation,
        }
    except Exception as exc:
        trace["error"] = str(exc)
        trace["traceback"] = traceback.format_exc()
        try:
            cache_dir = experiment_cache_dir(Path(args.cache_dir), payload)
            ensure_run_dirs(cache_dir)
            write_scenario_trace(cache_dir, payload, trace_for_storage(trace, args))
        except Exception:
            pass
        traceback.print_exc()
        return 500, {"error": str(exc), "traceback": traceback.format_exc()}


class ObserverHandler(BaseHTTPRequestHandler):
    args: argparse.Namespace

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"error": "not found"})
            return
        _, qwen_event_base_url, qwen_event_model = qwen_vl_env(self.args, stage="event")
        _, qwen_detail_base_url, qwen_detail_model = qwen_vl_env(self.args, stage="detail")
        event_localizer: dict[str, Any] = {
            "backend": self.args.event_localizer_backend,
            "temporal_event_backend": self.args.temporal_event_backend,
            "temporal_frame_fps": self.args.event_frame_fps,
            "temporal_max_frames": self.args.event_max_frames,
            "temporal_frame_max_side": self.args.frame_max_side,
        }
        if self.args.event_localizer_backend == "qwen_video":
            event_localizer.update(
                {
                    "input": "original_video",
                    "base_url": qwen_event_base_url,
                    "model": qwen_event_model,
                    "video_url_mode": self.args.qwen_video_url_mode,
                    "video_url_base": self.args.video_url_base,
                    "video_fps": self.args.qwen_video_fps,
                    "request_level_fps": None,
                    "generation": qwen_generation_config(self.args, "event"),
                }
            )
        elif self.args.event_localizer_backend == "qwen_frames":
            event_localizer.update(
                {
                    "input": "sampled_frames",
                    "base_url": qwen_event_base_url,
                    "model": qwen_event_model,
                    "generation": qwen_generation_config(self.args, "event"),
                    "sample_fps": self.args.event_frame_fps,
                    "max_frames": self.args.event_max_frames,
                    "frame_max_side": self.args.frame_max_side,
                }
            )
        self._send_json(
            200,
            {
                "status": "ok",
                "observer": "visual_event_qwen_sequence",
                "stages": {
                    "event_localizer": event_localizer,
                    "detail_recognizer": {
                        "input": "ordered_original_size_frames",
                        "base_url": qwen_detail_base_url,
                        "model": qwen_detail_model,
                        "generation": qwen_generation_config(self.args, "detail"),
                        "max_frames": self.args.sequence_frames,
                        "sample_fps": self.args.detail_sample_fps,
                        "boundary_offset_seconds": self.args.detail_boundary_offset,
                        "frame_resize": "none",
                        "frame_format": "png",
                    },
                },
            },
        )

    def do_POST(self) -> None:
        if self.path != "/observe":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            self._send_json(400, {"error": f"invalid JSON: {exc}"})
            return
        status, response = run_observation(payload, self.args)
        self._send_json(status, response)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {format % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visual observer server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--event_localizer_backend", choices=["qwen_frames", "qwen_video"], default="qwen_video")
    parser.add_argument(
        "--temporal_event_backend",
        choices=["inherit", "qwen_frames", "qwen_video"],
        default=os.environ.get("OBSERVER_TEMPORAL_EVENT_BACKEND", "qwen_frames"),
        help="Backend used for temporal/ordinal action requests when the configured event backend is qwen_video.",
    )
    parser.add_argument("--cache_dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--labeled_fps", type=float, default=2.0)
    parser.add_argument("--fontfile", default=DEFAULT_FONT)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--aura_timeout", type=float, default=600.0)
    parser.add_argument("--event_frame_fps", type=float, default=2.0)
    parser.add_argument("--event_max_frames", type=int, default=4)
    parser.add_argument("--frame_max_side", type=int, default=1024)
    parser.add_argument("--sequence_frames", type=int, default=8)
    parser.add_argument("--detail_sample_fps", type=float, default=2.0)
    parser.add_argument("--detail_boundary_offset", type=float, default=0.25)
    parser.add_argument("--sequence_window_seconds", type=float, default=1.5)
    parser.add_argument("--qwen_api_base_url", default=None)
    parser.add_argument("--qwen_api_key", default=None)
    parser.add_argument("--qwen_model", default=None)
    parser.add_argument("--qwen_event_api_base_url", default=None)
    parser.add_argument("--qwen_event_api_key", default=None)
    parser.add_argument("--qwen_event_model", default=None)
    parser.add_argument("--qwen_detail_api_base_url", default=None)
    parser.add_argument("--qwen_detail_api_key", default=None)
    parser.add_argument("--qwen_detail_model", default=None)
    parser.add_argument(
        "--qwen_video_url_mode",
        choices=["auto", "local", "url"],
        default=os.environ.get("OBSERVER_QWEN_VIDEO_URL_MODE", "auto"),
        help="Video URL mode for qwen_video event localization. auto uses file:// for local APIs and public URLs for remote APIs.",
    )
    parser.add_argument(
        "--video_url_base",
        default=os.environ.get("OBSERVER_VIDEO_URL_BASE") or os.environ.get("VIDEO_URL_BASE"),
        help="Base URL for public videos when qwen_video_url_mode uses url. The video filename is appended and URL-encoded.",
    )
    parser.add_argument(
        "--video_url_mapping",
        default=os.environ.get("VIDEO_URL_MAPPING"),
        help="JSON mapping from video filename to public URL for qwen_video online mode.",
    )
    parser.add_argument(
        "--qwen_video_fps",
        type=float,
        default=float(os.environ.get("OBSERVER_QWEN_VIDEO_FPS", "2")),
        help="fps field sent with OpenAI-compatible video_url input.",
    )
    parser.add_argument("--qwen_temperature", type=float, default=0.0)
    parser.add_argument("--qwen_max_tokens", type=int, default=1024)
    parser.add_argument("--qwen_timeout", type=float, default=float(os.environ.get("OBSERVER_QWEN_TIMEOUT", "300")))
    parser.add_argument("--qwen_enable_thinking", action="store_true")
    parser.add_argument("--qwen_thinking_budget", type=int, default=None)
    parser.add_argument(
        "--qwen_thinking",
        choices=["on", "off"],
        default="off",
        help="Global Qwen thinking switch. Stage-specific --qwen_event_thinking/--qwen_detail_thinking can override it.",
    )
    parser.add_argument(
        "--qwen_include_reasoning",
        action="store_true",
        help="Include separated reasoning in vLLM responses when the server runs with --reasoning-parser qwen3.",
    )
    parser.add_argument("--qwen_event_temperature", type=float, default=None)
    parser.add_argument("--qwen_event_max_tokens", type=int, default=None)
    parser.add_argument("--qwen_event_thinking_budget", type=int, default=None)
    parser.add_argument(
        "--qwen_event_thinking",
        choices=["inherit", "on", "off"],
        default="inherit",
        help="Thinking switch for the event localizer stage. Overrides --qwen_thinking when not inherit.",
    )
    parser.add_argument("--qwen_event_enable_thinking", action="store_true", default=None)
    parser.add_argument(
        "--qwen_event_high_resolution_images",
        choices=["on", "off"],
        default=os.environ.get("OBSERVER_EVENT_HIGH_RESOLUTION_IMAGES", "off"),
        help="Send DashScope/OpenAI-compatible vl_high_resolution_images=true for event image-frame requests.",
    )
    parser.add_argument("--qwen_detail_temperature", type=float, default=None)
    parser.add_argument("--qwen_detail_max_tokens", type=int, default=None)
    parser.add_argument("--qwen_detail_thinking_budget", type=int, default=None)
    parser.add_argument(
        "--qwen_detail_thinking",
        choices=["inherit", "on", "off"],
        default="inherit",
        help="Thinking switch for the detail recognizer stage. Overrides --qwen_thinking when not inherit.",
    )
    parser.add_argument("--qwen_detail_enable_thinking", action="store_true", default=None)
    parser.add_argument(
        "--qwen_detail_high_resolution_images",
        choices=["on", "off"],
        default=os.environ.get("OBSERVER_DETAIL_HIGH_RESOLUTION_IMAGES", "off"),
        help="Send DashScope/OpenAI-compatible vl_high_resolution_images=true for detail image-sequence requests.",
    )
    parser.add_argument(
        "--trace_detail",
        choices=["compact", "full"],
        default="compact",
        help="Store compact observer traces by default; use full to include raw prompts and raw model responses.",
    )
    return parser.parse_args()


def main() -> None:
    load_env_file(PROJECT_ROOT / ".env")
    args = parse_args()
    ObserverHandler.args = args
    server = ThreadingHTTPServer((args.host, args.port), ObserverHandler)
    print(f"Visual observer running on http://{args.host}:{args.port}")
    print(f"Event localizer backend: {args.event_localizer_backend}")
    print(f"Cache dir: {args.cache_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
