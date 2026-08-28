"""Small JSON-over-HTTP helper built on urllib (no third-party deps)."""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "pm-internship-watcher/1.0 (personal job alert script)"

# python.org macOS builds ship without a usable CA bundle, so a plain
# create_default_context() fails on every HTTPS call. Find real roots instead
# of ever turning verification off.
_CA_CANDIDATES = (
    "/etc/ssl/cert.pem",                       # macOS
    "/etc/ssl/certs/ca-certificates.crt",      # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",        # RHEL/Fedora
)
_ssl_context: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """A verifying SSL context, using whichever CA bundle this machine has."""
    global _ssl_context
    if _ssl_context is not None:
        return _ssl_context
    try:
        import certifi  # noqa: PLC0415 - optional, only if the user installed it
        _ssl_context = ssl.create_default_context(cafile=certifi.where())
        return _ssl_context
    except ImportError:
        pass
    paths = ssl.get_default_verify_paths()
    if (paths.cafile and os.path.exists(paths.cafile)) or (
        paths.capath and os.path.isdir(paths.capath)
    ):
        _ssl_context = ssl.create_default_context()
        return _ssl_context
    for candidate in _CA_CANDIDATES:
        if os.path.exists(candidate):
            _ssl_context = ssl.create_default_context(cafile=candidate)
            return _ssl_context
    # Last resort: still verifying, just with whatever OpenSSL defaults exist.
    _ssl_context = ssl.create_default_context()
    return _ssl_context


class FetchError(Exception):
    pass


def get_json(url: str, timeout: int = 25, retries: int = 2):
    """GET a URL and parse JSON. Retries transient failures with backoff."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # 404 means the board token is wrong; retrying will not help.
            if exc.code in (404, 410):
                raise FetchError(f"HTTP {exc.code} for {url}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{type(last).__name__}: {last} for {url}")


def post_json(url: str, payload: dict, timeout: int = 25, retries: int = 2):
    """POST JSON and parse the JSON response."""
    body = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # Telegram puts the useful error text in the 4xx body.
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise FetchError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{type(last).__name__}: {last} for {url}")
