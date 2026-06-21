#!/usr/bin/env python3
"""Standalone LangGraph GPT-frame service-agent runner for EgoBench."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.gpt55_frame_service_runner.openai_responses_client import OpenAIResponsesServiceClient  # noqa: E402
from experiments.gpt55_frame_service_runner.run_frame_agent import (  # noqa: E402
    DEFAULT_SERVICE_MODEL_NAME,
    DEFAULT_USER_MODEL_NAME,
    call_user_llm_for_runner,
    configure_user_model_env,
    contains_stop_signal,
    frame_metadata,
    init_db,
    load_env_file,
    load_results,
    parse_task_ids,
    prepare_frames,
    resolve_video_path,
    save_results,
)
from experiments.langgraph_service_agent.graph_agent import (  # noqa: E402
    LangGraphFrameServiceAgent,
    LangGraphTurnConfig,
)
from experiments.langgraph_service_agent.prompts import (  # noqa: E402
    LANGGRAPH_SERVICE_PROMPT_VERSION,
    build_langgraph_service_agent_prompt,
)
from run.prompts import USER_TEXT_ONLY_PROMPT_EASY, USER_TURN_SUMMARY_PROMPT  # noqa: E402


load_env_file(PROJECT_ROOT / ".env")


def scenario_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    input_json = PROJECT_ROOT / "scenarios" / "final" / f"{args.scenario}{args.scenario_number}.json"
    tool_json = PROJECT_ROOT / "tools" / args.scenario / f"{args.scenario}_tools.json"
    model_name = args.output_model_name or f"{args.service_model_name}-langgraph"
    output_json = PROJECT_ROOT / "results" / model_name / f"{args.scenario}{args.scenario_number}_easy.json"
    return input_json, tool_json, output_json


def selected_scenarios(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[tuple[int, dict[str, Any]]]:
    if args.task_ids:
        selected: list[tuple[int, dict[str, Any]]] = []
        for task_id in args.task_ids:
            if task_id > len(rows):
                raise ValueError(f"Task id {task_id} is out of range; only {len(rows)} tasks are available.")
            selected.append((task_id, rows[task_id - 1]))
        return selected
    if args.num_tasks > 0:
        rows = rows[: args.num_tasks]
    return list(enumerate(rows, start=1))


def make_user_call(args: argparse.Namespace):
    def call_llm(
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
        preserve_thinking: bool | None = None,
    ) -> tuple[str, int, int]:
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

    return call_llm


def run_simulation(args: argparse.Namespace) -> None:
    configure_user_model_env(args)
    import run.utils as run_utils

    user_call_llm = make_user_call(args)
    official_call_llm = run_utils.call_llm

    def patched_call_llm(
        messages: list[dict[str, Any]],
        agent_type: str = "service",
        service_model_name: str | None = None,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
        preserve_thinking: bool | None = None,
    ) -> tuple[str, int, int]:
        if agent_type == "user":
            return user_call_llm(
                messages,
                temperature=temperature,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
                preserve_thinking=preserve_thinking,
            )
        return official_call_llm(
            messages,
            agent_type=agent_type,
            service_model_name=service_model_name or args.service_model_name,
            enable_thinking=bool(enable_thinking),
        )

    run_utils.call_llm = patched_call_llm

    input_json, tool_json, output_json = scenario_paths(args)
    rows = json.loads(input_json.read_text(encoding="utf-8"))
    tools_list = json.loads(tool_json.read_text(encoding="utf-8"))
    tool_descriptions = json.dumps(tools_list, ensure_ascii=False, indent=2)
    selected = selected_scenarios(rows, args)
    if args.max_turns < 2:
        print(
            "⚠️ [Run Mode] max_turns is below 2. This is a single-turn behavior probe, "
            "not a complete EgoBench task run; full GT accuracy will be artificially low."
        )

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
        "🤖 [LangGraph Service Model] "
        f"model={args.service_model_name}, base_url={args.service_api_base_url or '[default]'}, "
        f"temperature={args.service_temperature}, reasoning_effort={args.service_reasoning_effort}"
    )

    all_results = load_results(str(output_json)) if args.resume else []
    completed_task_ids = {int(result["task_id"]) for result in all_results if "task_id" in result and not result.get("error")}
    if args.resume and completed_task_ids:
        print(f"🔄 [Resume] Skipping completed task ids: {sorted(completed_task_ids)}")

    for task_id, scenario_row in selected:
        if task_id in completed_task_ids:
            continue
        print(f"\n🚀 {'=' * 20} LangGraph Scenario {args.scenario}{args.scenario_number}: {task_id} {'=' * 20}")
        db = init_db(args.scenario, args.scenario_number)
        user_instruction = scenario_row.get("Instruction", "")
        image_description = scenario_row.get("image_description", "")
        video_path = resolve_video_path(scenario_row.get("image_path", ""))
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
            "service_prompt_version": LANGGRAPH_SERVICE_PROMPT_VERSION,
            "service_agent_backend": "langgraph_frame",
            "run_config": {
                "max_turns": args.max_turns,
                "max_inner_tool_rounds": args.max_inner_tool_rounds,
                "max_tool_calls": args.max_tool_calls,
                "summary_user": args.summary_user,
                "multi_agent_user": args.multi_agent_user,
                "selected_by_task_id": bool(args.task_ids),
            },
            "langgraph_trace": [],
            "frame_input": {
                "video_path": str(video_path),
                "frame_fps": args.frame_fps,
                "frame_max_side": args.frame_max_side,
                "frame_rotation": args.frame_rotation,
                "image_detail": args.image_detail,
                "frame_attach_policy": args.frame_attach_policy,
                "frames": frame_metadata(frames),
            },
            "frame_attached_calls": 0,
            "visual_context_requests": 0,
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
        service_agent_sys_prompt = build_langgraph_service_agent_prompt(
            tool_descriptions=tool_descriptions,
            scenario=args.scenario,
            scenario_number=args.scenario_number,
        )
        service_history: list[dict[str, str]] = []
        summarized_history_str = ""
        last_agent_response_for_check = "Dear customer, how can I help you?"
        task_error: Exception | None = None

        for turn in range(args.max_turns):
            user_start = time.time()
            user_reply, _, _ = user_call_llm(
                user_messages,
                temperature=args.user_temperature,
                enable_thinking=args.user_enable_thinking,
                thinking_budget=args.user_thinking_budget,
                preserve_thinking=args.user_preserve_thinking,
            )
            user_time = time.time() - user_start
            history_log["user_response_time_seconds"] += user_time
            evaluation_info = None
            if args.multi_agent_user:
                original_user_reply = user_reply
                check_start = time.time()
                kwargs = {
                    "user_response": original_user_reply,
                    "user_instruction": user_instruction,
                    "image_description": image_description,
                    "multi_agent_user": True,
                    "last_agent_response": last_agent_response_for_check,
                    "history": history_log["dialogue"],
                    "summarized_history": summarized_history_str if args.summary_user else None,
                    "user_mode": "easy",
                }
                user_reply, evaluation_info = run_utils.check_user_contradiction(**kwargs)
                history_log["user_response_time_seconds"] += time.time() - check_start
            print(f"👤 Final User Response: {user_reply}")
            user_log = {"role": "user", "turn": turn, "content": user_reply}
            if evaluation_info:
                user_log["evaluation"] = evaluation_info
            history_log["dialogue"].append(user_log)
            if contains_stop_signal(str(user_reply)):
                print("🛑 Stop signal detected")
                break

            service_history.append({"role": "user", "content": str(user_reply)})
            user_messages.append({"role": "assistant", "content": str(user_reply)})

            try:
                agent = LangGraphFrameServiceAgent(
                    service_client=service_client,
                    instructions=service_agent_sys_prompt,
                    frames=frames,
                    db=db,
                    execute_tool=run_utils.execute_tool,
                    check_tool_call=run_utils.check_tool_call,
                    prior_tool_logs=history_log["tool_calls"],
                    config=LangGraphTurnConfig(
                        turn=turn,
                        latest_user_message=str(user_reply),
                        max_inner_tool_rounds=args.max_inner_tool_rounds,
                        max_tool_calls=args.max_tool_calls - int(history_log["tool_calls_count"]),
                        image_detail=args.image_detail,
                        frame_attach_policy=args.frame_attach_policy,
                        max_visual_context_requests=args.max_visual_context_requests,
                        max_repair_rounds=args.max_repair_rounds,
                        task_instruction=user_instruction,
                        image_description=image_description,
                        enable_visual_resolve=args.enable_visual_resolve,
                        scenario=args.scenario,
                        scenario_number=args.scenario_number,
                    ),
                )
                agent_result = agent.run(service_history)
            except Exception as exc:
                task_error = exc
                history_log["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "turn": turn,
                    "stage": "langgraph_service",
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                }
                print(f"❌ [Task Error] Task {task_id} failed at turn {turn}: {exc}")
                break

            history_log["input_tokens"] += agent_result.input_tokens
            history_log["output_tokens"] += agent_result.output_tokens
            history_log["tool_calls_count"] += agent_result.calls
            history_log["rounds_count"] += agent_result.rounds
            history_log["agent_response_time_seconds"] += agent_result.time
            history_log["tool_calls"].extend(agent_result.tool_logs)
            history_log["dialogue"].extend(agent_result.dialogue_logs)
            history_log["frame_attached_calls"] += agent_result.frame_attached_calls
            history_log["visual_context_requests"] += agent_result.visual_context_requests
            history_log["langgraph_trace"].append({"turn": turn, "events": agent_result.trace})
            service_history = agent_result.updated_history
            last_agent_response_for_check = agent_result.reply

            if not agent_result.dialogue_logs:
                print("🛑 [Turn Stop] LangGraph service did not produce a user-visible final reply.")
                history_log["error"] = {
                    "type": "NoVisibleAgentReply",
                    "message": agent_result.reply,
                    "turn": turn,
                    "stage": "service_final_reply",
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                }
                break

            if args.summary_user:
                prompt = USER_TURN_SUMMARY_PROMPT.format(
                    user_instruction=user_instruction,
                    agent_response=last_agent_response_for_check,
                    user_response=str(user_reply),
                    previous_summary=summarized_history_str if summarized_history_str else "None",
                )
                summary, _, _ = user_call_llm(
                    [{"role": "user", "content": prompt}],
                    temperature=args.user_temperature,
                    enable_thinking=args.user_enable_thinking,
                    thinking_budget=args.user_thinking_budget,
                    preserve_thinking=args.user_preserve_thinking,
                )
                summarized_history_str = f"Turn {turn} Dialogue Summary of completed steps: {summary}\n"

            user_agent_sys_prompt = USER_TEXT_ONLY_PROMPT_EASY.format(
                user_instruction=user_instruction,
                image_description=image_description,
                original_user_response="",
                evaluation_feedback="",
                history_summary=summarized_history_str,
                service_agent_response=last_agent_response_for_check,
            )
            user_messages[0]["content"] = user_agent_sys_prompt
            if args.summary_user:
                user_messages = [
                    {"role": "system", "content": user_agent_sys_prompt},
                    {
                        "role": "user",
                        "content": "Please continue the conversation in the first person according to the original settings based on the summary and latest response.",
                    },
                ]
            else:
                user_messages.append({"role": "user", "content": last_agent_response_for_check})

        history_log["tokens_consumed"] = history_log["input_tokens"] + history_log["output_tokens"]
        history_log["user_turns_count"] = sum(1 for item in history_log["dialogue"] if item.get("role") == "user")
        history_log["agent_turns_count"] = sum(1 for item in history_log["dialogue"] if item.get("role") == "agent")
        history_log["execution_time_seconds"] = round(time.time() - start_time, 3)
        all_results = [r for r in all_results if int(r.get("task_id", -1)) != task_id]
        all_results.append(history_log)
        all_results.sort(key=lambda item: int(item.get("task_id", 10**9)))
        save_results(str(output_json), all_results)
        print(f"💾 [Checkpoint] Saved {len(all_results)} result records to: {output_json}")
        if task_error is not None and not args.continue_on_task_error:
            raise RuntimeError(f"Task {task_id} failed; checkpoint saved to {output_json}") from task_error

    print(f"\n✅ Completed! Results saved to: {output_json}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run standalone LangGraph GPT-frame EgoBench service agent")
    parser.add_argument("--user_model_name", default=DEFAULT_USER_MODEL_NAME)
    parser.add_argument(
        "--user_api_key",
        default=(
            os.environ.get("LANCE_API_KEY")
            or os.environ.get("LANCE_SERVICE_API_KEY")
            or os.environ.get("GPT_API_KEY")
            or os.environ.get("GPT_SERVICE_API_KEY")
            or os.environ.get("QW_SERVICE_API_KEY")
            or os.environ.get("API_KEY")
        ),
    )
    parser.add_argument(
        "--user_api_base_url",
        default=(
            os.environ.get("LANCE_LLM_API_BASE_URL")
            or os.environ.get("LANCE_SERVICE_API_BASE_URL")
            or os.environ.get("GPT_LLM_API_BASE_URL")
            or os.environ.get("GPT_SERVICE_API_BASE_URL")
            or os.environ.get("QW_SERVICE_API_BASE_URL")
            or os.environ.get("QW_SERVICE_BASE_URL")
            or os.environ.get("LLM_API_BASE_URL")
        ),
    )
    parser.add_argument("--user_temperature", type=float, default=0.0)
    parser.add_argument("--user_enable_thinking", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--user_thinking_budget", type=int, default=None)
    parser.add_argument("--user_preserve_thinking", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--service_model_name", default=DEFAULT_SERVICE_MODEL_NAME)
    parser.add_argument(
        "--service_api_key",
        default=(
            os.environ.get("LANCE_SERVICE_API_KEY")
            or os.environ.get("GPT_SERVICE_API_KEY")
            or os.environ.get("AIGPT_SERVICE_API_KEY")
            or os.environ.get("SERVICE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        ),
    )
    parser.add_argument(
        "--service_api_base_url",
        default=(
            os.environ.get("LANCE_SERVICE_API_BASE_URL")
            or os.environ.get("GPT_SERVICE_API_BASE_URL")
            or os.environ.get("AIGPT_SERVICE_API_BASE_URL")
            or os.environ.get("SERVICE_API_BASE_URL")
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
    parser.add_argument("--service_reasoning_effort", default=os.environ.get("SERVICE_REASONING_EFFORT"))
    parser.add_argument("--log_service_payload_size", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--service_payload_warn_mb", type=float, default=2.5)
    parser.add_argument("--scenario", choices=["retail", "kitchen", "restaurant", "order"], default="retail")
    parser.add_argument("--scenario_number", type=int, default=1)
    parser.add_argument("--num_tasks", type=int, default=0)
    parser.add_argument("--task_ids", type=parse_task_ids, default=None)
    parser.add_argument("--max_turns", type=int, default=10)
    parser.add_argument("--max_inner_tool_rounds", type=int, default=12)
    parser.add_argument("--max_tool_calls", type=int, default=200)
    parser.add_argument("--max_repair_rounds", type=int, default=2)
    parser.add_argument("--multi_agent_user", action="store_true")
    parser.add_argument("--summary_user", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue_on_task_error", action="store_true")
    parser.add_argument("--output_model_name", default=None)
    parser.add_argument("--frame_fps", type=float, default=2.0)
    parser.add_argument("--frame_max_side", type=int, default=1920)
    parser.add_argument("--frame_rotation", choices=["none", "clockwise", "counterclockwise", "180"], default="none")
    parser.add_argument("--jpeg_quality", type=int, default=3)
    parser.add_argument("--max_frames", type=int, default=0)
    parser.add_argument("--image_detail", choices=["low", "auto", "high"], default="high")
    parser.add_argument(
        "--frame_attach_policy",
        choices=["auto", "each_turn", "first_turn", "never"],
        default="auto",
    )
    parser.add_argument("--max_visual_context_requests", type=int, default=6)
    parser.add_argument("--enable_visual_resolve", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--refresh_frames", action="store_true")
    parser.add_argument(
        "--frame_cache_dir",
        default=str(PROJECT_ROOT / "experiments" / "gpt55_frame_service_runner" / "cache" / "frames"),
    )
    return parser.parse_args()


def main() -> None:
    run_simulation(parse_args())


if __name__ == "__main__":
    main()
