"""采集核心：robots 检查、限速、条件请求、重试、健康状态。"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any

from ..common import now_iso


@dataclass
class FetchResult:
    url: str
    status_code: int | None
    headers: dict[str, str]
    body: bytes | None
    fetched_at: str
    error: str | None = None
    error_code: str | None = None
    from_cache: bool = False


class Fetcher:
    def __init__(self, config: dict[str, Any]) -> None:
        self.user_agent = config.get("user_agent", "websearch-lite/0.1")
        self.timeout = float(config.get("request_timeout_s", 20))
        self.max_retries = int(config.get("max_retries", 2))
        self.backoff = float(config.get("retry_backoff_s", 2))
        self._last_request_at = 0.0
        self._robots_cache: dict[str, tuple[bool, urllib.robotparser.RobotFileParser | None]] = {}

    def _rate_limit(self, rps: float) -> None:
        interval = 1.0 / max(0.1, rps)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_at = time.monotonic()

    def robots(self, base_url: str, respect: bool = True) -> tuple[bool, str]:
        """返回 (allowed_to_proceed, reason)。404 robots 视为无禁止规则。"""
        if not respect:
            return True, "robots-check-disabled"
        from urllib.parse import urljoin, urlsplit
        parts = urlsplit(base_url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots_cache:
            allowed, parser = self._robots_cache[origin]
            return allowed, "cache"
        robots_url = urljoin(origin, "/robots.txt")
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            req = urllib.request.Request(robots_url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                content = r.read().decode("utf-8", errors="replace")
            parser.parse(content.splitlines())
            allowed = True
            reason = "robots-present"
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                allowed, reason = True, f"robots-{e.code}-no-rules"
            else:
                allowed, reason = False, f"robots-http-{e.code}"
        except Exception as e:
            allowed, reason = False, f"robots-error:{type(e).__name__}"
        self._robots_cache[origin] = (allowed, parser if allowed else None)
        return allowed, reason

    def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None,
              rps: float = 1.0, respect_robots: bool = True,
              base_url: str | None = None) -> FetchResult:
        allowed, reason = self.robots(base_url or url, respect_robots)
        if not allowed:
            return FetchResult(url, None, {}, None, now_iso(), reason, "ROBOTS_DISALLOWED")

        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        last_error = ""
        for attempt in range(self.max_retries + 1):
            self._rate_limit(rps)
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read()
                    return FetchResult(
                        url=r.geturl(), status_code=r.status,
                        headers={k.lower(): v for k, v in r.headers.items()},
                        body=body, fetched_at=now_iso(),
                    )
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return FetchResult(url, 304, {}, None, now_iso(), None, None, from_cache=True)
                last_error = f"HTTP {e.code}"
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                code = "HTTP_RETRYABLE" if e.code in (429, 500, 502, 503, 504) else "HTTP_PERMANENT"
                return FetchResult(url, e.code, {}, None, now_iso(), last_error, code)
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < self.max_retries:
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                return FetchResult(url, None, {}, None, now_iso(), last_error, "NETWORK_TIMEOUT")
        return FetchResult(url, None, {}, None, now_iso(), last_error, "NETWORK_TIMEOUT")
