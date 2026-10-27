"""연결 경계. 키와 명시적 모드가 모두 있을 때만 실제 HTTP 전송기를 만든다."""

from collections.abc import Mapping
import logging
import os
from typing import Protocol

from .contracts import UrlReputation
from .urls import ValidatedUrl

logger = logging.getLogger(__name__)

API_KEY_ENV = "GOOGLE_SAFE_BROWSING_API_KEY"
MODE_ENV = "PTOS_SAFE_BROWSING_MODE"
# Exact value only (no trimming/case folding): turning on external calls must be deliberate.
LIVE_MODE = "live-noncommercial"
TIMEOUT_ENV = "PTOS_SAFE_BROWSING_TIMEOUT_SECONDS"
# Per-URL deadline including queue wait. Development proposal, not a Google value.
DEFAULT_TIMEOUT = 1.0


class UrlReputationProvider(Protocol):
    async def lookup(self, url: ValidatedUrl) -> UrlReputation: ...


class DisconnectedReputationProvider:
    def __init__(self, reason: str = "key_missing"):
        self.reason = reason

    async def lookup(self, url: ValidatedUrl) -> UrlReputation:
        return UrlReputation(status="not_connected", reason=self.reason)


def configured_reputation_provider(env: Mapping[str, str] | None = None, *, max_timeout: float) -> UrlReputationProvider:
    """A key alone MUST NOT enable traffic: both the key and MODE_ENV == LIVE_MODE are required.

    max_timeout is the whole-analysis deadline; the lookup deadline must stay below it
    so a slow lookup cannot turn into a 504 that hides already found rule evidence.
    Never retain the credential in a provider repr, exception, log or response.
    """
    env = os.environ if env is None else env
    key = env.get(API_KEY_ENV, "").strip()
    if not key:
        return DisconnectedReputationProvider("key_missing")
    if env.get(MODE_ENV, "") != LIVE_MODE:
        return DisconnectedReputationProvider("policy_pending")
    raw_timeout = env.get(TIMEOUT_ENV, "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
    except ValueError:
        timeout = -1.0
    if not 0 < timeout < max_timeout:
        logger.warning("URL reputation stays OFF: %s must be a number between 0 and %s", TIMEOUT_ENV, max_timeout)
        return DisconnectedReputationProvider("invalid_config")
    # Imported here so the default (off) path never loads the HTTP client.
    from .safe_browsing import SafeBrowsingV5Provider
    from .safe_browsing_http import HttpxHashSearchTransport
    logger.warning("URL reputation: live Google Safe Browsing hashes.search lookups are ON (timeout %ss)", timeout)
    return SafeBrowsingV5Provider(HttpxHashSearchTransport(key, timeout=timeout), timeout=timeout)
