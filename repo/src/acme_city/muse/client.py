"""The bounded Meta Responses client.

The client is the only place in the application that may talk to the provider.
It sends one request per run, never retries, never enables a tool or a web
search and never sends ``response_format``.  The structured output is always
requested through ``text.format`` with ``strict: true``.

The provider credential is injected into the request header at dispatch time
only.  It is never part of a payload, never part of a recorded run and never
part of a log line: the recorded request summary carries the method, the URL,
the model and a body hash instead.
"""
# REQUIRES: AI-01, AI-02, AI-03, AI-04
# The provider boundary is a single non-retrying POST to the Responses endpoint with a
# bearer credential injected at dispatch, a strict JSON schema, a bounded output budget,
# no tools and no web search.

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Final

import httpx

from acme_city.core.config import Settings

#: The one endpoint a Muse run may call.
META_RESPONSES_URL: Final = "https://api.meta.ai/v1/responses"

#: The largest input a single run may reserve.
MAX_INPUT_TOKENS: Final = 4000

#: The largest output a single run may reserve.  Muse counts reasoning tokens
#: against this budget, so it must leave room for both reasoning and the JSON.
MAX_OUTPUT_TOKENS: Final = 4000

#: The output budget of a what-if briefing, explanation or proposal.  A live
#: briefing used 3,290 of 4,000 tokens on reasoning and was cut off before its
#: JSON was complete, so the policy tasks reserve more.
POLICY_MAX_OUTPUT_TOKENS: Final = 12000

#: The hard ceiling on any run's output budget.
MAX_OUTPUT_CEILING: Final = POLICY_MAX_OUTPUT_TOKENS

#: The default request timeout, in seconds.
DEFAULT_TIMEOUT_SECONDS: Final = 30.0

#: Why a call is refused when the global provider switch is off.
PROVIDER_DISABLED_ERROR: Final = (
    "external AI provider calls are disabled in this deployment "
    "(ACME_MUSE_PROVIDER_ENABLED)"
)

#: The placeholder that replaces a credential in any recorded text.
REDACTED: Final = "[redacted]"

#: The request keys that are never allowed in a payload.
FORBIDDEN_REQUEST_KEYS: Final = frozenset(
    {
        "response_format",
        "tools",
        "tool_choice",
        "functions",
        "web_search_options",
        "web_search",
        "browsing",
        "file_search",
        "code_interpreter",
    }
)


def live_call_block_reason(settings: Settings) -> str | None:
    """Return why a live provider call is locked out, or ``None`` when it may go."""
    if settings.public_demo and not settings.muse_live_calls_allowed:
        return "live Muse calls are locked on the hosted demo (ACME_MUSE_LIVE_CALLS_ALLOWED)"
    return None


def assert_live_call_allowed(settings: Settings) -> None:
    """Raise :class:`MuseLiveCallBlocked` unless a live call is allowed."""
    reason = live_call_block_reason(settings)
    if reason is not None:
        raise MuseLiveCallBlocked(reason)


class MuseRequestError(ValueError):
    """The payload violates the provider request contract.

    The error is raised before any network call: a payload that names a model
    outside the allowlist, enables a tool or carries an unbounded output
    budget is never dispatched.
    """


class MuseLiveCallBlocked(MuseRequestError):
    """A live provider call was refused by the hosted dispatch lock.

    It is a request error, so every caller that records a refused request
    records this one the same way.  It is raised before any network I/O, even
    when a credential is configured.  Replay and cassette paths never reach the
    dispatch layer.

    The callers record it as a provider error, which the live-call error stop
    counts: after enabling ``ACME_MUSE_LIVE_CALLS_ALLOWED`` on a non-hosted
    instance that had refused a live run, reset the demo.  The budget is
    OPR-14's to refine.
    """


@dataclass(frozen=True)
class ProviderResponse:
    """What the provider returned, reduced to the fields a run records."""

    response_id: str | None = None
    model: str | None = None
    status: str = "unknown"
    output_text: str | None = None
    output: list[Any] = field(default_factory=list)
    error: str | None = None
    incomplete_details: dict[str, Any] | None = None
    refusal: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        """Return whether the provider answered without an error."""
        return self.error is None and self.status in {"completed", "succeeded"}

    def to_dict(self) -> dict[str, Any]:
        """Return the dictionary form of the response."""
        return {
            "response_id": self.response_id,
            "model": self.model,
            "status": self.status,
            "output_text": self.output_text,
            "output": self.output,
            "error": self.error,
            "incomplete_details": self.incomplete_details,
            "refusal": self.refusal,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
            "http_status": self.http_status,
        }


def redact_secret(text: str, secret: str | None) -> str:
    """Return ``text`` with the provider credential removed.

    The credential is never logged or stored.  This helper makes sure a
    provider error that quotes the request cannot carry it into a run record.
    """
    if not text:
        return text
    if secret:
        text = text.replace(secret, REDACTED)
    return text


def _as_int(value: Any) -> int:
    """Return ``value`` as an integer, or zero when it is not one."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_usage(body: dict[str, Any]) -> dict[str, int]:
    """Return the usage counters of one provider response.

    The counters are reported as they arrive: the input tokens, the cached
    input tokens, the output tokens, the reasoning tokens and the total.
    """
    usage = body.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    input_details = usage.get("input_tokens_details")
    if not isinstance(input_details, dict):
        input_details = {}
    output_details = usage.get("output_tokens_details")
    if not isinstance(output_details, dict):
        output_details = {}
    return {
        "input_tokens": _as_int(usage.get("input_tokens")),
        "cached_input_tokens": _as_int(input_details.get("cached_tokens")),
        "output_tokens": _as_int(usage.get("output_tokens")),
        "reasoning_tokens": _as_int(output_details.get("reasoning_tokens")),
        "total_tokens": _as_int(usage.get("total_tokens")),
    }


def extract_output_text(body: dict[str, Any]) -> tuple[str | None, list[Any], str | None]:
    """Return the output text, the raw output items and a refusal, if any."""
    output = body.get("output")
    if not isinstance(output, list):
        output = []
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct, output, None
    texts: list[str] = []
    refusal: str | None = None
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "refusal":
            value = item.get("refusal") or item.get("text")
            refusal = str(value) if value else "the model refused the request"
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_text", "text"}:
                value = part.get("text")
                if isinstance(value, str):
                    texts.append(value)
    text = "\n".join(texts).strip() if texts else None
    return text, output, refusal


def summarize_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a log-safe summary of an outbound request.

    The summary never carries a header, a credential or the body itself: it
    carries the method, the URL, the model, the requested schema name, the
    output budget and a hash of the body.
    """
    text_format = payload.get("text")
    schema_name = None
    if isinstance(text_format, dict):
        fmt = text_format.get("format")
        if isinstance(fmt, dict):
            schema_name = fmt.get("name")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "method": "POST",
        "url": META_RESPONSES_URL,
        "model": payload.get("model"),
        "schema_name": schema_name,
        "max_output_tokens": payload.get("max_output_tokens"),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


class MuseClient:
    """Sends one bounded request to the Meta Responses endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        budget: Any = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = timeout_seconds
        #: The daily allowance of provider calls.  When it is given, one call is
        #: reserved before the request leaves; a client without one is used by
        #: the tests that inject their own transport.
        self._budget = budget
        self.request_summary: dict[str, Any] | None = None

    # ------------------------------------------------------------------ checks

    def check_payload(self, payload: dict[str, Any]) -> None:
        """Refuse a payload that breaks the provider request contract.

        Raises:
            MuseRequestError: when the payload names a model outside the
                allowlist, enables a tool or a web search, asks for
                ``response_format``, misses the strict JSON schema or exceeds
                the output budget.
        """
        if not isinstance(payload, dict):
            raise MuseRequestError("the provider payload must be a mapping")
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            raise MuseRequestError("the provider payload must name a model")
        if not self._settings.model_is_allowed(model):
            raise MuseRequestError(
                f"model {model!r} is outside the configured Standard allowlist"
            )
        for key in FORBIDDEN_REQUEST_KEYS:
            if key in payload:
                raise MuseRequestError(f"the provider payload must not carry {key!r}")
        text = payload.get("text")
        if not isinstance(text, dict):
            raise MuseRequestError("the provider payload must declare a strict text format")
        fmt = text.get("format")
        if not isinstance(fmt, dict):
            raise MuseRequestError("the provider payload must declare a strict text format")
        if fmt.get("type") != "json_schema":
            raise MuseRequestError("the structured output must use the json_schema format")
        if fmt.get("strict") is not True:
            raise MuseRequestError("the structured output must be strict")
        if not isinstance(fmt.get("name"), str) or not fmt.get("name"):
            raise MuseRequestError("the structured output must carry a schema name")
        if not isinstance(fmt.get("schema"), dict):
            raise MuseRequestError("the structured output must carry a JSON schema")
        budget = payload.get("max_output_tokens")
        if not isinstance(budget, int) or budget <= 0:
            raise MuseRequestError("the provider payload must bound the output budget")
        if budget > MAX_OUTPUT_CEILING:
            raise MuseRequestError(
                f"the output budget must not exceed {MAX_OUTPUT_CEILING} tokens"
            )

    # ---------------------------------------------------------------- dispatch

    def create_response(self, payload: dict[str, Any]) -> ProviderResponse:
        """Send one request and return what the provider answered.

        The request is sent exactly once.  A failure is returned as a failed
        response rather than raised, so that the failure can be recorded as an
        immutable run.  A request the hosted dispatch lock refuses is the one
        exception: it raises :class:`MuseLiveCallBlocked`.  A request the daily
        allowance refuses raises :class:`~acme_city.muse.budget.MuseBudgetExceeded`
        before anything is sent.
        """
        self.check_payload(payload)
        self.request_summary = summarize_request(payload)

        # The global switch is enforced here, at the one place that talks to the
        # provider, so every caller (the general command, the applicant assistant,
        # the policy tasks and the triage summary) honours it.
        if not self._settings.provider_enabled:
            return ProviderResponse(status="failed", error=PROVIDER_DISABLED_ERROR)

        assert_live_call_allowed(self._settings)

        key = self._settings.meta_api_key
        secret = key.get_secret_value() if key is not None else ""
        if not secret:
            return ProviderResponse(
                status="failed",
                error="no provider credential is configured for this service",
            )

        # The daily allowance is checked and reserved here, after the hosted
        # lock and before the transport: the lock wins, and a day without room
        # sends nothing.
        if self._budget is not None:
            self._budget.reserve()

        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        started = time.monotonic()
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
            ) as client:
                response = client.post(
                    META_RESPONSES_URL,
                    headers=headers,
                    content=json.dumps(payload, default=str).encode("utf-8"),
                )
        except httpx.HTTPError as exc:
            latency = int((time.monotonic() - started) * 1000)
            return ProviderResponse(
                status="failed",
                error=redact_secret(f"the provider request failed: {exc}", secret),
                latency_ms=latency,
            )
        latency = int((time.monotonic() - started) * 1000)

        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        output_text, output, refusal = extract_output_text(body)
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or "the provider reported an error"
            error_text = str(message)
        elif isinstance(error, str) and error:
            error_text = error
        else:
            error_text = None

        status = str(body.get("status") or ("completed" if response.is_success else "failed"))
        if response.status_code >= 400 and error_text is None:
            error_text = f"the provider answered with HTTP {response.status_code}"

        incomplete = body.get("incomplete_details")
        if not isinstance(incomplete, dict):
            incomplete = None

        return ProviderResponse(
            response_id=str(body["id"]) if body.get("id") else None,
            model=str(body["model"]) if body.get("model") else None,
            status=status,
            output_text=output_text,
            output=output,
            error=redact_secret(error_text, secret) if error_text else None,
            incomplete_details=incomplete,
            refusal=redact_secret(refusal, secret) if refusal else None,
            usage=extract_usage(body),
            latency_ms=latency,
            http_status=response.status_code,
        )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "FORBIDDEN_REQUEST_KEYS",
    "MAX_INPUT_TOKENS",
    "MAX_OUTPUT_CEILING",
    "MAX_OUTPUT_TOKENS",
    "POLICY_MAX_OUTPUT_TOKENS",
    "META_RESPONSES_URL",
    "PROVIDER_DISABLED_ERROR",
    "MuseClient",
    "MuseLiveCallBlocked",
    "MuseRequestError",
    "ProviderResponse",
    "REDACTED",
    "assert_live_call_allowed",
    "extract_output_text",
    "extract_usage",
    "live_call_block_reason",
    "redact_secret",
    "summarize_request",
]
