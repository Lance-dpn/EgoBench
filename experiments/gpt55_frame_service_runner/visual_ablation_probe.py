"""Run frame-size and reasoning-effort visual probes with service-agent payloads."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.gpt55_frame_service_runner.openai_responses_client import OpenAIResponsesServiceClient
from experiments.gpt55_frame_service_runner.prompts.service import SERVICE_PROMPT_VERSION, build_service_agent_prompt
from experiments.gpt55_frame_service_runner.run_frame_agent import prepare_frames, response_input_items


DEFAULT_QUESTION = (
    "Diagnostic visual-recognition probe. Do not call tools. "
    "Using only the attached restaurant3 timestamped frames, identify the dish name pointed to first "
    "and the dish name pointed to second. Follow the restaurant pointing rule: choose the visible dish "
    "text closest above to the stable fingertip, do not choose text mostly covered by the finger, and "
    "prefer the candidate supported by more frames. Answer exactly one JSON object and no prose: "
    '{"first_pointed_dish_name":"...","second_pointed_dish_name":"...","evidence":"brief"}'
)


def comma_values(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def reasoning_values(text: str) -> list[str]:
    values = []
    for value in comma_values(text):
        normalized = value.lower()
        if normalized == "hight":
            normalized = "high"
        if normalized not in {"none", "low", "medium", "high"}:
            raise argparse.ArgumentTypeError(f"Unsupported reasoning effort: {value}")
        values.append(normalized)
    return values


def int_values(text: str) -> list[int]:
    values = []
    for value in comma_values(text):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid integer value: {value}") from exc
        if parsed <= 0:
            raise argparse.ArgumentTypeError(f"Frame max side must be positive: {value}")
        values.append(parsed)
    return values


def resolve_video(path_text: str) -> Path:
    path = Path(path_text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([PROJECT_ROOT / path, PROJECT_ROOT / "videos" / path.name])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Video not found: {path_text}")


def payload_stats(input_items: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps({"input": input_items}, ensure_ascii=False)
    image_count = 0
    image_chars = 0
    for item in input_items:
        for part in item.get("content", []):
            if part.get("type") == "input_image":
                image_count += 1
                image_chars += len(str(part.get("image_url", "")))
    return {
        "body_mib_without_instructions": round(len(body.encode("utf-8")) / 1024 / 1024, 3),
        "images": image_count,
        "image_data_mib": round(image_chars / 1024 / 1024, 3),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run restaurant3 visual ablation probes.")
    parser.add_argument("--video", default=str(PROJECT_ROOT / "videos" / "restaurant3.mp4"))
    parser.add_argument("--scenario", default="restaurant")
    parser.add_argument("--scenario_number", type=int, default=3)
    parser.add_argument("--frame_max_sides", type=int_values, default=[512, 1024, 1536, 1920])
    parser.add_argument("--reasoning_efforts", type=reasoning_values, default=["none", "low", "medium", "high"])
    parser.add_argument("--frame_fps", type=float, default=2.0)
    parser.add_argument(
        "--frame_rotation",
        choices=["none", "clockwise", "counterclockwise", "180"],
        default="none",
    )
    parser.add_argument("--jpeg_quality", type=int, default=3)
    parser.add_argument("--max_frames", type=int, default=0)
    parser.add_argument("--image_detail", choices=["low", "auto", "high"], default="high")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--output",
        default=str(
            PROJECT_ROOT
            / "experiments"
            / "gpt55_frame_service_runner"
            / "cache"
            / "manual_reasoning_probe"
            / "restaurant3_frame_size_reasoning_ablation.json"
        ),
    )
    parser.add_argument(
        "--frame_cache_dir",
        default=str(PROJECT_ROOT / "experiments" / "gpt55_frame_service_runner" / "cache" / "manual_reasoning_probe"),
    )
    parser.add_argument("--service_model_name", default=os.environ.get("SERVICE_MODEL_NAME") or os.environ.get("OPENAI_MODEL_NAME") or "gpt-5.5")
    parser.add_argument("--service_api_key", default=os.environ.get("SERVICE_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--service_api_base_url", default=os.environ.get("SERVICE_API_BASE_URL") or os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--max_output_tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max_retries", type=int, default=3)
    parser.add_argument("--dry_run", action="store_true", help="Build frames and payload stats without calling the API.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_path = resolve_video(args.video)
    output_path = Path(args.output)

    tool_descriptions = "No tools are available for this diagnostic probe."
    prompt = build_service_agent_prompt(
        tool_descriptions=tool_descriptions,
        scenario=args.scenario,
        scenario_number=args.scenario_number,
    )
    report: dict[str, Any] = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": args.service_model_name,
        "prompt_version": SERVICE_PROMPT_VERSION,
        "scenario": args.scenario,
        "scenario_number": args.scenario_number,
        "video": str(video_path),
        "question": args.question,
        "tool_descriptions": tool_descriptions,
        "system_prompt": prompt,
        "frame_fps": args.frame_fps,
        "frame_rotation": args.frame_rotation,
        "jpeg_quality": args.jpeg_quality,
        "max_frames": args.max_frames,
        "image_detail": args.image_detail,
        "temperature": args.temperature,
        "frame_max_sides": args.frame_max_sides,
        "reasoning_efforts": args.reasoning_efforts,
        "dry_run": bool(args.dry_run),
        "runs": [],
    }
    write_json(output_path, report)

    for frame_max_side in args.frame_max_sides:
        frame_args = argparse.Namespace(
            scenario=args.scenario,
            scenario_number=args.scenario_number,
            frame_cache_dir=str(
                Path(args.frame_cache_dir)
                / f"{video_path.stem}_ablation_{frame_max_side}_rot-{args.frame_rotation}"
            ),
            frame_fps=args.frame_fps,
            frame_max_side=frame_max_side,
            frame_rotation=args.frame_rotation,
            jpeg_quality=args.jpeg_quality,
            max_frames=args.max_frames,
            refresh_frames=False,
        )
        frames = prepare_frames(frame_args, video_path)
        input_items = response_input_items(
            [{"role": "user", "content": args.question}],
            frames=frames,
            attach_frames=True,
            image_detail=args.image_detail,
            frame_header=(
                "The following images are uniformly sampled frames from the task video. "
                "They are in chronological order and each image is preceded by its frame id and timestamp. "
                "Inspect the stable fingertip position and nearby menu text carefully."
            ),
        )
        stats = payload_stats(input_items)

        for reasoning_effort in args.reasoning_efforts:
            for repeat in range(1, args.repeats + 1):
                run: dict[str, Any] = {
                    "frame_max_side": frame_max_side,
                    "reasoning_effort": reasoning_effort,
                    "repeat": repeat,
                    "frame_count": len(frames),
                    "payload": stats,
                    "status": "pending",
                }
                report["runs"].append(run)
                write_json(output_path, report)
                print(
                    f"=== frame_max_side={frame_max_side} reasoning={reasoning_effort} "
                    f"repeat={repeat}/{args.repeats} frames={len(frames)} payload={stats} ===",
                    flush=True,
                )
                if args.dry_run:
                    run["status"] = "dry_run"
                    write_json(output_path, report)
                    continue

                client = OpenAIResponsesServiceClient(
                    model=args.service_model_name,
                    api_key=args.service_api_key,
                    base_url=args.service_api_base_url,
                    temperature=args.temperature,
                    reasoning_effort=reasoning_effort,
                    max_output_tokens=args.max_output_tokens,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                )
                start = time.time()
                try:
                    result = client.create(instructions=prompt, input_items=input_items)
                except Exception as exc:
                    run.update(
                        {
                            "status": "error",
                            "error": str(exc),
                            "elapsed_seconds": round(time.time() - start, 3),
                        }
                    )
                else:
                    run.update(
                        {
                            "status": "ok",
                            "text": result.text,
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "elapsed_seconds": round(time.time() - start, 3),
                        }
                    )
                write_json(output_path, report)

    print(f"Saved ablation report to: {output_path}", flush=True)


if __name__ == "__main__":
    main()
