"""Keyless v5 hashes.search adapter. Only a caller-supplied transport can run.

The live HTTP transport lives in safe_browsing_http.py and is never wired by
default. Tests inject fakes.
Cache holds prefixes, returned full hashes and metadata; never URLs or API keys.
"""

import asyncio
import base64
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import time
from typing import Callable, Protocol

from .contracts import UrlReputation
from .safe_browsing_urls import CanonicalizationError, hash_url
from .urls import ValidatedUrl

PROVIDER = "google_safe_browsing_v5"
THREATS = frozenset({"MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"})
SEARCH_ENDPOINT = "https://safebrowsing.googleapis.com/v5/hashes:search"


@dataclass(frozen=True, repr=False)
class SearchResponse:
    status_code: int
    body: dict = field(repr=False)


class HashSearchTransport(Protocol):
    # Repeated REST hashPrefixes values: standard Base64 of exactly 4 bytes WITHOUT
    # padding, as in the official overview example (hashPrefixes=WwuJdQ).
    # No URL, hostname, expression, input text or full hash crosses this boundary.
    async def search(self, hash_prefixes: tuple[str, ...]) -> SearchResponse: ...


# Transport failures carry no message: request data must not leak through them.
class TransportTimeout(Exception):
    pass


class TransportNetworkError(Exception):
    pass


class TransportResponseError(Exception):
    """Unusable 200 response (format, size, JSON). Keeps only the Content-Type for diagnostics."""

    def __init__(self, content_type: str = ""):
        super().__init__()
        self.content_type = content_type[:100]


def encode_prefix(prefix: bytes) -> str:
    return base64.b64encode(prefix).decode("ascii").rstrip("=")


@dataclass(frozen=True, repr=False)
class CacheEntry:
    hashes: dict[bytes, frozenset[str]]
    ignored_hashes: frozenset[bytes]
    expires: float
    checked_at: datetime
    expires_at: datetime


def parse_response(body: dict, prefixes: tuple[bytes, ...]) -> tuple[float, dict[bytes, frozenset[str]], frozenset[bytes]]:
    """Reject malformed protocol data; ignore forward-incompatible threat details."""
    duration = body.get("cacheDuration")
    if not isinstance(duration, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,9})?s", duration):
        raise ValueError("Invalid response")
    ttl = Decimal(duration[:-1])
    if ttl > 315_576_000_000:  # protobuf Duration range, not a chosen cache policy
        raise ValueError("Invalid response")
    records = body.get("fullHashes", [])
    if not isinstance(records, list) or len(records) > 10_000:
        raise ValueError("Invalid response")
    found: dict[bytes, set[str]] = {}
    ignored: set[bytes] = set()
    for record in records:
        digest = base64.b64decode(record["fullHash"], validate=True)
        if len(digest) != 32 or digest[:4] not in prefixes:
            raise ValueError("Invalid response")
        details = record.get("fullHashDetails", [])
        if not isinstance(details, list):
            raise ValueError("Invalid response")
        found.setdefault(digest, set())
        if not details:
            ignored.add(digest)
        for detail in details:
            threat = detail.get("threatType")
            attributes = detail.get("attributes", [])
            # All currently recognized attributes exclude this standalone URL verdict:
            # CANARY: no enforcement. FRAME_ONLY: applies to frames only.
            if threat not in THREATS or not isinstance(attributes, list) or attributes:
                ignored.add(digest)
                continue
            found[digest].add(threat)
    return float(ttl), {digest: frozenset(threats) for digest, threats in found.items()}, frozenset(ignored)


class SafeBrowsingV5Provider:
    def __init__(
        self, transport: HashSearchTransport, *,
        # Local development budgets, NOT Google's quota or PRD risk thresholds.
        per_minute: int = 2, per_day: int = 100, cache_capacity: int = 2048,
        timeout: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if min(per_minute, per_day, cache_capacity) < 1 or timeout <= 0:
            raise ValueError("Invalid local budget")
        self._transport = transport
        self._per_minute, self._per_day = per_minute, per_day
        self._capacity, self._timeout = cache_capacity, timeout
        self._clock, self._utcnow = monotonic, utcnow
        self._cache: dict[bytes, CacheEntry] = {}
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        close = getattr(self._transport, "aclose", None)
        if close is not None:
            await close()

    @staticmethod
    def _verdict(hashes, entries: list[CacheEntry], cache_hit: bool) -> UrlReputation:
        threats = sorted({threat for entry in entries for digest, kinds in entry.hashes.items()
                          if digest in hashes.full_hashes for threat in kinds})
        unsupported = any(entry.ignored_hashes & hashes.full_hashes for entry in entries)
        return UrlReputation(
            status="malicious" if threats else "unknown", provider=PROVIDER,
            reason="full_hash_match" if threats else "unsupported_details" if unsupported else "no_match",
            full_hash_verified=bool(threats), threat_types=threats,
            checked_at=min(entry.checked_at for entry in entries),
            cache_expires_at=min(entry.expires_at for entry in entries), cache_hit=cache_hit,
        )

    async def lookup(self, url: ValidatedUrl) -> UrlReputation:
        def failure(status: str, reason: str) -> UrlReputation:
            return UrlReputation(status=status, reason=reason, provider=PROVIDER)

        try:
            hashes = hash_url(url.normalized_url)
        except CanonicalizationError:
            return failure("unavailable", "normalization_failed")
        # Include lock wait in the per-URL deadline. No retries/background tasks.
        try:
            async with asyncio.timeout(self._timeout):
                async with self._lock:
                    now = self._clock()
                    self._cache = {p: e for p, e in self._cache.items() if e.expires > now}
                    missing = tuple(p for p in hashes.prefixes if p not in self._cache)
                    cache_hit = not missing
                    entries = [self._cache[p] for p in hashes.prefixes if p in self._cache]
                    cached_entries = list(entries)
                    if entries:
                        cached = self._verdict(hashes, entries, True)
                        if cached.full_hash_verified:
                            # A still-valid cached host/path threat remains a warning
                            # even when new, more specific query prefixes are uncached.
                            return cached
                    if missing:
                        # Never evict live mandatory entries to make room/refetch them.
                        if len(self._cache) + len(missing) > self._capacity:
                            return failure("unavailable", "cache_capacity")
                        while self._calls and self._calls[0] <= now - 86400:
                            self._calls.popleft()
                        if len(self._calls) >= self._per_day or sum(t > now - 60 for t in self._calls) >= self._per_minute:
                            return failure("rate_limited", "local_limit")
                        # Count attempted calls, including HTTP/network failures.
                        self._calls.append(now)
                        response = await self._transport.search(tuple(encode_prefix(p) for p in missing))
                        if response.status_code in (401, 403):
                            return failure("auth_error", "authentication_failed")
                        if response.status_code == 429:
                            return failure("rate_limited", "provider_rate_limit")
                        if 500 <= response.status_code <= 599:
                            return failure("unavailable", "server_error")
                        if response.status_code != 200:
                            return failure("unavailable", "http_error")
                        try:
                            ttl, full_hashes, ignored = parse_response(response.body, missing)
                            checked_at = self._utcnow()
                            expires_at = checked_at + timedelta(seconds=ttl)
                            expires = self._clock() + ttl
                            new_entries = {p: CacheEntry(
                                {h: threats for h, threats in full_hashes.items() if h[:4] == p},
                                frozenset(h for h in ignored if h[:4] == p), expires, checked_at, expires_at,
                            ) for p in missing}
                        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
                            return failure("unavailable", "invalid_response")
                        self._cache.update(new_entries)
                        entries.extend(new_entries.values())
                        if any(entry.expires <= self._clock() for entry in cached_entries):
                            # Don't claim a complete no-match using negative entries
                            # that expired while waiting for other prefixes. A fresh
                            # positive alone remains sufficient to warn.
                            fresh_verdict = self._verdict(hashes, list(new_entries.values()), False)
                            if fresh_verdict.full_hash_verified:
                                return fresh_verdict
                            return failure("unavailable", "cache_expired_during_lookup")
                    # One complete SHA-256 comparison, not prefix membership, is required.
                    return self._verdict(hashes, entries, cache_hit)
        except (TimeoutError, TransportTimeout):
            return failure("timeout", "request_timeout")
        except TransportNetworkError:
            return failure("unavailable", "network_error")
        except TransportResponseError:
            return failure("unavailable", "invalid_response")
        except Exception:
            # Never propagate/log exceptions that can contain request data or credentials.
            return failure("unavailable", "transport_error")
