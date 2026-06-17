"""Lightweight tool-call correction support for frame service runs."""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from experiments.gpt55_frame_service_runner.openai_responses_client import (
    OpenAIResponsesServiceClient,
    _exception_status_code,
)


CORRECTION_SCENARIO_RULES = {
    "retail": (
        "- Retail correction focus: audit product/cart tool schemas, lookup evidence,\n"
        "  inventory, prices, discounts, quantities, cart state, branch logic, and\n"
        "  totals. Do not audit whether a visually inferred product or shelf referent\n"
        "  is correct.\n"
        "- A product name inferred from frames is a visual hypothesis. Do not require\n"
        "  tools to prove that the image truly shows that product. Audit only whether\n"
        "  product tools map the hypothesis to a clear canonical catalog product and\n"
        "  whether later product facts use that canonical item.\n"
        "- Complete retail list tools such as find_products_by_taste and\n"
        "  find_products_by_nutritional_characteristic can support negative\n"
        "  classification. If a canonical product is absent from the returned list,\n"
        "  it is not classified with that attribute in the official catalog."
    ),
    "restaurant": (
        "- Restaurant correction focus: audit dish/order tool schemas, lookup evidence,\n"
        "  allergens, nutrition, prices, discounts, recommendations, order state,\n"
        "  branch logic, ties, and calculations. Do not audit whether a visually\n"
        "  inferred dish, menu region, or pointing target is correct. For nutrition\n"
        "  attributes, require the service to consider semantically related official\n"
        "  enum values before concluding that a branch has no matching dish.\n"
        "- For category-localized restaurant tasks, treat a category lookup as the\n"
        "  boundary candidate set. Global taste/tag/allergen/nutrition list tools may\n"
        "  serve as attribute filters, but their candidates must be intersected with\n"
        "  the boundary before ranking or mutation.\n"
        "- When a proposed restaurant mutation targets a dish in the boundary-and-\n"
        "  attribute intersection and ranking facts were checked for that remaining\n"
        "  set, do not reject merely because unrelated global candidates were not\n"
        "  inspected or because the visual category itself might be wrong."
    ),
    "kitchen": (
        "- Kitchen correction focus: audit recipe, inventory, nutrition, shelf-life,\n"
        "  shopping-list, menu facts, tool schemas, branch logic, and state changes.\n"
        "  Do not audit whether a visually inferred ingredient, action, utensil, or\n"
        "  recipe scene is correct. Expiry decisions require a current date explicitly\n"
        "  stated by the user; never use runtime date. If an expiry-dependent mutation\n"
        "  is proposed without a user-stated current date, reject it and ask the service\n"
        "  agent to request the date."
    ),
    "order": (
        "- Order correction focus: audit restaurant/order tool schemas, lookup evidence,\n"
        "  dish/category/set-meal facts, order state, branch logic, ties, and aggregate\n"
        "  calculations. Do not audit whether a visually inferred restaurant, menu,\n"
        "  dish, category, set-meal text, or pointing target is correct."
    ),
}


CORRECTION_SYSTEM_PROMPT_TEMPLATE = """
You are a correction agent that audits a service agent before its output is
executed or shown to the user.

Runtime scenario: {scenario}

## Scope And Evidence

You do not solve the whole benchmark task. You do not access the database
directly. Database facts are only the tool results included in the audit
context.
For this correction pass, use the provided user/service dialogue history for
task context, and use only the current turn's executed tool ledger as database
evidence. Do not use older tool calls or results unless they are explicitly
present in the current turn ledger.

You do not audit visual recognition accuracy. The service agent may use frames
to form visual hypotheses, but this correction pass must not decide whether a
pointed/selected object, dish, product, region, ingredient, action, OCR text, or
spatial relation was visually recognized correctly. Do not request, inspect, or
reason from images. Treat visually inferred names or categories as hypotheses
that may seed read-only tool calls. Your job is to audit official tool use,
tool evidence, branch logic, state changes, and final replies.

## Scenario-Specific Correction Rules

{scenario_rule}

## Core Audit Rules

The correct evidence flow is: visual/dialogue hypothesis -> non-mutating tool
call -> executed tool result -> state-changing mutation and/or final reply.
Use the service prompt and current turn context to judge whether the service
agent's tool plan and final reply are coherent with the user's request and
the tool evidence.
Do not reject a read-only lookup because visual identity is uncertain; read-only
lookups are allowed to gather candidate evidence from dialogue or visual
hypotheses. Keep stricter evidence requirements for state-changing calls and
final replies, but apply those requirements to the non-visual tool chain:
official tool schema, returned candidates, filters, ranks, ties, quantities,
state, and calculations.
Apply branch gating without being over-strict: the service agent may batch
read-only calls for the same current decision point over the same active
candidate set, but should not pre-query tools that are only needed for inactive
future branches. Reject or request revision only when the proposed call clearly
belongs to an unrelated downstream branch, an alternative branch that has not
been selected, or a state change whose prerequisites are not yet proven.
Do not reject merely because a read-only batch could be smaller, because the
service is exploring plausible candidates, or because several calls are needed
to decide the current branch condition.
For visually derived names or OCR text, do not require exact full-name matching
between the service agent's visual hypothesis, the lookup query, and the
returned canonical database name. Visual/OCR text can contain wrong, extra, or
partial words. Match by the most discriminative tokens that can identify a
catalog item.
Use this token priority:
1. Strong tokens: brand/proper-name/store-specific words or rare multi-word
   phrases that distinguish one item from many nearby catalog items.
2. Medium tokens: variety, flavor, dish style, product type, ingredient, or
   category words.
3. Weak tokens: generic category words, colors, positions, container shapes,
   visual descriptors, or words that many returned candidates share.
If a query based on a strong token returns one canonical item and the stated
database fact is supported for that returned item, approve the reply even when
other medium/weak words from the visual hypothesis are absent or replaced in
the canonical name. Do not reject merely because the returned canonical name
does not preserve every visual/OCR word.
If an earlier full visual/OCR query returned a generic item that dropped the
strong token, and a later query using the strong token returned exactly one
canonical item preserving that strong token, treat the earlier generic result as
a failed broad lookup, not as a competing candidate. Do not use the generic
result to create ambiguity against the unique strong-token result.
If no strong token is available, or if the preserved token returns multiple
plausible candidates with different requested facts, require more read-only
tool evidence before approving a definitive reply.
Token preservation is case-insensitive and order-insensitive. A canonical name
may contain additional words and still preserve the selected discriminative
token or phrase, ignoring case, punctuation, and word order.

## Audit Inputs

Audit whether the proposed tool-call batch or proposed reply is justified by:
- the latest user request,
- the filtered user/service dialogue history,
- the prior dialogue summary, if provided,
- the complete official tool catalog, including descriptions and parameters,
- current turn executed official tool calls and their results,
- the service agent's own prior statements.

Audit the stage indicated by proposed_kind:
- proposed_kind="tool_calls": audit the service agent's planned official tool
  calls before execution. Decide whether the tool choice, batch order,
  parameter names, and parameter values are appropriate for the current user
  request and the executed ledger so far. Read-only evidence gathering is
  usually allowed; state-changing calls require stronger prior tool evidence.
- proposed_kind="tool_calls": also audit branch gating. Approve read-only
  batches that serve one current decision point. Reject only clear prefetching
  of inactive branches or unrelated downstream actions.
- proposed_kind="final_reply": audit only the proposed natural-language reply
  before it is shown to the user. Decide whether each claimed database fact,
  completed action, branch decision, and calculation is supported by executed
  tool results. If the reply still needs a tool call, use NEED_MORE_TOOL and
  suggest the exact official call(s).
- Do not suggest requesting visual context. If more evidence is needed, suggest
  official read-only tool calls or a concise user clarification only.

## Tool-Call Audit

For tool calls:
- Keep the proposed batch order intact. Do not reorder calls.
- Approve a batch only if every call in the batch is appropriate at this point.
- Validate every proposed tool name, parameter name, and parameter value against
  the official tool catalog before approving it.
- Use the tool descriptions to decide whether the proposed tool is the right
  one for the user's requested fact, calculation, or state change.
- Treat read-only tools such as find_*, get_*, tally_*, and compute_* as
  evidence gathering or calculation. They do not change database state and
  should normally be allowed to execute so the service agent can gather facts.
- Do not audit whether visually grounded read-only calls selected the correct
  visual target. Approve them when the tool exists and the parameters are valid
  enough to gather evidence for the user's request.
- A read-only batch is appropriate when all calls answer the same current
  branch condition, candidate filtering step, ranking step, calculation, or
  canonicalization step.
- A read-only batch is inappropriate when it clearly mixes evidence for both
  sides of an unresolved if/otherwise branch, or includes calls that are useful
  only after a different branch has become active.
- If the branch status is ambiguous but the calls are read-only and plausibly
  relevant to the current user request, prefer APPROVE over REJECT.
- Focus tool-call rejection on state-changing tools such as add_*, remove_*,
  and clear_*.
- For mutation calls, audit the non-visual chain: user requested a state change;
  the tool exists and accepts the supplied parameters; prior executed tool
  results support the selected canonical target, quantity, filters,
  ranking/tie handling, and other database facts that the mutation depends on.
- If the user's request first localizes a visual boundary such as a category,
  section, shelf area, card, panel, fold, selected group, or pointed category,
  audit rankings against the candidates inside that boundary, not against the
  whole database.
- A category/list lookup plus a tag/taste/allergen/nutrition list lookup can
  support an intersection candidate set. Require ranking facts only for the
  candidates in that intersection, not for every global item returned by the
  attribute list.
- If a mutation depends on a visual premise, do not audit the visual premise
  itself. Audit only whether the selected canonical target is supported by
  prior non-mutating tool results and satisfies requested non-visual constraints.
- Reject mutation calls if the selected canonical target is absent from prior
  relevant tool results, violates a requested non-visual constraint, uses the
  wrong quantity/user/order/cart, misses required ties, or changes state before
  required read-only facts have been executed and inspected.
- If prior tool results show multiple tied candidates for a requested maximum,
  minimum, cheapest, most expensive, highest, lowest, or equivalent ranking,
  reject a state-changing batch that mutates only part of the tied set when the
  user's task requires acting on the selected set.
- If a proposed batch combines mutation calls with read-only calls, review the
  whole batch in its given order. Approve only when the order is logically valid
  under the official tools; never reorder calls yourself.
- If a proposed batch prefetches inactive-branch read-only calls together with
  a valid current-branch lookup, reject with a suggestion to execute only the
  current decision-point calls first.

## Final-Reply Audit

For final replies:
- Reject replies that claim actions or calculations were completed without
  supporting executed tool results.
- Reject replies that should call another official tool before answering.
- Do not evaluate the visual mapping itself. Audit whether the selected
  canonical item and claimed database/action/calculation facts are supported by
  executed tool results.
- Reject final replies that choose or describe a branch without executed tool
  evidence for the branch condition, unless the branch condition was purely
  visual and the reply does not claim unsupported database facts.
- For visually derived item names, require support for the selected
  discriminative token, not exact full-name preservation. A unique tool result
  that preserves a strong brand/proper-name/store-specific token can support a
  reply even if medium tokens such as variety/flavor/type differ from the
  service agent's visual/OCR hypothesis.
- If a full visual/OCR lookup returned a generic item that dropped the strong
  token, ignore that generic result once a later strong-token lookup returns a
  unique canonical item preserving the strong token. Do not reject the reply as
  ambiguous solely because both lookups appear in the ledger.
- For replies after mutation calls, verify that the claimed state change and
  final quantity are supported by executed tool results and their returned
  fields.
- Reject replies that use a tool result for a generic or different canonical
  item when the claimed item or query included an available strong
  discriminative token and the returned item does not preserve that token.
- Do not reject only because of lowercase/capitalization differences or because
  the canonical database name adds extra words around the distinctive token.

## Output Contract

Return a compact text response using exactly this structure:

decision: APPROVE|REJECT|REVISE|NEED_MORE_TOOL
error_type: none|visual_target|key_frames|tool_schema|tool_evidence|state_change|calculation|unsupported_reply|other
visible_evidence: always "not audited"
reason: one sentence, at most 25 words.
suggestion: one sentence, at most 25 words; state the best next tool/action to check, or "none" for APPROVE.
replan: one sentence, at most 25 words; use "none" for APPROVE.

Never reject because of visual recognition, visual target identity, OCR quality,
frame selection, or pointing/spatial interpretation. If rejecting, state the
tool-schema, tool-evidence, state-change, branch, or calculation problem.
Do not reject a tool batch just because a different valid tool sequence might be
more efficient. Reject only clear schema errors, unsupported mutations,
unsupported replies, wrong calculations, missed ties, or clear inactive-branch
prefetching.
Never tell the service agent to output NEED_VISUAL_CONTEXT in suggestion or
replan.

Keep the whole response under 130 words unless including a JSON call. If and only
if using REVISE or NEED_MORE_TOOL, include one JSON array of official tool calls
after a line beginning with corrected_call: or suggested_call:.
""".strip()


def build_correction_system_prompt(*, scenario: str, scenario_number: int) -> str:
    scenario_rule = CORRECTION_SCENARIO_RULES.get(
        scenario,
        "- Use the official tools to audit tool schemas, database facts, branch logic, calculations, and state changes. Do not audit visual recognition.",
    )
    return CORRECTION_SYSTEM_PROMPT_TEMPLATE.format(
        scenario=f"{scenario}{scenario_number}",
        scenario_rule=scenario_rule,
    )


READ_ONLY_PREFIXES = ("find_", "get_", "tally_", "compute_")
LOOKUP_PREFIXES = ("find_", "get_")
MUTATION_PREFIXES = ("add_", "remove_", "clear_")

GENERIC_NAME_TOKENS = {
    "a",
    "an",
    "and",
    "bottle",
    "box",
    "brand",
    "category",
    "dish",
    "item",
    "menu",
    "object",
    "pack",
    "product",
    "the",
    "variety",
    "wine",
    "with",
    "red",
    "white",
    "blue",
    "green",
    "yellow",
    "black",
    "light",
    "dark",
    "sauvignon",
    "blanc",
    "cabernet",
    "chardonnay",
    "merlot",
    "pinot",
    "noir",
    "rose",
    "rosé",
    "brut",
    "champagne",
}


@dataclass
class CorrectionDecision:
    decision: str
    reason: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision == "APPROVE"


@dataclass
class ChatCompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    raw: Any | None = None


class ChatCompletionsCorrectionClient:
    """OpenAI-compatible chat completions client for the correction agent."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 2048,
        temperature: float | None = 0.0,
        timeout: int = 300,
        max_retries: int = 3,
        retry_base_delay: float = 10.0,
        retry_max_delay: float = 60.0,
        retry_after_cap: float = 120.0,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = (
            api_key
            or os.environ.get("CORRECTION_API_KEY")
            or os.environ.get("Deepseek_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or ""
        )
        self.base_url = (
            base_url
            or os.environ.get("CORRECTION_API_BASE_URL")
            or os.environ.get("Deepseek_SERVICE_API_BASE_URL")
            or os.environ.get("DEEPSEEK_API_BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.retry_after_cap = retry_after_cap
        self.thinking = thinking if thinking not in {"", "none", "None"} else None
        self.reasoning_effort = reasoning_effort if reasoning_effort not in {"", "none", "None"} else None
        if not self.api_key:
            raise ValueError("CORRECTION_API_KEY or DEEPSEEK_API_KEY is required for the correction agent.")

    def create(
        self,
        *,
        system_prompt: str,
        user_content: str | None = None,
        user_items: list[dict[str, Any]] | None = None,
    ) -> ChatCompletionResult:
        normalized_items = user_items or []
        if not normalized_items:
            normalized_items = [{"type": "input_text", "text": user_content or ""}]
        # Chat completions do not support image inputs in all providers;
        # keep frames as text notices so callers can still pass references.
        dropped_images = sum(
            1 for item in normalized_items if isinstance(item, dict) and item.get("type") == "input_image"
        )
        if dropped_images:
            print(
                f"⚠️ [Correction Images] chat_completions path drops {dropped_images} image inputs; "
                "use --correction_api_type responses for visual correction."
            )
        text_items = []
        for item in normalized_items:
            if isinstance(item, dict) and item.get("type") == "input_text":
                text = item.get("text")
                if isinstance(text, str):
                    text_items.append(text)
        if not text_items:
            text_items = [""]
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return self._create_once(
                    system_prompt=system_prompt,
                    user_content="\n\n".join(text_items),
                )
            except Exception as exc:  # pragma: no cover - exercised in live API use
                last_error = exc
                if self._is_non_retryable(exc):
                    raise RuntimeError(f"Chat completions request is not retryable: {exc}") from exc
                if attempt < self.max_retries - 1:
                    wait = self._retry_wait_seconds(attempt, exc)
                    print(
                        f"🔁 [Correction Retry] Attempt {attempt + 1}/{self.max_retries} failed: {exc}. "
                        f"Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
        raise RuntimeError(f"Chat completions request failed after {self.max_retries} attempts: {last_error}") from last_error

    def _build_payload(self, *, system_prompt: str, user_content: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.thinking is not None:
            payload["thinking"] = {"type": self.thinking}
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def _create_once(self, *, system_prompt: str, user_content: str) -> ChatCompletionResult:
        payload = self._build_payload(system_prompt=system_prompt, user_content=user_content)
        try:
            from openai import OpenAI  # type: ignore
        except ModuleNotFoundError:
            return self._create_with_requests(payload)

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        sdk_payload = dict(payload)
        extra_body: dict[str, Any] = {}
        if "thinking" in sdk_payload:
            extra_body["thinking"] = sdk_payload.pop("thinking")
        if extra_body:
            sdk_payload["extra_body"] = extra_body
        response = client.chat.completions.create(**sdk_payload)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        message = response.choices[0].message if response.choices else None
        text = str(getattr(message, "content", "") or "")
        return ChatCompletionResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens, raw=response)

    def _create_with_requests(self, payload: dict[str, Any]) -> ChatCompletionResult:
        url = f"{self.base_url}/chat/completions"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        text = ""
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices:
            text = str(choices[0].get("message", {}).get("content", "") or "")
        return ChatCompletionResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens, raw=data)

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
            "invalid_request_error",
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
            "connection error",
            "unexpected eof",
            "timeout",
            "temporarily unavailable",
            "rate limit",
            "server_error",
            "internal_server_error",
            "insufficient_system_resource",
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
        return None


class ResponsesCorrectionClient:
    """Responses API adapter for running the correction agent on GPT-5.5."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 2048,
        temperature: float | None = 0.0,
        reasoning_effort: str | None = None,
        timeout: int = 300,
        max_retries: int = 3,
        retry_base_delay: float = 10.0,
        retry_max_delay: float = 60.0,
        retry_after_cap: float = 120.0,
    ) -> None:
        self.client = OpenAIResponsesServiceClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_output_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
            retry_after_cap=retry_after_cap,
            log_request_size=False,
            payload_warn_mb=0,
        )

    def create(
        self,
        *,
        system_prompt: str,
        user_content: str | None = None,
        user_items: list[dict[str, Any]] | None = None,
    ) -> ChatCompletionResult:
        normalized_items = user_items or []
        if not normalized_items:
            normalized_items = [{"type": "input_text", "text": user_content or ""}]
        result = self.client.create(
            instructions=system_prompt,
            input_items=[{"role": "user", "content": normalized_items}],
        )
        return ChatCompletionResult(
            text=result.text,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            raw=result.raw,
        )


def normalize_calls(tool_call_obj: Any) -> list[dict[str, Any]]:
    if isinstance(tool_call_obj, list):
        return [call for call in tool_call_obj if isinstance(call, dict)]
    if isinstance(tool_call_obj, dict):
        return [tool_call_obj]
    return []


def call_name(call: dict[str, Any]) -> str:
    return str(call.get("tool_name") or call.get("name") or "")


def is_read_only_call(call: dict[str, Any]) -> bool:
    name = call_name(call)
    return name.startswith(READ_ONLY_PREFIXES)


def is_lookup_call(call: dict[str, Any]) -> bool:
    name = call_name(call)
    return name.startswith(LOOKUP_PREFIXES)


def is_mutation_call(call: dict[str, Any]) -> bool:
    name = call_name(call)
    return name.startswith(MUTATION_PREFIXES)


def compact_json(value: Any, max_chars: int = 3000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"... [context_truncated {len(text) - max_chars} chars]"


def normalized_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def distinctive_tokens(text: str) -> list[str]:
    tokens = normalized_tokens(text)
    return [
        token
        for token in tokens
        if len(token) > 2 and not token.isdigit() and token not in GENERIC_NAME_TOKENS
    ]


def canonical_match_drops_too_much(query_tokens: list[str], returned_tokens: set[str]) -> list[str]:
    dropped = [token for token in query_tokens if token not in returned_tokens]
    if not dropped:
        return []
    preserved_count = len(query_tokens) - len(dropped)
    if len(query_tokens) >= 3 and preserved_count >= 2:
        return []
    return dropped


def parse_tool_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return content


def numeric_fact_strings(value: Any) -> set[str]:
    strings: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (int, float)) and key in {
                "tax_rate",
                "price",
                "discount",
                "calories_kcal",
                "fat_g",
            }:
                strings.add(str(item).rstrip("0").rstrip("."))
                if key == "tax_rate":
                    strings.add(str(int(round(float(item) * 100))))
            elif isinstance(item, (dict, list)):
                strings.update(numeric_fact_strings(item))
    elif isinstance(value, list):
        for item in value:
            strings.update(numeric_fact_strings(item))
    return strings


def deterministic_reply_feedback(proposed_reply: str, tool_logs: list[dict[str, Any]]) -> str | None:
    reply_lower = str(proposed_reply or "").lower()
    for entry in tool_logs:
        for result in entry.get("results", []):
            if not isinstance(result, dict):
                continue
            params = result.get("parameters", {}) if isinstance(result.get("parameters", {}), dict) else {}
            query_name = params.get("product_name") or params.get("dish_name") or params.get("name")
            if not query_name:
                continue
            query_distinctive = distinctive_tokens(str(query_name))
            if not query_distinctive:
                continue
            data = parse_tool_content(result.get("content"))
            if not isinstance(data, dict):
                continue
            products = data.get("products")
            if not isinstance(products, list) or not products:
                continue
            returned_names = [
                str(product.get("product_name") or product.get("dish_name") or product.get("name") or "")
                for product in products
                if isinstance(product, dict)
            ]
            returned_token_set = set(normalized_tokens(" ".join(returned_names)))
            dropped = canonical_match_drops_too_much(query_distinctive, returned_token_set)
            if not dropped:
                continue
            returned_text = " ".join(returned_names).lower()
            fact_strings = numeric_fact_strings(products)
            reply_uses_returned_name = any(name and name.lower() in reply_lower for name in returned_names)
            reply_uses_returned_fact = any(fact and re.search(rf"\b{re.escape(fact)}\b", reply_lower) for fact in fact_strings)
            if reply_uses_returned_name or reply_uses_returned_fact:
                return (
                    "The proposed reply relies on a lookup whose returned canonical item drops distinctive "
                    f"query token(s) {dropped} from {query_name!r}. The returned item(s) {returned_names} may be "
                    "a generic fuzzy match. Re-query using the most representative distinctive token or shorter "
                    "canonical substring before answering."
                )
    return None


def json_char_count(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def compact_tool_logs(tool_logs: list[dict[str, Any]], *, max_entries: int, max_result_chars: int) -> list[dict[str, Any]]:
    _ = max_result_chars
    compacted: list[dict[str, Any]] = []
    selected_logs = tool_logs[-max_entries:] if max_entries > 0 else tool_logs
    for entry in selected_logs:
        calls = normalize_calls(entry.get("calls", []))
        results = []
        for result in entry.get("results", []):
            if not isinstance(result, dict):
                continue
            content = str(result.get("content", ""))
            results.append(
                {
                    "tool_name": result.get("tool_name"),
                    "parameters": result.get("parameters", {}),
                    "content": content,
                }
            )
        compacted.append({"turn": entry.get("turn"), "calls": calls, "results": results})
    return compacted


def build_audit_context(
    *,
    scenario: str,
    scenario_number: int,
    task_id: int,
    turn: int,
    latest_user_message: str,
    summarized_history: str,
    service_history: list[dict[str, str]],
    service_prompt: str,
    tool_catalog: Any,
    tool_logs: list[dict[str, Any]],
    key_frames: list[dict[str, Any]] | None = None,
    proposed: Any,
    proposed_kind: str,
    max_tool_log_entries: int,
    max_tool_result_chars: int,
    max_audit_context_chars: int,
) -> str:
    _ = max_audit_context_chars
    dialogue_history = service_history
    stage_contract = {
        "tool_calls": (
            "Audit planned official tool calls before execution: tool choice, parameter names, "
            "parameter values, batch order, and whether state-changing calls are justified."
        ),
        "final_reply": (
            "Audit the proposed user-visible reply before delivery: claimed facts, completed actions, "
            "branch decisions, and calculations must be supported by executed tool results."
        ),
    }.get(proposed_kind, "Audit the proposed service-agent output before it is executed or shown.")
    executed_tool_ledger = compact_tool_logs(
        tool_logs,
        max_entries=max_tool_log_entries,
        max_result_chars=max_tool_result_chars,
    )
    important_constraints = [
        "Only executed official tool results are database evidence.",
        "The dialogue history may include previous turns, but it excludes tool-call JSON, tool execution results, and correction feedback.",
        "Only the current turn tool ledger is available as tool evidence; do not infer facts from older tool results not shown here.",
        "Do not use video or hidden ground truth.",
        "Do not audit visual recognition accuracy, frame selection, OCR quality, pointing target identity, or spatial interpretation.",
        "Read-only tools such as find_*, get_*, tally_*, and compute_* do not change database state.",
        "Read-only tool calls may be based on dialogue or visual hypotheses and should not be blocked only for lack of visual proof.",
        "Do not invent visual evidence or reject only because visual mapping is unproven.",
        "For final replies, audit non-visual tool facts, completed actions, branch decisions, and calculations.",
        "For visually derived names or OCR text, do not require exact full-name matching to the returned canonical database name.",
        "Match visually derived names by the strongest discriminative token that uniquely identifies a catalog item; do not reject only because weaker variety/type words differ.",
        "A generic lookup result that drops the strongest discriminative token is not a competing candidate once a later strong-token lookup returns one canonical item preserving that token.",
        "For mutation calls, audit non-visual tool evidence: tool schema, returned fields, filters, quantities, rankings, ties, and state target.",
        "When tool results show tied selected candidates and the user needs a state change over the selected set, require every tied candidate to be mutated.",
        "Visual claims alone do not justify final reply facts.",
        "Do not demand database proof of visual descriptors that the tools cannot represent.",
        "Validate tool names, parameter names, enum values, and intended use against official_tool_catalog.",
        "Do not reorder a proposed tool-call batch.",
        "Read-only batch calls should serve the same current decision point or active candidate set.",
        "Do not approve clear prefetching of tools that are only needed by inactive future branches.",
        "Do not reject a plausible read-only exploration merely because another valid sequence would be more efficient.",
        "If a state-changing call lacks non-visual tool evidence, reject or request more read-only tool evidence.",
        "For enum-valued filters, if an exact enum lookup has no overlap with a requested candidate set, check semantically related official enum values before accepting a fallback branch.",
        "Use previous dialogue turns only to understand the user's task and service commitments, not as database evidence.",
    ]
    if scenario == "retail":
        important_constraints.extend(
            [
                "For retail, a visually inferred product name is allowed as a hypothesis; do not require official tools to prove the image-to-product mapping.",
                "For retail, if product tools map a visual hypothesis to one clear canonical catalog product, audit later facts and mutations against that canonical product.",
                "For retail, complete list tools such as find_products_by_taste and find_products_by_nutritional_characteristic support negative classification when the canonical product is absent from the returned list.",
            ]
        )
    payload = {
        "scenario": f"{scenario}{scenario_number}",
        "task_id": task_id,
        "turn": turn,
        "service_prompt": service_prompt,
        "proposed_kind": proposed_kind,
        "stage_contract": stage_contract,
        "proposed": proposed,
        "latest_user_message": latest_user_message,
        "summarized_history": summarized_history or "",
        "dialogue_scope": "filtered user/service dialogue history; tool calls, tool results, and correction feedback are excluded",
        "tool_ledger_scope": "current turn only",
        "dialogue_history": dialogue_history,
        "key_frames": [],
        "current_turn_tool_ledger": executed_tool_ledger,
        "official_tool_catalog": tool_catalog,
        "important_constraints": important_constraints,
        "visual_grounding_policy": {
            "visual_mapping_audit_enabled": False,
            "correction_receives_images": False,
            "key_frames_available_to_correction": False,
            "dialogue_history_available": True,
            "tool_ledger_current_turn_only": True,
            "service_prompt_included": True,
            "visual_claims_may_seed_read_only_calls_without_key_frames": True,
            "visual_read_only_call_requires_positive_visual_support": False,
            "final_reply_audit_scope": "tool_facts_only_no_visual_mapping_audit",
            "mutation_audit_scope": "tool_chain_only_no_visual_mapping_audit",
            "do_not_block_read_only_lookup_because_visual_mapping_is_unproven": True,
            "visual_claims_alone_do_not_justify_final_reply_facts": True,
            "visual_ocr_name_matching": "discriminative_token_not_exact_full_name",
            "unique_strong_token_match_can_support_canonical_item": True,
            "generic_results_dropping_strong_token_are_not_conflicting_candidates": True,
            "do_not_require_database_fields_for_visual_descriptors": True,
            "read_only_batch_branch_gating_enabled": True,
            "over_strict_rejection_guard": "approve plausible read-only current-decision exploration",
        },
    }
    return compact_json(payload, max_chars=0)


def audit_context_stats(audit_context: str) -> dict[str, Any]:
    text = str(audit_context or "")
    return {
        "chars": len(text),
        "context_truncated": "[context_truncated " in text,
        "has_dialogue_history": '"dialogue_history"' in text,
        "has_current_turn_tool_ledger": '"current_turn_tool_ledger"' in text,
        "has_official_tool_catalog": '"official_tool_catalog"' in text,
        "has_proposed": '"proposed"' in text,
    }


def extract_json_calls(text: str) -> list[dict[str, Any]]:
    candidates = re.findall(r"\[[\s\S]*?\]", text)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        calls = normalize_calls(value)
        if calls:
            return calls
    return []


def parse_decision(text: str) -> CorrectionDecision:
    stripped = (text or "").strip()
    first_line_raw = stripped.splitlines()[0].strip() if stripped else "REJECT"
    decision_match = re.match(r"decision\s*:\s*(APPROVE|REJECT|REVISE|NEED_MORE_TOOL)\b", first_line_raw, re.IGNORECASE)
    first_line = decision_match.group(1).upper() if decision_match else first_line_raw.upper()
    decision = first_line if first_line in {"APPROVE", "REJECT", "REVISE", "NEED_MORE_TOOL"} else "REJECT"
    reason = stripped
    calls = extract_json_calls(stripped) if decision in {"REVISE", "NEED_MORE_TOOL"} else []
    return CorrectionDecision(decision=decision, reason=reason, calls=calls, raw_text=text)


def compact_decision_feedback(decision: CorrectionDecision) -> dict[str, str]:
    fields = {
        "decision": decision.decision,
        "error_type": "other" if decision.decision != "APPROVE" else "none",
        "visible_evidence": "",
        "reason": "",
        "suggestion": "",
        "replan": "",
    }
    for line in str(decision.reason or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in fields:
            fields[key] = value.strip()
    if not fields["reason"]:
        lines = [line.strip() for line in str(decision.reason or "").splitlines() if line.strip()]
        fields["reason"] = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
    if not fields["visible_evidence"]:
        fields["visible_evidence"] = "not audited"
    if not fields["suggestion"]:
        fields["suggestion"] = "Use the review reason to choose the next tool or reply." if decision.decision != "APPROVE" else "none"
    if not fields["replan"]:
        fields["replan"] = "Use the review reason to replan." if decision.decision != "APPROVE" else "none"
    return fields


def review_with_agent(
    client: ChatCompletionsCorrectionClient | ResponsesCorrectionClient,
    *,
    system_prompt: str,
    audit_context: str,
    key_frame_items: list[dict[str, Any]] | None = None,
) -> CorrectionDecision:
    user_items = [{"type": "input_text", "text": audit_context}]
    result = client.create(
        system_prompt=system_prompt,
        user_items=user_items,
    )
    decision = parse_decision(result.text)
    decision.input_tokens = result.input_tokens
    decision.output_tokens = result.output_tokens
    return decision


def deterministic_batch_feedback(calls: list[dict[str, Any]]) -> str | None:
    if not calls:
        return "No valid tool calls were found in the proposed batch."

    saw_read_only = False
    for call in calls:
        if is_read_only_call(call):
            saw_read_only = True
        elif is_mutation_call(call) and saw_read_only:
            return (
                "The proposed batch mixes read-only evidence gathering with a later state-changing call. "
                "Run the read-only tools first, inspect their results, then propose mutation calls in a later batch."
            )
    return None


def _result_item_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, str):
        text = value.strip().lower()
        if text:
            names.add(text)
    elif isinstance(value, dict):
        for key in ("dish_name", "product_name", "name", "item_name", "recipe_name", "ingredient_name"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                names.add(item.strip().lower())
        if not names:
            for item in value.values():
                if isinstance(item, (dict, list)):
                    names.update(_result_item_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_result_item_names(item))
    return names


def deterministic_batch_approval(calls: list[dict[str, Any]]) -> str | None:
    if calls and all(is_read_only_call(call) for call in calls):
        tool_names = {call_name(call) for call in calls}
        if len(calls) > 1 and len(tool_names) > 1:
            return None
        return (
            "All proposed calls are read-only official tools. They do not change database state, "
            "so the service agent can gather evidence or run calculations before deciding next steps."
        )
    return None


def write_correction_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def correction_log_path(output_path: str, output_model_name: str | None = None) -> Path:
    if output_model_name:
        name = output_model_name
    else:
        name = Path(output_path).parent.name
    return Path("experiments") / "gpt55_frame_service_runner" / "cache" / "correction_logs" / f"{name}.jsonl"


def failure_decision(exc: Exception, *, failure_policy: str) -> CorrectionDecision:
    if failure_policy == "reject":
        decision = "REJECT"
    else:
        decision = "APPROVE"
    return CorrectionDecision(
        decision=decision,
        reason=f"Correction agent failed; applying failure_policy={failure_policy}: {exc}",
        raw_text="",
        error=str(exc),
    )


def env_default_model() -> str:
    return (
        os.environ.get("CORRECTION_MODEL_NAME")
        or os.environ.get("LANCE_SERVICE_MODEL_NAME")
        or os.environ.get("SERVICE_MODEL_NAME")
        or os.environ.get("Deepseek_SERVICE_MODEL_NAME")
        or os.environ.get("DEEPSEEK_MODEL_NAME")
        or "gpt-5.5"
    )


def env_chat_completions_model() -> str:
    return (
        os.environ.get("CORRECTION_MODEL_NAME")
        or os.environ.get("Deepseek_SERVICE_MODEL_NAME")
        or os.environ.get("DEEPSEEK_MODEL_NAME")
        or "deepseek-v4-flash"
    )
