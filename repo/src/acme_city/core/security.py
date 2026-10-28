"""Security headers and trusted-proxy handling (both deployment modes).

The Content Security Policy matches what the interface really loads: local
scripts, local stylesheets, local images and same-origin requests.  No page uses
an inline script or an inline event handler.  A few templates carry inline
``style`` attributes; those are allowed through ``style-src-attr`` only (an
attribute can restyle an element but cannot run code).  The two downloadable
HTML documents (the permit artifact and the application copy) carry an inline
``<style>`` block and no script at all, so they get their own stricter policy.
"""

from __future__ import annotations

from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from acme_city.auth.service import DEFAULT_COOKIE_NAME

#: The policy of every application page.
PAGE_CSP: Final = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "style-src-attr 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

#: The policy of a downloaded HTML document: no script, one inline stylesheet.
DOCUMENT_CSP: Final = "; ".join(
    (
        "default-src 'none'",
        "style-src 'unsafe-inline'",
        "img-src 'self' data:",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)

#: The policy of the generated API documentation pages (demo mode only; the
#: pages load Swagger UI from a public CDN and start it with an inline script).
DOCS_CSP: Final = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    "https://fastapi.tiangolo.com; frame-ancestors 'none'"
)
DOCS_PATHS: Final = ("/docs", "/redoc", "/docs/oauth2-redirect")

HSTS: Final = "max-age=31536000; includeSubDomains"
STATIC_PREFIX: Final = "/ui/static"


class SecurityHeadersMiddleware:
    """Add the security headers to every HTTP response."""

    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_headers = Headers(scope=scope)
        path = scope.get("path", "")
        has_session = f"{DEFAULT_COOKIE_NAME}=" in request_headers.get("cookie", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                content_type = headers.get("content-type", "")
                is_html = content_type.startswith("text/html")
                if "content-security-policy" not in headers:
                    if path in DOCS_PATHS and not self.production:
                        headers["Content-Security-Policy"] = DOCS_CSP
                    elif is_html and "attachment" in headers.get("content-disposition", ""):
                        headers["Content-Security-Policy"] = DOCUMENT_CSP
                    else:
                        headers["Content-Security-Policy"] = PAGE_CSP
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "same-origin"
                # A route that allows same-origin framing (the in-app document
                # viewer) gets the matching legacy header; everything else is DENY.
                framed = "frame-ancestors 'self'" in headers.get("content-security-policy", "")
                headers["X-Frame-Options"] = "SAMEORIGIN" if framed else "DENY"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if self.production:
                    headers["Strict-Transport-Security"] = HSTS
                if (
                    "cache-control" not in headers
                    and not path.startswith(STATIC_PREFIX)
                    and (has_session or "set-cookie" in headers)
                    and (is_html or content_type.startswith("application/json") or not content_type)
                ):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class TrustedProxyMiddleware:
    """Honour ``X-Forwarded-Proto`` from a reverse proxy (opt-in, off by default).

    Only enable this when the service is reachable solely through the proxy: any
    client that can reach the service directly could otherwise claim ``https``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            proto = Headers(scope=scope).get("x-forwarded-proto", "").split(",")[0].strip().lower()
            if proto in {"http", "https"}:
                scope = dict(scope)
                scope["scheme"] = proto if scope["type"] == "http" else {"http": "ws", "https": "wss"}[proto]
        await self.app(scope, receive, send)


__all__ = [
    "DOCS_CSP",
    "DOCUMENT_CSP",
    "HSTS",
    "PAGE_CSP",
    "SecurityHeadersMiddleware",
    "TrustedProxyMiddleware",
]
