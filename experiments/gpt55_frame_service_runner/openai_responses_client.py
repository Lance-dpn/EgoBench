"""Responses API service-model client for the frame-based experiment."""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class ResponsesResult:
    text: str
    input_tokens: int
    output_tokens: int
    raw: Any | None = None


def _response_output_text(response: Any) -> str:
    direct = getattr(response, "output_text", None)
    if direct:
        return str(direct)
    if isinstance(response, dict):
        direct = response.get("output_text")
        if direct:
            return str(direct)
        output = response.get("output", [])
    else:
        output = getattr(response, "output", []) or []

    chunks: list[str] = []
    for item in output:
        content = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", []) or []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") in {"output_text", "text"} and part.get("text"):
                    chunks.append(str(part["text"]))
            else:
                text = getattr(part, "text", None)
                if text:
                    chunks.append(str(text))
    return "\n".join(chunks).strip()


def _usage_tokens(response: Any) -> tuple[int, int]:
    usage = response.get("usage", {}) if isinstance(response, dict) else getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0), int(
            usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        )
    return int(getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0), int(
        getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0
    )


class OpenAIResponsesServiceClient:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_output_tokens: int = 32768,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: int = 600,
        max_retries: int = 8,
        retry_base_delay: float = 30.0,
        retry_max_delay: float = 180.0,
        retry_after_cap: float = 300.0,
        log_request_size: bool = True,
        payload_warn_mb: float = 2.5,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("SERVICE_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.base_url = (base_url or os.environ.get("SERVICE_API_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort if reasoning_effort not in {"", "none", "None"} else None
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.retry_after_cap = retry_after_cap
        self.log_request_size = log_request_size
        self.payload_warn_mb = payload_warn_mb
        if not self.api_key:
            raise ValueError("SERVICE_API_KEY or OPENAI_API_KEY is required for GPT frame service.")

    def create(self, *, instructions: str, input_items: list[dict[str, Any]]) -> ResponsesResult:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return self._create_once(instructions=instructions, input_items=input_items)
            except Exception as exc:  # pragma: no cover - exercised in live API use
                last_error = exc
                if self._is_non_retryable(exc):
                    raise RuntimeError(f"Responses API request is not retryable: {exc}") from exc
                if attempt < self.max_retries - 1:
                    wait = self._retry_wait_seconds(attempt, exc)
                    print(
                        f"🔁 [Responses Retry] Attempt {attempt + 1}/{self.max_retries} failed: {exc}. "
                        f"Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
        raise RuntimeError(f"Responses API failed after {self.max_retries} attempts: {last_error}") from last_error

    def _retry_wait_seconds(self, attempt: int, exc: Exception) -> float:
        retry_after = self._retry_after_seconds(exc)
        if retry_after is not None:
            return min(retry_after, self.retry_after_cap) + random.uniform(0, 1)
        backoff = self.retry_base_delay * (2**attempt)
        return min(backoff, self.retry_max_delay) + random.uniform(0, 1)

    def _is_non_retryable(self, exc: Exception) -> bool:
        if self._is_retryable(exc):
            return False
        text = str(exc).lower()
        markers = [
            "invalid_value",
            "model_not_found",
            "invalid_model",
            "unsupported_model",
            "badrequesterror",
            "error code: 400",
        ]
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status_code = _exception_status_code(exc)
        if status_code in {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}:
            return True
        text = str(exc).lower()
        markers = [
            "stream disconnected",
            "connection error",
            "unexpected eof",
            "auth_unavailable",
            "origin_response_timeout",
            "timeout",
            "temporarily unavailable",
            "rate limit",
            "server_error",
            "internal_server_error",
            "error code: 408",
            "error code: 409",
            "error code: 429",
            "error code: 500",
            "error code: 502",
            "error code: 503",
            "error code: 504",
            "error code: 520",
            "error code: 522",
            "error code: 524",
        ]
        return any(marker in text for marker in markers)

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            retry_after = headers.get("retry-after") or headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        if response is not None:
            try:
                data = response.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                value = data.get("retry_after")
                if value is None and isinstance(data.get("error"), dict):
                    value = data["error"].get("retry_after")
                if value is not None:
                    try:
                        return max(0.0, float(value))
                    except (TypeError, ValueError):
                        pass
        match = re.search(r"['\"]retry_after['\"]\s*:\s*(\d+(?:\.\d+)?)", str(exc))
        if match:
            return max(0.0, float(match.group(1)))
        return None

    def _build_payload(self, *, instructions: str, input_items: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "max_output_tokens": self.max_output_tokens,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        return payload

    def _log_payload_size(self, payload: dict[str, Any]) -> None:
        if not self.log_request_size:
            return
        body = json.dumps(payload, ensure_ascii=False)
        image_count = 0
        image_chars = 0
        for item in payload.get("input", []):
            for part in item.get("content", []):
                if part.get("type") == "input_image":
                    image_count += 1
                    image_chars += len(str(part.get("image_url", "")))
        body_mib = len(body.encode("utf-8")) / 1024 / 1024
        image_mib = image_chars / 1024 / 1024
        print(
            f"📦 [Responses Payload] body={body_mib:.2f} MiB, "
            f"images={image_count}, image_data={image_mib:.2f} MiB"
        )
        if self.payload_warn_mb > 0 and body_mib > self.payload_warn_mb:
            print(
                f"⚠️ [Responses Payload Warning] request body exceeds "
                f"{self.payload_warn_mb:.2f} MiB; consider lower --frame_max_side, "
                "--max_frames, or fewer concurrent requests."
            )

    def _create_once(self, *, instructions: str, input_items: list[dict[str, Any]]) -> ResponsesResult:
        payload = self._build_payload(instructions=instructions, input_items=input_items)
        self._log_payload_size(payload)
        try:
            from openai import OpenAI  # type: ignore
        except ModuleNotFoundError:
            return self._create_with_requests(instructions=instructions, input_items=input_items)

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        if not hasattr(client, "responses"):
            return self._create_with_requests(instructions=instructions, input_items=input_items)

        response = client.responses.create(**payload)
        input_tokens, output_tokens = _usage_tokens(response)
        return ResponsesResult(text=_response_output_text(response), input_tokens=input_tokens, output_tokens=output_tokens, raw=response)

    def _create_with_requests(self, *, instructions: str, input_items: list[dict[str, Any]]) -> ResponsesResult:
        url = f"{self.base_url}/responses"
        payload = self._build_payload(instructions=instructions, input_items=input_items)
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        input_tokens, output_tokens = _usage_tokens(data)
        return ResponsesResult(text=_response_output_text(data), input_tokens=input_tokens, output_tokens=output_tokens, raw=data)


def _exception_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None
