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
        "- If the service proposes read-only product lookups for a visually inferred\n"
        "  product name, price label, country label, shelf position, or OCR fragment,\n"
        "  approve those lookups unless the tool schema is invalid. These calls are\n"
        "  how retail visual hypotheses are canonicalized.\n"
        "- Complete retail list tools such as find_products_by_taste and\n"
        "  find_products_by_nutritional_characteristic can support negative\n"
        "  classification. If a canonical product is absent from the returned list,\n"
        "  it is not classified with that attribute in the official catalog.\n"
        "- When country is used as a retail DB filter, require canonical full\n"
        "  country names rather than abbreviations. If a lookup used UK, USA, or\n"
        "  US and returned empty, request a retry with United Kingdom or United\n"
        "  States before accepting that no candidates exist.\n"
        "- If a full visual/OCR product lookup returns no result, expect one to\n"
        "  three distinctive token lookups or relevant candidate-list tools before\n"
        "  the service concludes the product is unavailable. Generic package words\n"
        "  alone are insufficient when brand/proper-name or rare label tokens exist.\n"
        "- Treat nut/nuts as a plain-language allergen alias when the user wording\n"
        "  and retail DB field use different singular/plural forms.\n"
        "- Treat retail natural-language `high oil`/`High Oil` as equivalent to the\n"
        "  official nutritional_characteristic enum `high_fat`. Approve supported\n"
        "  `high_fat` tool calls for high-oil wording, and reject refusals that stop\n"
        "  only because a separate `high_oil` enum does not exist.\n"
        "- For retail, approve official enum normalization from natural-language\n"
        "  `high calorie`/`high-calorie` to `high_calories`, `low calorie`/\n"
        "  `low-calorie` to `low_calories`, and `gluten-free`/`gluten free` to\n"
        "  `gluten_free`."
    ),
    "restaurant": (
        "- Restaurant correction focus: audit dish/order tool schemas, lookup evidence,\n"
        "  allergens, nutrition, prices, discounts, recommendations, order state,\n"
        "  branch logic, ties, and calculations. Do not audit whether a visually\n"
        "  inferred dish, menu region, or pointing target is correct. Preserve exact\n"
        "  enum semantics: do not merge broad/specific nutrition labels such as\n"
        "  low_sugar vs sugar_free or low_calorie vs low_calories unless the user asks\n"
        "  for the broader set. Plain-language allergen aliases such as nut/nuts may\n"
        "  be treated as one category when inclusion/exclusion semantics require it.\n"
        "- For category-localized restaurant tasks, treat a category lookup as the\n"
        "  boundary candidate set. Global taste/tag/allergen/nutrition list tools may\n"
        "  serve as attribute filters, but their candidates must be intersected with\n"
        "  the boundary before ranking or mutation.\n"
        "- When a proposed restaurant mutation targets a dish in the boundary-and-\n"
        "  attribute intersection and ranking facts were checked for that remaining\n"
        "  set, do not reject merely because unrelated global candidates were not\n"
        "  inspected or because the visual category itself might be wrong.\n"
        "- For drink menu boards/cards, a visible uppercase label above a beverage\n"
        "  image is an exact visual menu anchor. If lookup results contain an exact\n"
        "  case-insensitive key for that single-letter label, audit that exact label\n"
        "  as the canonical target even when substring matches are also returned.\n"
        "- Do not reject restaurant mutations/calculations merely because a\n"
        "  single-letter label such as F, H, T, U, R, or E also matched longer dish\n"
        "  names. Reject substitutions to longer names unless visual/menu evidence\n"
        "  or exact DB results support replacing the letter anchor.\n"
        "- The exact single-letter anchor governs only the pointed/located drink.\n"
        "  If a later branch asks for drinks/options on the menu without limiting\n"
        "  scope to the letter-labeled specials, require a candidate set that also\n"
        "  covers named beverages before approving ranked mutations."
    ),
    "kitchen": (
        "- Kitchen correction focus: audit recipe, inventory, nutrition, shelf-life,\n"
        "  shopping-list, menu facts, tool schemas, branch logic, and state changes.\n"
        "  Do not audit whether a visually inferred ingredient, action, utensil, or\n"
        "  recipe scene is correct. Expiry decisions require a current date explicitly\n"
        "  stated by the user; never use runtime date. If an expiry-dependent mutation\n"
        "  is proposed without a user-stated current date, reject it and ask the service\n"
        "  agent to request the date.\n"
        "- Prefer preserving separate add/remove/update calls when they represent\n"
        "  different recipe occurrences, branch stages, or instructed process steps;\n"
        "  do not ask the service to merge them merely for efficiency.\n"
        "- For highest/lowest/most/fewest numeric ingredient or recipe rankings,\n"
        "  require tool evidence for the relevant numeric property over the active\n"
        "  candidate set. Do not accept a broad tag such as high_protein or low_fat\n"
        "  as a substitute for the requested numeric extremum.\n"
        "- For ingredient properties such as staple, dry goods, vegetable, meat,\n"
        "  seasoning, or storage/category membership, require official ingredient\n"
        "  category/location evidence rather than common-sense inference.\n"
        "- Treat kitchen allergen singular/plural wording as aliases when the DB\n"
        "  uses a different form. For example, an empty `egg` allergen lookup should\n"
        "  be retried as `eggs` before accepting that no recipe qualifies."
    ),
    "order": (
        "- Order correction focus: audit restaurant/order tool schemas, lookup evidence,\n"
        "  dish/category/set-meal facts, order state, branch logic, ties, and aggregate\n"
        "  calculations. Do not audit whether a visually inferred menu, dish,\n"
        "  category, set-meal text, or pointing target is correct. Restaurant_name is\n"
        "  the exception: it must come from user dialogue, not visual inference.\n"
        "- For order, frames, visible menu titles, logos, OCR text, and brand labels\n"
        "  must not be used to determine, rename, or canonicalize DB restaurant_name.\n"
        "  Reject tool calls and DB-backed replies when restaurant_name is introduced\n"
        "  only from visual/menu text rather than the user's dialogue.\n"
        "- Also reject user-visible replies that say a restaurant is named according\n"
        "  to visual/OCR/menu-title evidence. The service may compare visual menu\n"
        "  content, but must refer to restaurants using only user-supplied dialogue\n"
        "  names or ask the user for the exact full name.\n"
        "- Complete restaurant_name often follows `<name> <nation> Restaurant`, for\n"
        "  example complete names contain a venue/name part, a nation/cuisine part,\n"
        "  and `Restaurant`; when user wording provides those parts, the service may\n"
        "  compose that likely full name from user dialogue only, but should not treat\n"
        "  unsupported or visual-derived guesses as confirmed DB names. If an\n"
        "  unsupported name was attempted, allow one structured retry only when the\n"
        "  same user dialogue supplies all name/nation/Restaurant parts; reject\n"
        "  retries that invent the missing nation/cuisine or use visual/OCR text.\n"
        "- If asking for restaurant-name confirmation, the service must describe the\n"
        "  `<name> <nation> Restaurant` pattern only. Reject replies that put a\n"
        "  visual/menu-label guess or unsupported restaurant string into the question\n"
        "  as the suggested answer or example.\n"
        "- If restaurant selection will be followed by DB-backed ordering, the chosen\n"
        "  restaurant_name must be one supplied by the user. A visual-only restaurant\n"
        "  label cannot become the DB restaurant_name unless the user independently\n"
        "  provides it as the exact restaurant name in dialogue.\n"
        "- Reject tool calls using unsupported restaurant_name values because even\n"
        "  read-only lookups can create empty DB namespaces and break result-based\n"
        "  evaluation. Do not disclose a list of valid restaurant namespaces in the\n"
        "  correction feedback; tell the service to ask the user to confirm the exact\n"
        "  full restaurant name using the `<name> <nation> Restaurant` pattern.\n"
        "- If a guard or tool result already showed that a user-confirmed restaurant\n"
        "  name is unsupported, apply that unsupported status only to the exact\n"
        "  restaurant_name value named in the guard/tool feedback. Do not generalize\n"
        "  it to other user-supplied restaurant names from the same rejected batch.\n"
        "  Do not suggest using that same rejected name again. Require either a\n"
        "  different exact full restaurant name or a switch to another complete-pattern\n"
        "  restaurant option already provided by the user.\n"
        "- If a restaurant-name lookup failed or the ledger has no DB-supported full\n"
        "  restaurant_name, reject dish/order/set-meal mutations and final database\n"
        "  claims that guess a restaurant. Prefer a concise user clarification for the\n"
        "  complete restaurant name.\n"
        "- If the user constrains the task to an expanded page, menu page, section,\n"
        "  visible region, or set-meal text, require the service to preserve that\n"
        "  boundary before ranking or mutation; do not accept a global-menu extremum\n"
        "  unless the user asked globally.\n"
        "- Audit set-meal and dish operations separately. Reject using dish mutation\n"
        "  tools for set meals or set-meal mutation tools for individual dishes."
    ),
}


CORRECTION_SYSTEM_PROMPT_TEMPLATE = """
You are a correction agent that audits a service agent before its output is
executed or shown to the user.

Runtime scenario: {scenario}

## Scope And Evidence

You audit the service agent's next output; you do not solve the benchmark task.
Use dialogue history to understand the user's request and commitments. Use the
current turn's executed official tool ledger and previous-turn official tool
ledger as database evidence. Treat previous-turn tool results as evidence only
for facts/actions already established earlier in the same task; if the latest
user request changes the target, boundary, quantity, or condition, require
current-turn read-only evidence before approving new mutations or final claims.
Runner or correction feedback included in dialogue history is valid process
evidence about rejected outputs. In particular, if a namespace guard says an
order restaurant_name is unsupported or was not executed, you may approve a
reply that accurately says that name cannot be used for DB-backed tools and
asks for a different exact full restaurant name. This does not authorize any
dish, price, nutrition, order, or calculation fact without official tool
ledger evidence.

Do not audit visual recognition accuracy. Do not decide whether the service
recognized the correct object, dish, product, region, ingredient, action, OCR
text, pointing target, or spatial relation. Visual hypotheses may seed read-only
tool calls; official tool results must support mutations, calculations, branch
decisions, and DB-backed final replies.

If audit_context says service_frames_attached_this_turn=true, never reject a
reply or tool plan because frames, fresh visual context, key frames, or image
evidence are unavailable to you. You still may reject unsupported DB facts,
mutations, branch decisions, missed ties, wrong schemas, or calculations.

## Scenario-Specific Correction Rules

{scenario_rule}

## Core Audit Rules

Expected evidence flow: visual/dialogue hypothesis -> read-only official tools
-> canonical target and active branch -> mutation and/or final reply.

For read-only tool calls, be permissive: approve plausible lookup, list, get,
tally, or compute calls that gather candidates, enum options, fields, or branch
evidence, unless schema/parameters are invalid or the batch clearly belongs to
unrelated downstream work.

For mutations and final replies, be strict: require official evidence for the
canonical target, active branch, quantities, filters, ranks, ties, state target,
and calculations. Reject unsupported winners, missed ties, inactive-branch
mutations, wrong schemas, wrong identifiers, and unsupported DB claims.

For ranked choices, audit the active candidate set first. A highest/lowest/most/
least winner is supported only if the needed value was checked for all surviving
candidates in that bounded set, with ties preserved.

Canonical fields returned by tools override preliminary visual/OCR wording. A
visual/OCR lookup may be partial or noisy; match by distinctive tokens, not exact
full string. If a full visual/OCR lookup fails, prefer one to three read-only
distinctive-token retries before user clarification, except unsupported order
restaurant_name. If a clear canonical field is returned, later mutations,
calculations, and final replies must use that canonical field.

Do not require exhaustive global enumeration once a visual/dialogue boundary or
active candidate set is supported. Require global enumeration only when the user
explicitly asks for a global list/extremum and no narrower boundary exists.

Do not approve final-state-equivalent shortcuts that omit required intermediate
mutations. The tool-call process is part of correctness.

## Audit Inputs

Audit whether the proposed tool-call batch or proposed reply is justified by:
- the latest user request,
- the filtered user/service dialogue history,
- the prior dialogue summary, if provided,
- the complete official tool catalog, including descriptions and parameters,
- previous-turn official tool calls and their results from this task,
- current turn executed official tool calls and their results,
- the service agent's own prior statements.

Audit the stage indicated by proposed_kind:
- proposed_kind="tool_calls": validate tool names, parameters, batch order, and
  whether any mutation in the proposed batch is already justified.
- proposed_kind="final_reply": verify each claimed DB fact, completed action,
  branch decision, and calculation against executed tool results. If evidence is
  missing, use NEED_MORE_TOOL and suggest exact official call(s).
- Do not suggest visual context. If more evidence is needed, suggest official
  read-only tools or a concise user clarification only.

## Tool-Call Audit

For tool calls:
- Keep the proposed batch order intact. Do not reorder calls.
- Approve a batch only if every call is appropriate at this point.
- Validate every tool name, parameter name, parameter value, enum, and intended
  use against the official tool catalog.
- Treat find_*, get_*, list_*, tally_*, and compute_* as read-only evidence or
  calculation tools. They may be used to canonicalize visual/dialogue hypotheses
  and discover candidates, but compute/tally calls must still have known inputs.
- Reject mutations when the requested state change, canonical target, quantity,
  active branch, ranking/tie handling, or removal/clear condition is not
  supported by prior executed read-only evidence.
- Reject mutation batches that miss required ties, aggregate process-distinct
  changes, omit required intermediate mutations, or mix read-only and mutation
  calls in an order that is not logically valid.
- Do not use REVISE to replace add/remove/clear/update/create mutations. For
  unsupported or wrong mutations, use REJECT or NEED_MORE_TOOL and explain the
  missing evidence; the service agent must replan and emit any state change.
- Use REVISE only for non-mutating schema/identifier corrections where the same
  intended read-only evidence call is clearly preserved.

## Final-Reply Audit

For final replies:
- Reject replies that claim DB facts, actions, branch decisions, calculations,
  or final quantities without supporting executed tool results.
- Require the final named item/entity to be a returned canonical name or an
  unambiguous token-preserving shorthand. Do not reject capitalization-only
  differences or canonical names that add words around a distinctive token.
- If lookup results are multiple or generic, require narrowing, tied handling,
  or another lookup before approving a definitive reply.
- For numeric totals, taxes, payable amounts, discounts, set-meal totals, and
  aggregate summaries, require the relevant compute/tally/total output when such
  a tool exists.
- For conditional, ranked, replacement, or multi-step mutation requests, verify
  both the final state and the required tool-call path.

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
Never tell the service to ask the user for product/dish names merely because a
read-only lookup uses a visually inferred name. Let official tools canonicalize
that hypothesis first.
Do not reject a tool batch just because a different valid tool sequence might be
more efficient. Reject only clear schema errors, unsupported mutations,
unsupported replies, wrong calculations, missed ties, or clear inactive-branch
use in a mutation/final reply.
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


READ_ONLY_PREFIXES = ("find_", "get_", "list_", "tally_", "compute_")
LOOKUP_PREFIXES = ("find_", "get_", "list_")
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


NAME_LIKE_PARAMETER_KEYS = {
    "product_name",
    "dish_name",
    "recipe_name",
    "ingredient_name",
    "item_name",
    "category",
    "section",
    "restaurant_name",
}


def call_parameters(call: dict[str, Any]) -> dict[str, Any]:
    params = call.get("parameters", {})
    return params if isinstance(params, dict) else {}


def has_name_like_parameter(call: dict[str, Any]) -> bool:
    params = call_parameters(call)
    for key in NAME_LIKE_PARAMETER_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def is_candidate_canonicalization_batch(calls: list[dict[str, Any]]) -> bool:
    if not calls or not all(is_lookup_call(call) for call in calls):
        return False
    return any(has_name_like_parameter(call) for call in calls)


def compact_json(value: Any, max_chars: int = 3000) -> str:
    _ = max_chars
    return json.dumps(value, ensure_ascii=False, default=str)


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
            fact_strings = numeric_fact_strings(products)
            reply_uses_returned_name = any(name and name.lower() in reply_lower for name in returned_names)
            reply_uses_query_name = str(query_name).lower() in reply_lower
            reply_uses_returned_fact = any(fact and re.search(rf"\b{re.escape(fact)}\b", reply_lower) for fact in fact_strings)
            if reply_uses_query_name and not reply_uses_returned_name:
                return (
                    "The proposed reply keeps the visual/OCR query name "
                    f"{query_name!r}, but the lookup returned canonical item(s) {returned_names}. "
                    "Use the returned canonical name or run another lookup before answering."
                )
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
    _ = max_entries
    _ = max_result_chars
    compacted: list[dict[str, Any]] = []
    for entry in tool_logs:
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
    prior_tool_logs: list[dict[str, Any]] | None = None,
    key_frames: list[dict[str, Any]] | None = None,
    service_frames_attached: bool = False,
    proposed: Any,
    proposed_kind: str,
    max_tool_log_entries: int,
    max_tool_result_chars: int,
    max_audit_context_chars: int,
) -> str:
    _ = max_tool_log_entries
    _ = max_tool_result_chars
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
    previous_tool_ledger = compact_tool_logs(
        prior_tool_logs or [],
        max_entries=max_tool_log_entries,
        max_result_chars=max_tool_result_chars,
    )
    important_constraints = [
        "Database facts may come from previous_turn_tool_ledger or current_turn_tool_ledger. Previous-turn results support only facts/actions already established earlier in this same task.",
        "Do not audit visual recognition, OCR quality, frame selection, pointing target identity, or spatial interpretation.",
        "If service_frames_attached_this_turn is true, do not reject because frames, fresh visual context, or key frames are missing.",
        "Read-only calls may be seeded by dialogue or visual hypotheses; reject them only for schema errors or unrelated downstream work.",
        "Mutations and final replies require executed official evidence for canonical target, active branch, quantity, state, ranks/ties, and calculations.",
        "Canonical fields returned by tools override preliminary visual/OCR strings for later calls and replies.",
        "If full visual/OCR lookup fails, prefer one to three distinctive-token read-only retries before user clarification, except unsupported order restaurant_name.",
        "Do not require exhaustive global enumeration when a narrower visual/dialogue boundary or active branch candidate set is supported.",
        "Compute/tally/total tools are required for final numeric totals when such tools exist.",
        "Do not approve shortcuts that omit required intermediate mutations or miss tied state changes.",
        "Validate tool names, parameter names, enum values, intended use, and proposed batch order against official_tool_catalog.",
        "Preserve exact enum semantics; related values are fallback evidence only, not automatic unions for ranking or mutation.",
    ]
    if scenario == "retail":
        important_constraints.extend(
            [
                "For retail, find_products_by_allergen is the official allergen listing tool for allergen inclusion. Validate retail allergen calls against the official tool catalog.",
                "For retail shopping-list comparisons, treat missing/not-yet-added/not-yet-bought/not-yet-purchased as absent from the current cart unless the user explicitly asks to restock, top up, or match the listed quantity.",
                "For retail, complete list tools such as find_products_by_taste and find_products_by_nutritional_characteristic support negative classification when the canonical product is absent from the returned list.",
                "For retail, natural-language high oil/High Oil is equivalent to official nutritional_characteristic high_fat; do not reject high_fat calls or approve refusals merely because high_oil is not an enum.",
                "For retail, natural-language high calorie/low calorie/gluten-free wording may be normalized to official enums high_calories/low_calories/gluten_free.",
            ]
        )
    elif scenario == "order":
        important_constraints.extend(
            [
                "For order, restaurant_name must come from user dialogue, not visual menu titles, logos, OCR, or brand labels.",
                "For order, complete restaurant_name often follows `<name> <nation> Restaurant`; when user wording provides those parts, prefer that composed complete name before treating the restaurant as unsupported. After an unsupported name, allow one structured retry only from user-supplied parts; do not invent missing nation/cuisine or use visual/OCR text.",
                "For order restaurant-name clarification, reject wording that suggests a visual/menu-label guess or unsupported restaurant string as the answer; ask for the pattern only.",
                "For order, user confirmation of an unsupported restaurant label is not DB evidence. If the namespace guard rejected it, apply the rejection only to the exact rejected restaurant_name value; do not generalize it to other user-supplied restaurant names from the same batch. Do not suggest retrying the rejected name; require a different exact full name or use another complete-pattern option from the user.",
                "For order, if no DB-supported complete restaurant_name exists after lookup, require user confirmation before dish/order/set-meal mutations or DB-backed final claims.",
                "For order, natural-language high calorie/low calorie/gluten-free wording may be normalized to official tag enums high_calories/low_calories/gluten_free.",
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
        "dialogue_scope": "filtered user/service dialogue history plus runner/correction feedback needed to explain rejected outputs; official tool execution results are provided via previous_turn_tool_ledger and current_turn_tool_ledger",
        "tool_ledger_scope": "previous turns plus current turn",
        "service_frames_attached_this_turn": bool(service_frames_attached),
        "dialogue_history": dialogue_history,
        "key_frames": [],
        "previous_turn_tool_ledger": previous_tool_ledger,
        "current_turn_tool_ledger": executed_tool_ledger,
        "official_tool_catalog": tool_catalog,
        "important_constraints": important_constraints,
        "visual_grounding_policy": {
            "visual_mapping_audit_enabled": False,
            "correction_receives_images": False,
            "key_frames_available_to_correction": False,
            "service_frames_attached_this_turn": bool(service_frames_attached),
            "dialogue_history_available": True,
            "tool_ledger_current_turn_only": False,
            "previous_turn_tool_ledger_available": True,
            "service_prompt_included": True,
            "read_only_visual_hypothesis_lookup_allowed": True,
            "canonical_output_fields_override_visual_inputs": True,
            "mutation_and_final_reply_require_tool_chain": True,
            "final_numeric_answers_require_compute_when_available": True,
            "process_distinct_mutations_must_not_be_aggregated": True,
        },
    }
    return compact_json(payload, max_chars=0)


def audit_context_stats(audit_context: str) -> dict[str, Any]:
    text = str(audit_context or "")
    return {
        "chars": len(text),
        "context_truncated": False,
        "has_dialogue_history": '"dialogue_history"' in text,
        "has_previous_turn_tool_ledger": '"previous_turn_tool_ledger"' in text,
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
        if is_candidate_canonicalization_batch(calls):
            return (
                "The proposed calls are read-only lookup/canonicalization calls seeded by a "
                "dialogue or visual hypothesis. They may execute before stronger database evidence exists."
            )
        return (
            "All proposed calls are read-only official tools. They do not change database state, "
            "so the service agent can gather evidence, candidates, fields, branch facts, or calculations before deciding next steps."
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
