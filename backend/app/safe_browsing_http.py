"""Live hashes.search HTTP transport. Built only when explicitly enabled (url_reputation.py).

Only unpadded Base64 4-byte prefixes and the API key leave the process. The key
goes in the X-Goog-Api-Key header, never the URL, so it stays out of URLs,
exception messages and logs. No redirects, no proxy/.netrc from the environment.
"""

import json
import logging

import httpx

from .safe_browsing import SEARCH_ENDPOINT, SearchResponse, TransportNetworkError, TransportResponseError, TransportTimeout

# Development proposal to bound memory, NOT a Google limit.
MAX_RESPONSE_BYTES = 1 << 20

# httpx logs request URLs (with prefixes) at INFO. Keep them out of logs.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class HttpxHashSearchTransport:
    def __init__(self, api_key: str, *, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key.strip():
            raise ValueError("API key required")
        if timeout <= 0:
            raise ValueError("Invalid timeout")
        self._key, self._timeout, self._transport = api_key.strip(), timeout, transport
        self._client: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        return "HttpxHashSearchTransport()"

    def _get_client(self) -> httpx.AsyncClient:
        # Created on first use inside the running event loop; aclose() allows a fresh one later.
        if self._client is None:
            self._client = httpx.AsyncClient(
                # alt=json is the documented default for REST; the reference overview
                # also mentions protobuf bodies, so the Content-Type is checked below.
                headers={"X-Goog-Api-Key": self._key, "Accept": "application/json"},
                timeout=self._timeout, follow_redirects=False, trust_env=False, transport=self._transport,
            )
        return self._client

    async def search(self, hash_prefixes: tuple[str, ...]) -> SearchResponse:
        params = [*(("hashPrefixes", prefix) for prefix in hash_prefixes), ("alt", "json")]
        try:
            async with self._get_client().stream("GET", SEARCH_ENDPOINT, params=params) as response:
                if response.status_code != 200:
                    # Error bodies are not read or returned: they may echo request data.
                    return SearchResponse(response.status_code, {})
                content_type = response.headers.get("content-type", "")
                if content_type.split(";")[0].strip().lower() != "application/json":
                    raise TransportResponseError(content_type)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise TransportResponseError(content_type)
                    chunks.append(chunk)
        except httpx.TimeoutException:
            raise TransportTimeout() from None
        except httpx.TransportError:
            raise TransportNetworkError() from None
        try:
            body = json.loads(b"".join(chunks))
        except ValueError:
            raise TransportResponseError(content_type) from None
        if not isinstance(body, dict):
            raise TransportResponseError(content_type)
        return SearchResponse(200, body)

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()
