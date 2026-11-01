"""The bounded Meta image client, next to the Responses client.

This client is the only place that may ask the provider for an icon image.
It sends one request per generation attempt, never retries, and uses a
60-second timeout.  The response item must carry ``b64_json``: a ``url``
response is a failure, because following it would be an outbound fetch the
application never performs.

The provider credential is injected into the request header at dispatch
time only.  It is never part of a payload, never part of a stored prompt
or audit record, and never part of a log line: errors are redacted with it.
"""
# REQUIRES: AI-01, AI-03
# The image boundary is a single non-retrying POST to the image generations
# endpoint with a bearer credential injected at dispatch; b64_json only.

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from acme_city.core.config import Settings
from acme_city.muse.budget import MuseBudgetExceeded
from acme_city.muse.client import live_call_block_reason, redact_secret

#: The one endpoint an icon generation may call.
META_IMAGES_URL: Final = "https://api.meta.ai/v1/images/generations"

#: The image model used for permit type icons.
IMAGE_MODEL: Final = "muse-image-1.0"

#: The fixed request timeout, in seconds.  One request, no retry.
IMAGE_TIMEOUT_SECONDS: Final = 60.0

#: Estimated cost of one generation attempt, in USD.
IMAGE_COST_ESTIMATE_USD: Final = 0.01


def describe_image(data: bytes) -> tuple[str, int, int] | None:
    """Return ``(media_type, width, height)`` for PNG, JPEG or WebP bytes.

    The dimensions come from the image header only; anything that does not
    parse is refused rather than stored.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return "image/png", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8 ":
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return "image/webp", width, height
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return "image/webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8X":
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return "image/webp", width, height
        return None
    if data.startswith(b"\xff\xd8\xff"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                return None
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                height = int.from_bytes(data[index + 5 : index + 7], "big")
                width = int.from_bytes(data[index + 7 : index + 9], "big")
                return "image/jpeg", width, height
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            if length < 2:
                return None
            index += 2 + length
        return None
    return None


def wrap_icon_prompt(sentence: str) -> str:
    """Wrap an administrator's sentence in the fixed civic icon style.

    The palette is the palette of the City of Acme website: civic blue,
    deep navy and gold on a white tile.  A picture in any other colour does
    not belong to the site it stands on.
    """
    return (
        "Flat vector icon on a rounded-square soft tile, City of Acme palette: "
        "civic blue #1a5fa0, deep navy #12304f and gold #f0b323 on a white tile, "
        "simple bold shapes, generous padding, flat even lighting, no text, no letters, "
        f"no numbers, no logos, no watermarks. Subject: {sentence}"
    )


@dataclass(frozen=True)
class ImageResult:
    """What one generation attempt produced."""

    ok: bool
    image_data: bytes = b""
    media_type: str = ""
    status: str = "failed"
    error: str | None = None
    http_status: int | None = None
    response_size: int = 0
    latency_ms: int = 0

    @property
    def image_bytes(self) -> bytes:
        """Return the decoded image bytes (empty when the attempt failed)."""
        return self.image_data


class MuseImageClient:
    """Sends one bounded request to the Meta image generations endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = IMAGE_TIMEOUT_SECONDS,
        budget: Any = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = timeout_seconds
        #: The daily allowance of provider calls.  When it is given, one call is
        #: reserved before the request leaves.
        self._budget = budget

    def generate(self, prompt: str) -> ImageResult:
        """Send one generation request and return what the provider answered.

        Exactly one request is sent.  A failure is returned rather than
        raised, so that the attempt can be recorded with its real status.
        """
        if not self._settings.provider_enabled:
            return ImageResult(
                ok=False,
                error="external AI provider calls are disabled in this deployment "
                "(ACME_MUSE_PROVIDER_ENABLED)",
            )
        blocked = live_call_block_reason(self._settings)
        if blocked is not None:
            return ImageResult(ok=False, error=blocked)
        key = self._settings.meta_api_key
        secret = key.get_secret_value() if key is not None else ""
        if not secret:
            return ImageResult(
                ok=False,
                error="no provider credential is configured for this service",
            )
        # The daily allowance is checked and reserved here, after the hosted
        # lock and before the transport: the lock wins, and a day without room
        # sends nothing.
        if self._budget is not None:
            try:
                self._budget.reserve()
            except MuseBudgetExceeded as exc:
                return ImageResult(ok=False, error=str(exc))
        payload = {"model": IMAGE_MODEL, "prompt": prompt, "n": 1}
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
                    META_IMAGES_URL,
                    headers=headers,
                    content=json.dumps(payload).encode("utf-8"),
                )
        except httpx.HTTPError as exc:
            latency = int((time.monotonic() - started) * 1000)
            return ImageResult(
                ok=False,
                error=redact_secret(
                    f"the provider request failed: {type(exc).__name__}", secret
                ),
                latency_ms=latency,
            )
        latency = int((time.monotonic() - started) * 1000)
        body_bytes = response.content or b""
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        items = body.get("data")
        item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        encoded = item.get("b64_json")
        if isinstance(encoded, str) and encoded:
            # Success: the recorded size is the delivered image size.
            try:
                image = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return ImageResult(
                    ok=False,
                    error="the provider returned image data that is not valid base64",
                    http_status=response.status_code,
                    response_size=len(body_bytes),
                    latency_ms=latency,
                )
            described = describe_image(image)
            if described is None:
                return ImageResult(
                    ok=False,
                    error="the provider returned bytes that are not a PNG, JPEG or WebP image",
                    http_status=response.status_code,
                    response_size=len(image),
                    latency_ms=latency,
                )
            return ImageResult(
                ok=True,
                image_data=image,
                media_type=described[0],
                status="succeeded",
                http_status=response.status_code,
                response_size=len(image),
                latency_ms=latency,
            )
        if isinstance(item.get("url"), str) and item["url"]:
            # A URL-only answer is a failure: no outbound fetch is ever made.
            return ImageResult(
                ok=False,
                error=(
                    "the provider answered with an image URL instead of image data; "
                    "URL responses are not fetched"
                ),
                http_status=response.status_code,
                response_size=len(body_bytes),
                latency_ms=latency,
            )
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or "the provider reported an error"
            error_text = str(message)
        elif isinstance(error, str) and error:
            error_text = error
        elif response.status_code >= 400:
            error_text = f"the provider answered with HTTP {response.status_code}"
        else:
            error_text = "the provider returned no image item"
        return ImageResult(
            ok=False,
            error=redact_secret(error_text, secret),
            http_status=response.status_code,
            response_size=len(body_bytes),
            latency_ms=latency,
        )


__all__ = [
    "IMAGE_COST_ESTIMATE_USD",
    "IMAGE_MODEL",
    "IMAGE_TIMEOUT_SECONDS",
    "META_IMAGES_URL",
    "ImageResult",
    "MuseImageClient",
    "describe_image",
    "wrap_icon_prompt",
]
