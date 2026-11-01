"""Public-demo protection: per-client rate limits and a bounded request size.

Anyone who reaches a public demonstration can act as any persona, so the
service limits how fast one client address can call it.  The limits are small,
in memory and dependency free: a token bucket per client address and per limit.
They reset when the process restarts, which suits a demonstration whose data is
rebuilt on every start.  They are not a defence against a distributed attack;
put the service behind the host's edge protection for that.

Client address
--------------
Without ``ACME_TRUST_PROXY_HEADERS`` the client is the socket peer, and
``X-Forwarded-For`` is ignored (any client could forge it).  With it, the
client is the right-most address in ``X-Forwarded-For`` that is not a trusted
proxy.  The proxy in front appends the address it received the request from,
so the right-most entries come from infrastructure and the left-most entries
are whatever the client claimed.  Reading from the right therefore cannot be
forged by a client that sends its own header.  The addresses skipped as
trusted are, from the right, the first ``ACME_TRUSTED_PROXY_HOPS`` entries
(extra proxies the operator knows about, such as a CDN) and any private,
loopback or link-local address.  When nothing usable is left the socket peer
is used.
"""

from __future__ import annotations

import ipaddress
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Paths no limit applies to: the health checks and the static files (a page
#: loads several of them, so counting them would spend the allowance on assets).
EXEMPT_PREFIXES: Final = ("/ui/static", "/readyz", "/healthz")
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
#: Requests that switch or end a persona session.
SESSION_PATHS: Final = frozenset({"/ui/actor", "/ui/end", "/api/session/select", "/api/session"})
#: The applicant form's background check and its pre-submit review.  Both
#: repeat while the applicant is still editing and the server writes no case,
#: so each counts as a read: neither spends the upload allowance a real
#: submission needs.
FORM_CHECK_PATH: Final = re.compile(r"^/apply/[a-z0-9_-]+/(?:check|review)/?$")
MAX_TRACKED_CLIENTS: Final = 20_000

LIMIT_ALL: Final = "all"
LIMIT_WRITE: Final = "write"
LIMIT_SESSION: Final = "session"
LIMIT_UPLOAD: Final = "upload"
LIMIT_LABELS: Final = {
    LIMIT_ALL: "requests",
    LIMIT_WRITE: "changes",
    LIMIT_SESSION: "user switches",
    LIMIT_UPLOAD: "uploads",
}


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _is_internal(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_private or address.is_loopback or address.is_link_local


def resolve_client_ip(
    scope: Scope, *, trust_proxy_headers: bool = False, trusted_hops: int = 0
) -> str:
    """Return the client address used as the rate-limit key (see module docstring)."""
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if not trust_proxy_headers:
        return peer
    values = Headers(scope=scope).getlist("x-forwarded-for")
    chain = [part.strip() for value in values for part in value.split(",") if part.strip()]
    candidates = chain[: max(len(chain) - trusted_hops, 0)] if trusted_hops else chain
    for entry in reversed(candidates):
        if not _is_ip(entry):
            break
        if _is_internal(entry):
            continue
        return entry
    return peer


class TokenBucketLimiter:
    """A token bucket per key: ``per_minute`` requests a minute, burst of the same size."""

    def __init__(
        self, per_minute: int, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def _level(self, key: str, now: float) -> float:
        tokens, stamp = self._buckets.get(key, (self.capacity, now))
        return min(self.capacity, tokens + (now - stamp) * self.rate)

    def retry_after(self, key: str) -> float:
        """Return the seconds until ``key`` has a token (0 when it has one)."""
        level = self._level(key, self._clock())
        return 0.0 if level >= 1.0 else (1.0 - level) / self.rate

    def take(self, key: str) -> None:
        """Spend one token for ``key``; call only after ``retry_after`` returned 0."""
        now = self._clock()
        self._buckets[key] = (self._level(key, now) - 1.0, now)
        if len(self._buckets) > MAX_TRACKED_CLIENTS:
            self._prune(now)

    def _prune(self, now: float) -> None:
        for stale in [k for k in self._buckets if self._level(k, now) >= self.capacity]:
            del self._buckets[stale]
        while len(self._buckets) > MAX_TRACKED_CLIENTS:
            del self._buckets[next(iter(self._buckets))]


@dataclass(frozen=True)
class RateLimitConfig:
    """Requests per minute for each limit; ``0`` switches that limit off."""

    all_per_minute: int = 0
    write_per_minute: int = 0
    session_per_minute: int = 0
    upload_per_minute: int = 0
    trust_proxy_headers: bool = False
    trusted_hops: int = 0

    @property
    def enabled(self) -> bool:
        return any(
            (self.all_per_minute, self.write_per_minute, self.session_per_minute, self.upload_per_minute)
        )


def classify(method: str, path: str, content_type: str) -> list[str]:
    """Return the limits a request counts against (empty when exempt)."""
    if path.startswith(EXEMPT_PREFIXES):
        return []
    if method == "POST" and FORM_CHECK_PATH.fullmatch(path):
        return [LIMIT_ALL]  # the form's background check and pre-submit review are reads
    limits = [LIMIT_ALL]
    if method not in SAFE_METHODS:
        limits.append(LIMIT_WRITE)
        if path.rstrip("/") in SESSION_PATHS:
            limits.append(LIMIT_SESSION)
        if content_type.lower().startswith("multipart/form-data"):
            limits.append(LIMIT_UPLOAD)
    return limits


def _wants_json(headers: Headers, path: str) -> bool:
    accept = headers.get("accept", "")
    return path.startswith("/api/") or ("application/json" in accept and "text/html" not in accept)


def _render_limited_page(limit: str, retry: int) -> str:
    from acme_city.ui.router import templates

    return templates.get_template("rate_limited_page.html").render(
        retry_after=retry, what=LIMIT_LABELS[limit]
    )


def limited_response(limit: str, retry: int, *, as_json: bool) -> Response:
    """Build the 429 answer: JSON for API callers, the application page otherwise."""
    headers = {"Retry-After": str(retry), "Cache-Control": "no-store"}
    if as_json:
        return JSONResponse(
            {
                "code": "rate_limited",
                "message": f"Too many {LIMIT_LABELS[limit]} from this address. Try again in {retry} seconds.",
            },
            status_code=429,
            headers=headers,
        )
    return Response(
        _render_limited_page(limit, retry),
        status_code=429,
        media_type="text/html",
        headers=headers,
    )


class RateLimitMiddleware:
    """Answer 429 when a client address is over any limit that applies to a request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: RateLimitConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.config = config
        self.limiters: dict[str, TokenBucketLimiter] = {}
        for name, per_minute in (
            (LIMIT_ALL, config.all_per_minute),
            (LIMIT_WRITE, config.write_per_minute),
            (LIMIT_SESSION, config.session_per_minute),
            (LIMIT_UPLOAD, config.upload_per_minute),
        ):
            if per_minute > 0:
                self.limiters[name] = TokenBucketLimiter(per_minute, clock=clock)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = resolve_client_ip(
            scope,
            trust_proxy_headers=self.config.trust_proxy_headers,
            trusted_hops=self.config.trusted_hops,
        )
        # Other code (the community limiter) keys on the same resolved address.
        scope["acme_client_ip"] = client
        if not self.limiters:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        path = scope.get("path", "")
        applicable = [
            name
            for name in classify(scope["method"], path, headers.get("content-type", ""))
            if name in self.limiters
        ]
        if not applicable:
            await self.app(scope, receive, send)
            return
        # Check every limit first so a refused request spends nothing.
        for name in applicable:
            wait = self.limiters[name].retry_after(client)
            if wait > 0:
                response = limited_response(
                    name, max(1, math.ceil(wait)), as_json=_wants_json(headers, path)
                )
                await response(scope, receive, send)
                return
        for name in applicable:
            self.limiters[name].take(client)
        await self.app(scope, receive, send)


class MaxBodyMiddleware:
    """Refuse a request body larger than ``max_bytes`` with 413.

    The declared ``Content-Length`` is checked first; a body without one (or
    one that lies) is counted as it streams.  Past the limit the application is
    told the client disconnected (it never sees the rest of the body, so it
    cannot act on a truncated one) and whatever it answers is replaced by 413.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._refuse(scope, receive, send)
            return
        received = 0
        exceeded = False
        answered = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal answered
            if exceeded:
                return  # the 413 below replaces whatever the application said
            if message["type"] == "http.response.start":
                answered = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not answered:
            await self._refuse(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        megabytes = max(1, self.max_bytes // (1024 * 1024))
        response = JSONResponse(
            {
                "code": "request_too_large",
                "message": f"The request is larger than the {megabytes} MB limit.",
            },
            status_code=413,
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)


__all__ = [
    "MaxBodyMiddleware",
    "RateLimitConfig",
    "RateLimitMiddleware",
    "TokenBucketLimiter",
    "classify",
    "limited_response",
    "resolve_client_ip",
]
