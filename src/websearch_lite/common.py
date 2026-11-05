"""P0 公共工具：时间、ID、URL 规范化、哈希、JSON。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACK_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "spm", "ref", "referrer", "from", "src", "share_token",
}
AMP_SUFFIXES = ("/amp", "/amp.html")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    for suffix in AMP_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in TRACK_PARAMS]
    netloc = host + (f":{parts.port}" if parts.port and parts.port not in (80, 443) else "")
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(query), ""))


def simhash(text: str, bits: int = 64) -> int:
    tokens = re.findall(r"\w+", text.lower())
    vector = [0] * bits
    for token in tokens:
        h = int(hashlib.blake2b(token.encode(), digest_size=8).hexdigest(), 16)
        for i in range(bits):
            vector[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, value in enumerate(vector):
        if value > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default
