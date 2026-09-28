"""Client for the Studio99 Indic Typography API (v1).

Standard library only. Server-side only: never ship your API key to a browser or app.
Docs: https://studio99.app/developers/docs
"""

from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Mapping, Optional, TypeVar

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://studio99.app/api/v1"

T = TypeVar("T")


@dataclass(frozen=True)
class RateLimit:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset: Optional[int] = None  # unix seconds


@dataclass(frozen=True)
class Response(Generic[T]):
    """What every method returns: the payload plus the metering that came with it."""

    data: T
    usage: Optional[Dict[str, Any]] = None
    rate_limit: RateLimit = field(default_factory=RateLimit)


class Studio99Error(Exception):
    """A failed call. ``code`` is the API error code, e.g. ``INSUFFICIENT_CREDITS``."""

    def __init__(self, message: str, code: str, status: int, rate_limit: Optional[RateLimit] = None):
        super().__init__(f"{code}: {message}")
        self.message = message
        self.code = code
        self.status = status  # HTTP status, 0 for network/timeout errors
        self.rate_limit = rate_limit


class _Library:
    def __init__(self, client: "Studio99"):
        self._c = client

    def search(self, q: Optional[str] = None, *, category: Optional[str] = None, language: Optional[str] = None,
               page: Optional[int] = None, limit: Optional[int] = None) -> Response[Dict[str, Any]]:
        """Free read."""
        return self._c._request("GET", "/library/search",
                                query={"q": q, "category": category, "language": language, "page": page, "limit": limit})

    def get(self, id: str) -> Response[Dict[str, Any]]:
        """Free read. ``id`` may be the id, shortId or slug."""
        return self._c._request("GET", f"/library/{urllib.parse.quote(id, safe='')}")

    def download(self, id: str, format: str = "PNG") -> Response[Dict[str, Any]]:
        """1 credit. Returns a signed ``downloadUrl`` valid for 5 minutes."""
        return self._c._request("GET", f"/library/{urllib.parse.quote(id, safe='')}/download", query={"format": format})

    def render_svg(self, id: str) -> Response[Dict[str, Any]]:
        """1 credit. Only for artworks whose detail has ``canRenderSvg: true``."""
        return self._c._request("GET", f"/library/{urllib.parse.quote(id, safe='')}/render-svg")


class Studio99:
    """Studio99 Indic Typography API client.

    >>> s99 = Studio99()  # reads STUDIO99_API_KEY
    >>> res = s99.generate("shubh vivah", language="hindi", use_case="wedding", count=4)
    >>> res.data["generatedResults"][0]["svg"]["svgString"]
    """

    def __init__(self, api_key: Optional[str] = None, *, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 60.0, max_retries: int = 2):
        key = api_key or os.environ.get("STUDIO99_API_KEY")
        if not key:
            raise ValueError("Studio99: missing API key. Pass api_key=... or set STUDIO99_API_KEY.")
        self._api_key = key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self.library = _Library(self)

    def __repr__(self) -> str:  # never print the key
        return f"Studio99(base_url={self._base_url!r})"

    # ---- metered -----------------------------------------------------------

    def generate(self, text: str, **options: Any) -> Response[Dict[str, Any]]:
        """Styled calligraphy variants of ``text``. 1 credit per variant returned.

        Options (all optional): language, count, format ("svg" | "png"), pngWidth, fontId,
        use_case, mood, engine, align, lines, lineGap, recipe, seed.
        """
        return self._request("POST", "/generate", body={"text": text, **options})

    def render(self, text: str, font_id: str, *, font_size: Optional[float] = None,
               format: Optional[str] = None, png_width: Optional[int] = None) -> Response[Dict[str, Any]]:
        """``text`` in one exact font. Deterministic. 1 credit."""
        body: Dict[str, Any] = {"text": text, "fontId": font_id}
        if font_size is not None:
            body["fontSize"] = font_size
        if format is not None:
            body["format"] = format
        if png_width is not None:
            body["pngWidth"] = png_width
        return self._request("POST", "/render", body=body)

    # ---- free reads ---------------------------------------------------------

    def fonts(self, *, language: Optional[str] = None, mood: Optional[str] = None,
              use_case: Optional[str] = None, limit: Optional[int] = None) -> Response[Dict[str, Any]]:
        """The curated font slate. Free read."""
        return self._request("GET", "/fonts", query={"language": language, "mood": mood, "use_case": use_case, "limit": limit})

    def capabilities(self) -> Response[Dict[str, Any]]:
        return self._request("GET", "/capabilities")

    def health(self) -> Response[Dict[str, Any]]:
        return self._request("GET", "/health", unwrapped=True)

    # ---- transport ----------------------------------------------------------

    def _request(self, method: str, path: str, *, query: Optional[Mapping[str, Any]] = None,
                 body: Optional[Mapping[str, Any]] = None, unwrapped: bool = False) -> Response[Any]:
        url = self._base_url + path
        params = {k: v for k, v in (query or {}).items() if v is not None and v != ""}
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "X-API-Key": self._api_key,
            "Accept": "application/json",
            "User-Agent": f"studio99-python/{__version__}",
        }
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        idempotent = method == "GET"

        attempt = 0
        while True:
            can_retry = attempt < self._max_retries
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as res:
                    status, raw, hdrs = res.status, res.read(), res.headers
            except urllib.error.HTTPError as e:
                status, raw, hdrs = e.code, e.read(), e.headers
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                # A POST may have reached the engine: never retry it, so nobody is charged twice.
                if idempotent and can_retry:
                    time.sleep(_backoff(attempt))
                    attempt += 1
                    continue
                timed_out = isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e)
                raise Studio99Error(str(e), "TIMEOUT" if timed_out else "NETWORK_ERROR", 0) from None

            rate_limit = _rate_limit(hdrs)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except ValueError:
                payload = None

            ok = 200 <= status < 300
            if ok and unwrapped and payload is not None:
                return Response(data=payload, rate_limit=rate_limit)
            if ok and isinstance(payload, dict) and payload.get("success"):
                return Response(data=payload.get("data"), usage=payload.get("usage"), rate_limit=rate_limit)

            err = (payload or {}).get("error") if isinstance(payload, dict) else None
            code = (err or {}).get("code") or "UNKNOWN"
            message = (err or {}).get("message") or f"HTTP {status}"

            if can_retry and status == 429 and code == "RATE_LIMIT_EXCEEDED":
                wait = (rate_limit.reset - time.time() + 0.25) if rate_limit.reset else _backoff(attempt)
                time.sleep(min(max(wait, 0.25), 60.0))
                attempt += 1
                continue
            if can_retry and idempotent and 502 <= status <= 504:
                time.sleep(_backoff(attempt))
                attempt += 1
                continue
            raise Studio99Error(message, code, status, rate_limit)


def _rate_limit(headers: Any) -> RateLimit:
    def num(name: str) -> Optional[int]:
        v = headers.get(name) if headers is not None else None
        try:
            return int(v) if v is not None else None
        except ValueError:
            return None

    return RateLimit(num("X-RateLimit-Limit"), num("X-RateLimit-Remaining"), num("X-RateLimit-Reset"))


def _backoff(attempt: int) -> float:
    return 0.5 * (2 ** attempt) + random.random() * 0.25
