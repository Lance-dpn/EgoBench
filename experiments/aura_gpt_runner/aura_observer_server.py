#!/usr/bin/env python3
"""
HTTP wrapper for local AURA video observation.

Run this script with the AURA Python environment. It does not modify or start
the original AURA realtime socket/ASR/TTS stack; it imports the video sampling
and vLLM initialization utilities, then exposes a narrow /observe endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
import numpy as np


AURA_ROOT = Path(os.environ.get("AURA_ROOT", "/mnt/sda/dpn/AURA")).resolve()
if str(AURA_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(AURA_ROOT))

import Qwen3_VL_online_streaming_v2_ContextManaged as aura  # noqa: E402
from vllm import SamplingParams  # noqa: E402


DEFAULT_MODEL_PATH = (
    "/home/dpn/.cache/huggingface/hub/models--aurateam--AURA/"
    "snapshots/88ee550629fcb4d84428cdbfb346d07f01ea6e03"
)


SYSTEM_PROMPT = """You are a precise visual observer for an embodied-agent benchmark.
Your only job is to inspect the provided video and describe visible evidence that
helps a separate service agent resolve the user's request. Use the service-side
visual grounding instruction as role context, but do not act as the service
agent. Do not call tools, do not invent database facts, and do not use hidden
labels. Return JSON only."""


USER_PROMPT_TEMPLATE = """Inspect the video for the current service-agent dialogue turn.

Scenario: {scenario}
Service-side prompt excerpt for visual grounding:
{service_instruction}

Current user message that must be visually grounded:
{current_user_message}

Return a compact JSON object with these fields:
- current_request: the current visual question/request in your own words.
- resolved_referents: map each visual reference in the current user message to concrete visible evidence, including pointing order, hand, side, row/column, category, product/menu text, and confidence.
- relevant_visible_text: exact visible menu/product/category text that helps answer this turn.
- spatial_context: layout and relative positions needed for this turn, such as left/right/top/bottom/third/last.
- action_sequence: chronological pointing or selection actions relevant to this turn.
- uncertainties: what remains unclear; be explicit if a name cannot be read.

Focus only on the current user message. Inspect the full video independently for
this turn, and do not use prior dialogue as visual evidence.
Do not summarize unrelated future task steps.
Do not use hidden user-task instructions, expected answers, or ground-truth labels.
Keep the JSON concise. Use null for unknown values. Do not include markdown."""


def is_url(path: str) -> bool:
    parsed = urlparse(path)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def fetch_url_to_temp(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix or ".mp4"
    fd, temp_path = tempfile.mkstemp(prefix="aura_observe_", suffix=suffix)
    os.close(fd)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            with open(temp_path, "wb") as f:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
    return temp_path


def limit_frames(video_tuple: tuple[Any, dict[str, Any]], max_frames: int) -> tuple[Any, dict[str, Any]]:
    video_array, metadata = video_tuple
    if max_frames <= 0 or video_array is None or video_array.shape[0] <= max_frames:
        return video_tuple
    indices = np.linspace(0, video_array.shape[0] - 1, max_frames).round().astype(int)
    limited = video_array[indices]
    new_metadata = dict(metadata or {})
    new_metadata["total_num_frames"] = int(limited.shape[0])
    if "frames_indices" in new_metadata:
        original_indices = new_metadata["frames_indices"]
        new_metadata["frames_indices"] = [original_indices[i] for i in indices.tolist()]
    if "duration" in new_metadata and new_metadata.get("fps"):
        new_metadata["duration"] = float(limited.shape[0]) / float(new_metadata["fps"])
    return limited, new_metadata


def extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def build_vllm_inputs(prompt: str, video_tuple: tuple[Any, dict[str, Any]]) -> dict[str, Any]:
    full_prompt = (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>"
        f"<|im_start|>user\n<|vision_start|><|video_pad|><|vision_end|>\n"
        f"{prompt}<|im_end|><|im_start|>assistant\n"
    )
    return {
        "prompt": full_prompt,
        "multi_modal_data": {"video": [video_tuple]},
    }


async def generate_observation(app: web.Application, prompt: str, video_tuple: tuple[Any, dict[str, Any]]) -> str:
    request_id = f"aura-observe-{uuid.uuid4().hex}"
    sampling = SamplingParams(
        temperature=app["args"].temperature,
        max_tokens=app["args"].max_tokens,
    )
    full_text = ""
    async for response in aura.async_engine.generate(
        prompt=build_vllm_inputs(prompt, video_tuple),
        sampling_params=sampling,
        request_id=request_id,
    ):
        if response.outputs and hasattr(response.outputs[0], "text"):
            full_text = response.outputs[0].text or full_text
    return full_text.strip()


async def observe(request: web.Request) -> web.Response:
    payload = await request.json()
    video_path = payload.get("video_path")
    if not video_path:
        return web.json_response({"error": "video_path is required"}, status=400)

    args = request.app["args"]
    task_id = payload.get("task_id", "")
    scenario = payload.get("scenario", "")
    service_instruction = payload.get(
        "service_instruction",
        payload.get(
            "instruction",
            "Ground the current user's visible references for the service agent using only video evidence and dialogue context.",
        ),
    )
    current_user_message = payload.get("current_user_message", "")
    temp_path = None
    started = time.time()

    try:
        source_path = video_path
        if is_url(video_path):
            temp_path = await fetch_url_to_temp(video_path)
            source_path = temp_path
        if not os.path.exists(source_path):
            return web.json_response({"error": f"video not found: {video_path}"}, status=404)

        video_tuple = aura.downsample_video_to_numpy(
            source_path,
            target_fps=args.target_fps,
            resize=args.video_resize,
        )
        if not video_tuple or video_tuple[0] is None:
            return web.json_response({"error": f"failed to decode video: {video_path}"}, status=422)
        video_tuple = limit_frames(video_tuple, args.max_frames)

        prompt = USER_PROMPT_TEMPLATE.format(
            scenario=scenario,
            service_instruction=service_instruction,
            current_user_message=current_user_message,
        )
        raw_text = await generate_observation(request.app, prompt, video_tuple)
        parsed = extract_json_object(raw_text)
        elapsed = round(time.time() - started, 3)

        return web.json_response(
            {
                "task_id": task_id,
                "video_path": video_path,
                "model": args.model,
                "target_fps": args.target_fps,
                "max_frames": args.max_frames,
                "elapsed_seconds": elapsed,
                "observation": parsed if parsed is not None else {"raw": raw_text},
                "raw_observation": raw_text,
            },
            dumps=lambda obj: json.dumps(obj, ensure_ascii=False),
        )
    except Exception as exc:
        traceback.print_exc()
        return web.json_response(
            {"error": str(exc), "error_repr": repr(exc), "traceback": traceback.format_exc()},
            status=500,
        )
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok" if aura.async_engine is not None else "loading",
            "model": request.app["args"].model,
        }
    )


async def startup(app: web.Application) -> None:
    args = app["args"]
    aura.setup_silent_token_id(args.model)
    await aura.init_async_engine(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AURA video observation HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--model", default=os.environ.get("AURA_MODEL_PATH", DEFAULT_MODEL_PATH))
    parser.add_argument("--target-fps", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=32)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--video-resize", action="store_true")

    parser.add_argument("--tensor-parallel-size", type=int, default=1)
    parser.add_argument("--pipeline-parallel-size", type=int, default=1)
    parser.add_argument("--max-model-len", type=int, default=65536)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.85)
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument("--max-images-per-prompt", type=int, default=256)
    parser.add_argument("--enable-expert-parallel", action="store_true", default=False)
    parser.add_argument("--kv-offloading-size", type=int, default=None)
    parser.add_argument("--mm-encoder-attn-backend", default=None)
    parser.add_argument("--mm-encoder-tp-mode", default=None)
    parser.add_argument("--disable-hybrid-kv-cache-manager", action="store_true")
    parser.add_argument("--block-size", type=int, default=None)
    parser.add_argument("--cache-dtype", default="auto")
    parser.add_argument("--prefix-caching-hash-algo", default=None)
    parser.add_argument("--max-num-batched-tokens", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = web.Application(client_max_size=1024 * 1024)
    app["args"] = args
    app.router.add_get("/health", health)
    app.router.add_post("/observe", observe)
    app.on_startup.append(startup)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
