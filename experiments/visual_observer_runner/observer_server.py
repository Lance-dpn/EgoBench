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
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
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


AURA_EVENT_LOCALIZER_PROMPT = """You are the first-stage event localizer in a two-model visual observer.

Task:
Given the current user message and a labeled low-fps video, locate the visual
event that grounds the user's request. Then write a concise instruction for the
next vision model.

Your responsibility:
- Resolve event timing and visual references only: action order, selected or
  referenced entity, interaction state, spatial relation, visible region, and
  any region that a downstream vision reader should inspect.
- Return one short event time segment and 3-4 frame timestamps from that segment,
  ordered from early to late.
- Write a concise downstream_instruction that tells the next vision model what
  visual detail to identify for this referent.

Rules:
- Use the video, not outside knowledge.
- For ordinal language, follow the relevant visible order in the video.
- For spatial language, follow the visible spatial layout.
- Do not output entity names, prices, nutrition, allergens, country/origin,
  discounts, cart/order state, or actions to take.
- Do not solve the database question. Only localize the visual event and guide
  the next vision model.
- Prefer one best referent. If truly uncertain between visual events, return up
  to three candidate referents ordered by confidence.
- Timestamps may be any decimal seconds from the original video. Do not round
  them to 0.5-second steps unless that is the best visible estimate.

Return JSON only:
{
  "current_visual_request": "...",
  "referents": [
    {
      "referent": "...",
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "ordinal": "first|second|third|last|null",
      "event_time_range": {"start": 5.37, "end": 6.42},
      "time_range": "5.37-6.42s",
      "target_region": "coarse region in the frame",
  "detail_needed": ["identify anchor"],
      "downstream_instruction": "Identify the visible anchor for this localized referent.",
      "best_keyframes": [
        {
          "frame_id": "F12",
          "timestamp": 6.0,
          "target_region": "coarse region in the frame",
          "reason": "short visual reason"
        }
      ],
      "uncertainty": null
    }
  ],
  "uncertainties": null
}

If the video frame label is visible, set frame_id to that exact label, for
example "F12"."""


QWEN_FRAME_EVENT_LOCALIZER_PROMPT = """You are the first-stage event localizer in a two-model visual observer.

Task:
Given the current user message and a sequence of sampled video frames, locate
the visual event(s) that ground the user's request. The attached images are
ordered from early to late. Each image is preceded by a frame id and timestamp.

Your responsibility:
- Resolve event timing and visual references only: action order, selected or
  referenced entity, interaction state, spatial relation, visible region, and
  any region that a downstream vision reader should inspect.
- If the user request explicitly mentions multiple visual objects, comparisons,
  or relations, return one referent per required object in the same order as
  mentioned by the user.
- Prefer one referent only when the user request contains one visual referent.
- Write a concise downstream_instruction that tells the next vision model what
  visual detail to identify for this referent.

Rules:
- Use only the attached frames and their timestamps, not outside knowledge.
- For ordinal language, follow the relevant visible order in the frame sequence.
- For spatial language, follow the visible spatial layout.
- Do not output entity names, prices, nutrition, allergens, country/origin,
  discounts, cart/order state, or actions to take.
- Do not solve the database question. Only localize the visual event and guide
  the next vision model.
- Timestamps may be any decimal seconds from the original video. Do not round
  them to 0.5-second steps unless that is the best visible estimate.

Current user message:
{current_user_message}

Scene description:
{image_description}

Return JSON only:
{{
  "current_visual_request": "...",
  "referents": [
    {{
      "referent": "...",
      "request_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "ordinal": "first|second|third|last|null",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "time_range": "5.37-6.42s",
      "target_region": "coarse region in the frame",
      "detail_needed": ["identify anchor"],
      "downstream_instruction": "Identify the visible anchor for this localized referent.",
      "best_keyframes": [
        {{
          "frame_id": "F012",
          "timestamp": 6.0,
          "target_region": "coarse region in the frame",
          "reason": "short visual reason"
        }}
      ],
      "uncertainty": null
    }}
  ],
  "uncertainties": null
}}"""


QWEN_VIDEO_EVENT_LOCALIZER_PROMPT = """You are the first-stage event localizer in a two-model visual observer.

Task:
Given the current user message and the original video, locate the visual
event(s) that ground the user's request. The video is provided directly; do not
assume any externally controlled frame rate.

Your responsibility:
- Resolve event timing and visual references only: action order, selected or
  referenced entity, interaction state, spatial relation, visible region, and
  any region that a downstream vision reader should inspect.
- If the user request explicitly mentions multiple visual objects, comparisons,
  or relations, return one referent per required object in the same order as
  mentioned by the user.
- Prefer one referent only when the user request contains one visual referent.
- Write a concise downstream_instruction that tells the next vision model what
  visual detail to identify for this referent.

Rules:
- Use only the video, not outside knowledge.
- For ordinal language, follow the relevant visible order in the video.
- For spatial language, follow the visible spatial layout.
- Do not output entity names, prices, nutrition, allergens, country/origin,
  discounts, cart/order state, or actions to take.
- Do not solve the database question. Only localize the visual event and guide
  the next vision model.
- All timestamps must be seconds from the start of the original video.
- Timestamps may be any decimal seconds from the original video. Do not round
  them to 0.5-second steps unless that is the best visible estimate.

Current user message:
{current_user_message}

Scene description:
{image_description}

Return JSON only:
{{
  "current_visual_request": "...",
  "referents": [
    {{
      "referent": "...",
      "request_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "ordinal": "first|second|third|last|null",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "time_range": "5.37-6.42s",
      "target_region": "coarse region in the frame",
      "detail_needed": ["identify anchor"],
      "downstream_instruction": "Identify the visible anchor for this localized referent.",
      "best_keyframes": [
        {{
          "timestamp": 6.0,
          "target_region": "coarse region in the frame",
          "reason": "short visual reason"
        }}
      ],
      "uncertainty": null
    }}
  ],
  "uncertainties": null
}}"""


QWEN_SEQUENCE_DETAIL_PROMPT = """You are the second-stage vision reader in a two-model visual observer.

Current user request:
{current_user_message}

Scene description:
{image_description}

The first-stage localizer has already localized the relevant video event. The attached images are
ordered from early to late and come from this event segment.

Localized event summary:
- referent: {user_referent}
- event type: {event_type}
- time range: {time_range}
- target region: {target_region}
- instruction: {downstream_instruction}

Your job:
Use the ordered image sequence to identify the single most likely visible anchor
requested by the localizer. Trust the event timing and do not reinterpret which
occurrence or spatial relation is intended unless the image sequence itself is
ambiguous.
Combine evidence across all attached frames before deciding. The target text or
object may be occluded, blurred, cropped, or unreadable in a single frame; track
the same localized target through the sequence and use the clearest frame(s) for
the final identity.

Boundaries:
- Use only visible text and visual evidence in these images.
- Focus on the target region and the object/person/state involved in the
  localized event.
- Choose one best target_identity. Do not output top-k alternatives.
- visual_key_values must contain exactly one item for the primary visible anchor
  of this localized referent.
- Put other readable text in visible_text only. Do not promote neighboring or
  background anchors into visual_key_values.
- Do not output price, discount, tax, nutrition, allergens, taste,
  country/origin, cart state, or other database attributes as key/value pairs.
- If the target cannot be identified, set target_identity to null, return an
  empty visual_key_values list, and explain the ambiguity in uncertainty.

Return JSON only:
{{
  "target_identity": "... or null",
  "visible_text": [],
  "visual_key_values": [
    {{
      "key": "product_name|dish_name|ingredient_name|recipe_name|category|set_meal_name|visible_region",
      "value": "... or null",
      "confidence": "high|medium|low",
      "evidence": "which frame(s), visible text, action/order cues, region, color, shape, or spatial relation"
    }}
  ],
  "spatial_evidence": "...",
  "uncertainty": null
}}"""


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
        return slugify_name(match.group(1), "task"), f"turn{match.group(2)}"
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
            "schema_version": "aura_qwenvl_observer_scenario_trace_v1",
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


def keyframe_output_name(scenario: str, task_id: str, timestamp: float, referent_index: int, frame_index: int) -> str:
    scene_part = slugify_name(scenario or "scene", "scene")
    task_part = slugify_name(task_id or "task", "task")
    return f"{scene_part}-{task_part}-t{timestamp:.2f}-r{referent_index:02d}-k{frame_index:02d}.png"


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
    return {
        "temperature": args.qwen_temperature if temperature is None else temperature,
        "max_tokens": args.qwen_max_tokens if max_tokens is None else max_tokens,
        "enable_thinking": args.qwen_enable_thinking if enable_thinking is None else enable_thinking,
    }


def aura_event_url(args: argparse.Namespace) -> str:
    return args.aura_event_url or args.aura_observer_url or "http://127.0.0.1:18081/observe"


def build_planner_user_message(current_user_message: str, image_description: str) -> str:
    if not image_description:
        return current_user_message
    return (
        "Short scene note:\n"
        f"{image_description}\n\n"
        "Visual request:\n"
        f"{current_user_message}"
    )


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
    if start is not None and end is not None and float(end) > float(start):
        return sample_timestamps_from_range(float(start), float(end), sample_fps, max_frames, boundary_offset)

    explicit = referent.get("sequence_timestamps") or referent.get("ordered_timestamps")
    timestamps = [parse_timestamp(item) for item in coerce_list(explicit, max_items=max_frames)]
    timestamps = [round(max(0.0, float(item)), 3) for item in timestamps if item is not None]
    if timestamps:
        return timestamps[:max_frames]

    keyframe_times = [
        float(kf["timestamp"])
        for kf in referent.get("keyframes", [])
        if isinstance(kf, dict) and kf.get("timestamp") is not None
    ]
    center = keyframe_times[0] if keyframe_times else start or end
    if center is None:
        return []
    half = max(0.0, window_seconds / 2.0)
    return evenly_spaced(max(0.0, float(center) - half), float(center) + half, max_frames)


def clean_aura_plan(aura_response: dict[str, Any], current_user_message: str, labeled_fps: float) -> dict[str, Any]:
    observation = aura_observation_payload(aura_response)
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

        keyframes = []
        for keyframe in coerce_list(ref.get("best_keyframes") or ref.get("keyframes"), max_items=3):
            if not isinstance(keyframe, dict):
                continue
            timestamp = frame_id_to_timestamp(keyframe.get("frame_id"), labeled_fps)
            if timestamp is None:
                timestamp = parse_timestamp(keyframe.get("timestamp"))
            keyframes.append(
                {
                    "frame_id": keyframe.get("frame_id"),
                    "timestamp": timestamp,
                    "target_region": keyframe.get("target_region") or ref.get("target_region"),
                    "reason": keyframe.get("reason"),
                }
            )

        if not sequence_timestamps and keyframes:
            sequence_timestamps = [round(float(kf["timestamp"]), 3) for kf in keyframes if kf.get("timestamp") is not None]

        cleaned_refs.append(
            {
                "user_referent": user_referent,
                "event_type": event_type,
                "ordinal": ordinal,
                "event_time_range": event_time_range,
                "time_range": ref.get("time_range"),
                "target_region": ref.get("target_region") or (keyframes[0].get("target_region") if keyframes else None),
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

    return {
        "current_visual_request": (
            observation.get("current_visual_request") or observation.get("current_request")
            if isinstance(observation, dict)
            else current_user_message
        ),
        "referents": cleaned_refs,
        "uncertainties": observation.get("uncertainties") if isinstance(observation, dict) else None,
    }


def parse_vision_text(text: str) -> Any:
    parsed = extract_json_object(text)
    return parsed if parsed is not None else {"raw_text": text}


def clean_vision_detail(detail: Any) -> dict[str, Any]:
    if not isinstance(detail, dict):
        detail = {"raw_text": str(detail)}
    cleaned = dict(detail)
    if "confidence" in cleaned:
        cleaned["confidence"] = normalize_confidence(cleaned.get("confidence"))
    if str(cleaned.get("uncertainty")).lower() in {"none", "null", ""}:
        cleaned["uncertainty"] = None
    return cleaned


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


def build_downstream_instruction(referent: dict[str, Any]) -> str:
    if referent.get("downstream_instruction"):
        return str(referent["downstream_instruction"])
    referent_text = referent.get("user_referent") or "the localized visual referent"
    return f"These frames show {referent_text}. Identify the specific visible anchor involved in this event."


def build_qwen_sequence_prompt(referent: dict[str, Any], current_user_message: str, image_description: str) -> str:
    event_range = referent.get("event_time_range") or {}
    if isinstance(event_range, dict) and (event_range.get("start") is not None or event_range.get("end") is not None):
        time_range = f"{event_range.get('start')}s-{event_range.get('end')}s"
    else:
        time_range = referent.get("time_range")
    return QWEN_SEQUENCE_DETAIL_PROMPT.format(
        current_user_message=current_user_message,
        image_description=image_description or "N/A",
        user_referent=referent.get("user_referent"),
        event_type=referent.get("event_type"),
        time_range=time_range,
        target_region=referent.get("target_region"),
        downstream_instruction=build_downstream_instruction(referent),
    )


def build_qwen_event_prompt(current_user_message: str, image_description: str) -> str:
    return QWEN_FRAME_EVENT_LOCALIZER_PROMPT.format(
        current_user_message=current_user_message,
        image_description=image_description or "N/A",
    )


def build_qwen_video_event_prompt(current_user_message: str, image_description: str) -> str:
    return QWEN_VIDEO_EVENT_LOCALIZER_PROMPT.format(
        current_user_message=current_user_message,
        image_description=image_description or "N/A",
    )


def call_qwen_video_event_localizer(prompt: str, video_path: Path, args: argparse.Namespace) -> tuple[Any, str, Any]:
    from openai import OpenAI

    api_key, base_url, model = qwen_vl_env(args, stage="event")
    generation = qwen_generation_config(args, "event")
    client = OpenAI(api_key=api_key, base_url=base_url)
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "video_url", "video_url": {"url": local_video_file_url(video_path)}},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=generation["temperature"],
        max_tokens=generation["max_tokens"],
        extra_body={"enable_thinking": generation["enable_thinking"]},
    )
    text = response.choices[0].message.content
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return raw, text, parse_vision_text(text)


def call_qwen_frame_event_localizer(prompt: str, frame_records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[Any, str, Any]:
    from openai import OpenAI

    api_key, base_url, model = qwen_vl_env(args, stage="event")
    generation = qwen_generation_config(args, "event")
    client = OpenAI(api_key=api_key, base_url=base_url)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for item in frame_records:
        frame_id = item.get("frame_id")
        timestamp = item.get("timestamp")
        path = Path(item["path"])
        content.append({"type": "text", "text": f"{frame_id}: timestamp={timestamp}s file={path.name}"})
        content.append({"type": "image_url", "image_url": {"url": local_image_data_url(path)}})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=generation["temperature"],
        max_tokens=generation["max_tokens"],
        extra_body={"enable_thinking": generation["enable_thinking"]},
    )
    text = response.choices[0].message.content
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return raw, text, parse_vision_text(text)


def call_qwen_vl_sequence(prompt: str, frame_paths: list[Path], args: argparse.Namespace) -> tuple[Any, str, Any]:
    from openai import OpenAI

    api_key, base_url, model = qwen_vl_env(args, stage="detail")
    generation = qwen_generation_config(args, "detail")
    client = OpenAI(api_key=api_key, base_url=base_url)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for idx, frame_path in enumerate(frame_paths, start=1):
        content.append({"type": "text", "text": f"Frame {idx}: {frame_path.name}"})
        content.append({"type": "image_url", "image_url": {"url": local_image_data_url(frame_path)}})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=generation["temperature"],
        max_tokens=generation["max_tokens"],
        extra_body={"enable_thinking": generation["enable_thinking"]},
    )
    text = response.choices[0].message.content
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
    event_stage = stages.get("event_localizer") or stages.get("aura_event_localizer", {})
    vision_stage = stages.get("vision_details", [])
    compact_details = []
    for item in vision_stage if isinstance(vision_stage, list) else []:
        compact_details.append(
            {
                "referent_index": item.get("referent_index"),
                "detail_mode": item.get("detail_mode"),
                "qwen_base_url": item.get("qwen_base_url"),
                "qwen_model": item.get("qwen_model"),
                "user_referent": item.get("user_referent"),
                "timestamps": item.get("timestamps"),
                "target_region": item.get("target_region"),
                "sample_fps": item.get("sample_fps"),
                "boundary_offset": item.get("boundary_offset"),
                "frame_paths": item.get("frame_paths"),
                "elapsed_seconds": item.get("elapsed_seconds"),
                "error": item.get("error"),
                "clean_detail": item.get("clean_detail"),
            }
        )

    request = trace.get("request", {})
    compact = {
        "schema_version": "aura_qwenvl_observer_trace_compact_v1",
        "created_at": trace.get("created_at"),
        "experiment_id": trace.get("experiment_id"),
        "experiment_timestamp": trace.get("experiment_timestamp"),
        "experiment_cache_dir": trace.get("experiment_cache_dir"),
        "request": {
            "task_id": request.get("task_id"),
            "scenario": request.get("scenario"),
            "video_path": request.get("video_path"),
            "image_description": request.get("image_description"),
            "current_user_message": request.get("current_user_message"),
        },
        "stages": {
            "labeled_video": stages.get("labeled_video"),
            "event_localizer": {
                "backend": event_stage.get("backend"),
                "qwen_base_url": event_stage.get("qwen_base_url"),
                "qwen_model": event_stage.get("qwen_model"),
                "elapsed_seconds": event_stage.get("elapsed_seconds"),
                "event_frame_fps": event_stage.get("event_frame_fps"),
                "event_max_frames": event_stage.get("event_max_frames"),
                "event_frames": event_stage.get("event_frames"),
                "clean_plan": event_stage.get("clean_plan"),
            },
            "aura_event_localizer": {
                "backend": event_stage.get("backend"),
                "elapsed_seconds": event_stage.get("elapsed_seconds"),
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
        "schema_version": "aura_qwenvl_observer_trace_v1",
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

        local_video = local_video_path(video_path)
        cache_dir = experiment_cache_dir(Path(args.cache_dir), payload)
        ensure_run_dirs(cache_dir)
        trace["experiment_id"] = cache_dir.name
        trace["experiment_timestamp"] = cache_dir.parent.name
        trace["experiment_cache_dir"] = str(cache_dir)

        labeled_video: Path | None = None
        if args.event_localizer_backend in {"aura_http", "qwen_frames"}:
            labeled_video = make_labeled_video(local_video, cache_dir, args.labeled_fps, args.fontfile, args.refresh)
            trace["stages"]["labeled_video"] = {"path": str(labeled_video), "fps": args.labeled_fps}
        else:
            trace["stages"]["labeled_video"] = {
                "path": None,
                "fps": None,
                "skipped": "qwen_video uses the original video directly.",
            }

        event_start = time.time()
        if args.event_localizer_backend == "qwen_frames":
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
            prompt = build_qwen_event_prompt(current_user_message, image_description)
            raw_response, text, parsed = call_qwen_frame_event_localizer(prompt, event_frames, args)
            event_data = {"observation": parsed if isinstance(parsed, dict) else {"raw": text}}
            clean_plan = clean_aura_plan(event_data, current_user_message, args.labeled_fps)
            event_stage = {
                "backend": "qwen_frames",
                "qwen_base_url": event_base_url,
                "qwen_model": event_model,
                "generation": qwen_generation_config(args, "event"),
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
        elif args.event_localizer_backend == "qwen_video":
            _, event_base_url, event_model = qwen_vl_env(args, stage="event")
            prompt = build_qwen_video_event_prompt(current_user_message, image_description)
            raw_response, text, parsed = call_qwen_video_event_localizer(prompt, local_video, args)
            event_data = {"observation": parsed if isinstance(parsed, dict) else {"raw": text}}
            clean_plan = clean_aura_plan(event_data, current_user_message, args.labeled_fps)
            event_stage = {
                "backend": "qwen_video",
                "qwen_base_url": event_base_url,
                "qwen_model": event_model,
                "generation": qwen_generation_config(args, "event"),
                "elapsed_seconds": round(time.time() - event_start, 3),
                "video_path": str(local_video),
                "video_url": local_video_file_url(local_video),
                "request_level_fps": None,
                "prompt": prompt,
                "raw_response": raw_response,
                "raw_text": text,
                "parsed_response": parsed,
                "clean_plan": clean_plan,
            }
        else:
            assert labeled_video is not None
            aura_payload = {
                "task_id": f"{task_id}_aura_event",
                "scenario": scenario,
                "service_instruction": AURA_EVENT_LOCALIZER_PROMPT,
                "video_path": str(labeled_video),
                "current_user_message": build_planner_user_message(current_user_message, image_description),
            }
            aura_response = requests.post(aura_event_url(args), json=aura_payload, timeout=args.aura_timeout)
            aura_response.raise_for_status()
            event_data = aura_response.json()
            clean_plan = clean_aura_plan(event_data, current_user_message, args.labeled_fps)
            event_stage = {
                "backend": "aura_http",
                "elapsed_seconds": round(time.time() - event_start, 3),
                "request": aura_payload,
                "raw_response": event_data,
                "clean_plan": clean_plan,
            }
        trace["stages"]["event_localizer"] = event_stage
        trace["stages"]["aura_event_localizer"] = event_stage

        detail_records = []
        frame_dir = cache_dir / "keyframes"
        for ref_idx, referent in enumerate(clean_plan.get("referents", [])):
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
                frame_name = keyframe_output_name(scenario, task_id, float(timestamp), ref_idx, frame_idx)
                frame_paths.append(extract_frame(local_video, float(timestamp), frame_dir, frame_name, None))

            prompt = build_qwen_sequence_prompt(referent, current_user_message, image_description)
            _, detail_base_url, detail_model = qwen_vl_env(args, stage="detail")
            detail_start = time.time()
            raw_response = None
            text = ""
            parsed: Any = None
            try:
                raw_response, text, parsed = call_qwen_vl_sequence(prompt, frame_paths, args)
                clean_detail = clean_vision_detail(parsed)
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
            detail_records.append(
                {
                    "referent_index": ref_idx,
                    "detail_mode": "qwen_sequence",
                    "qwen_base_url": detail_base_url,
                    "qwen_model": detail_model,
                    "generation": qwen_generation_config(args, "detail"),
                    "user_referent": referent.get("user_referent"),
                    "timestamps": timestamps,
                    "target_region": referent.get("target_region"),
                    "sample_fps": args.detail_sample_fps,
                    "boundary_offset": args.detail_boundary_offset,
                    "frame_resize": "none",
                    "frame_paths": [str(path) for path in frame_paths],
                    "prompt": prompt,
                    "elapsed_seconds": round(time.time() - detail_start, 3),
                    "error": detail_error,
                    "raw_response": raw_response,
                    "raw_text": text,
                    "parsed_detail": parsed,
                    "clean_detail": clean_detail,
                }
            )

        trace["stages"]["vision_details"] = detail_records
        observation = compact_observation(clean_plan, detail_records)
        trace["observation"] = observation
        trace["elapsed_seconds"] = round(time.time() - started, 3)
        trace_path = write_scenario_trace(cache_dir, payload, trace_for_storage(trace, args))

        return 200, {
            "task_id": task_id,
            "video_path": video_path,
            "observer": "visual_event_qwen_sequence",
            "event_localizer_backend": args.event_localizer_backend,
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
        }
        if self.args.event_localizer_backend == "qwen_video":
            event_localizer.update(
                {
                    "input": "original_video",
                    "base_url": qwen_event_base_url,
                    "model": qwen_event_model,
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
        else:
            event_localizer.update(
                {
                    "input": "labeled_low_fps_video",
                    "aura_event_url": aura_event_url(self.args),
                    "labeled_fps": self.args.labeled_fps,
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
    parser.add_argument("--event_localizer_backend", choices=["aura_http", "qwen_frames", "qwen_video"], default="aura_http")
    parser.add_argument("--aura_event_url", default=None)
    parser.add_argument(
        "--aura_observer_url",
        default=None,
        help="Deprecated alias for --aura_event_url.",
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
    parser.add_argument("--qwen_temperature", type=float, default=0.0)
    parser.add_argument("--qwen_max_tokens", type=int, default=1024)
    parser.add_argument("--qwen_enable_thinking", action="store_true")
    parser.add_argument("--qwen_event_temperature", type=float, default=None)
    parser.add_argument("--qwen_event_max_tokens", type=int, default=None)
    parser.add_argument("--qwen_event_enable_thinking", action="store_true", default=None)
    parser.add_argument("--qwen_detail_temperature", type=float, default=None)
    parser.add_argument("--qwen_detail_max_tokens", type=int, default=None)
    parser.add_argument("--qwen_detail_enable_thinking", action="store_true", default=None)
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
    print(f"AURA event URL: {aura_event_url(args)}")
    print(f"Cache dir: {args.cache_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
