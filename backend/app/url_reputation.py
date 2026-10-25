"""연결 경계만 제공한다. 기본 어댑터에는 HTTP/DNS 클라이언트가 없다."""

import os
from typing import Protocol

from .contracts import UrlReputation
from .urls import ValidatedUrl


class UrlReputationProvider(Protocol):
    async def lookup(self, url: ValidatedUrl) -> UrlReputation: ...


class DisconnectedReputationProvider:
    def __init__(self, reason: str = "key_missing"):
        self.reason = reason

    async def lookup(self, url: ValidatedUrl) -> UrlReputation:
        return UrlReputation(status="not_connected", reason=self.reason)


def configured_reputation_provider() -> UrlReputationProvider:
    """Deliberate live-connection hold: a key alone MUST NOT enable traffic.

    No HTTP transport is shipped/wired. Revisit only after the user verifies
    free/no-billing terms, attribution and quota, then authorizes real calls.
    Never retain the credential in a provider, repr, exception or response.
    """
    return DisconnectedReputationProvider(
        "policy_pending" if os.environ.get("GOOGLE_SAFE_BROWSING_API_KEY", "").strip() else "key_missing"
    )
