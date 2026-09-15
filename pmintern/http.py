"""Small JSON-over-HTTP helper built on urllib (no third-party deps)."""
from __future__ import annotations

import gzip
import contextlib
import json
import threading
import re
import random
import os
import pathlib
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


# Hosts that serve many of our boards from shared infrastructure. Workday runs
# ~200 of them; unthrottled, a cloud runner's shared IP drew HTTP 429 on 59
# boards in one scan. A per-host gate keeps concurrency polite.
_HOST_LIMITS = {"myworkdayjobs.com": 6}
_gates: dict[str, threading.BoundedSemaphore] = {}
_gates_lock = threading.Lock()

RETRYABLE = (429, 500, 502, 503, 504)
MAX_BACKOFF = 30


def _gate(url: str):
    host = urllib.parse.urlparse(url).netloc.lower()
    for suffix, limit in _HOST_LIMITS.items():
        if host.endswith(suffix):
            with _gates_lock:
                return _gates.setdefault(suffix, threading.BoundedSemaphore(limit))
    return contextlib.nullcontext()


def _backoff(exc: urllib.error.HTTPError | None, attempt: int) -> float:
    """Honour Retry-After when the server sends one; otherwise back off exponentially."""
    if exc is not None:
        header = exc.headers.get("Retry-After") if exc.headers else None
        if header and header.strip().isdigit():
            return min(float(header), MAX_BACKOFF)
    return min(2.0 * (2 ** attempt), MAX_BACKOFF) + random.uniform(0, 1)


def _detail(exc: urllib.error.HTTPError) -> str:
    """First line of an error body, with HTML stripped, so logs stay readable."""
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    text = re.sub(r"<[^>]+>", " ", body)
    return " ".join(text.split())[:160]


def _request_json(req: urllib.request.Request, url: str, timeout: int, retries: int,
                  fail_fast: tuple = (404, 410)):
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _gate(url):
                with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                    return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in fail_fast or exc.code not in RETRYABLE:
                raise FetchError(f"HTTP {exc.code}: {_detail(exc)}") from exc
            last = exc
            if attempt < retries:
                time.sleep(_backoff(exc, attempt))
            continue
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(_backoff(None, attempt))
    code = f"HTTP {last.code}" if isinstance(last, urllib.error.HTTPError) else type(last).__name__
    raise FetchError(f"{code} after {retries + 1} attempts")


def get_json(url: str, timeout: int = 25, retries: int = 4):
    """GET a URL and parse JSON. Retries throttling and transient failures."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"})
    return _request_json(req, url, timeout, retries)


def post_json(url: str, payload: dict, timeout: int = 25, retries: int = 4):
    """POST JSON and parse the JSON response. Retries throttling (429) with backoff."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    return _request_json(req, url, timeout, retries)


def get_text(url: str, timeout: int = 90, retries: int = 2) -> str:
    """Plain GET returning decoded text, with gzip handling."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise FetchError(f"HTTP {exc.code} for {url}") from exc
            last = exc
        except (urllib.error.URLError, OSError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{type(last).__name__}: {last} for {url}")


def get_text_cached(url: str, cache_path, timeout: int = 60, retries: int = 2) -> str:
    """GET with ETag revalidation, backed by an on-disk cache.

    Large feeds re-send megabytes on every poll otherwise. A 304 costs a few
    hundred bytes and lets us reuse the copy already on disk.
    """
    cache_path = pathlib.Path(cache_path)
    meta_path = cache_path.with_suffix(cache_path.suffix + ".etag")
    etag = ""
    if cache_path.exists() and meta_path.exists():
        etag = meta_path.read_text(encoding="utf-8").strip()

    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if etag:
        headers["If-None-Match"] = etag

    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                new_etag = resp.headers.get("ETag", "")
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(raw)
                if new_etag:
                    meta_path.write_text(new_etag, encoding="utf-8")
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and cache_path.exists():
                return cache_path.read_text(encoding="utf-8", errors="replace")
            last = exc
        except (urllib.error.URLError, OSError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))

    # A stale copy beats losing a whole source to one bad fetch.
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")
    raise FetchError(f"{type(last).__name__}: {last} for {url}")


def get_json_cached(url: str, cache_path, timeout: int = 45, retries: int = 2):
    """ETag-revalidated GET that parses the cached body as JSON."""
    return json.loads(get_text_cached(url, cache_path, timeout=timeout, retries=retries))
