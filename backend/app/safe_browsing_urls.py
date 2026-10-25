"""Offline Safe Browsing URL expressions; never resolve/open the input address.

Separate from the stricter user-input validator. See docs/SAFE_BROWSING.md.
Byte-oriented unescaping preserves non-UTF8 paths without replacement characters.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import ipaddress
import re
from urllib.parse import unquote_to_bytes

import idna


class CanonicalizationError(ValueError):
    def __init__(self):
        super().__init__("URL canonicalization unavailable")


def _escape(value: bytes) -> str:
    return "".join(f"%{byte:02X}" if byte <= 32 or byte >= 127 or byte in (35, 37) else chr(byte) for byte in value)


def _ipv4(host: str) -> str | None:
    # Historical IPv4 notation in the Google URL procedure (hex/octal/1–4 parts).
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or not all(re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", p) for p in parts):
        return None
    values = [int(p, 16) if p.lower().startswith("0x") else int(p, 8) if len(p) > 1 and p.startswith("0") else int(p) for p in parts]
    if any(n > 255 for n in values[:-1]) or values[-1] >= 256 ** (5 - len(values)):
        raise CanonicalizationError()
    number = sum(n << (24 - 8 * i) for i, n in enumerate(values[:-1])) + values[-1]
    return str(ipaddress.IPv4Address(number))


@dataclass(frozen=True, repr=False)
class CanonicalUrl:
    host: str
    path: str
    query: str

    def expressions(self) -> tuple[str, ...]:
        hosts = [self.host]
        if not self.host.startswith("[") and _ipv4(self.host) is None:
            parts = self.host.split(".")
            hosts.extend(".".join(parts[-count:]) for count in range(min(5, len(parts) - 1), 1, -1))
        # At most 4 prefixes (root + first 3 directories), full path, path+query.
        paths = ["/"]
        paths.extend(self.path[:match.end()] for match in list(re.finditer("/", self.path))[1:4])
        paths.append(self.path)
        if self.query:
            paths.append(f"{self.path}?{self.query}")
        return tuple(dict.fromkeys(host + path for host in hosts for path in dict.fromkeys(paths)))


def canonicalize(url: str) -> CanonicalUrl:
    try:
        # A fragment introduced by decoding is data, not a fragment delimiter.
        raw = url.strip().replace("\t", "").replace("\r", "").replace("\n", "").split("#", 1)[0].encode("utf-8")
        for _ in range(1024):
            decoded = unquote_to_bytes(raw)
            if decoded == raw:
                break
            raw = decoded
        else:
            raise CanonicalizationError()  # resource guard, never a no-match
        match = re.match(rb"https?://", raw, re.IGNORECASE)
        if not match:
            raise CanonicalizationError()
        address, _, query = raw[match.end():].partition(b"?")
        authority, separator, path = address.partition(b"/")
        if b"@" in authority or b"\\" in authority:
            raise CanonicalizationError()
        if authority.startswith(b"["):
            end = authority.index(b"]")
            suffix = authority[end + 1:]
            if suffix and not re.fullmatch(rb":[0-9]+", suffix):
                raise CanonicalizationError()
            host = "[" + ipaddress.IPv6Address(authority[1:end].decode("ascii")).compressed + "]"
        else:
            name, colon, port = authority.partition(b":")
            if colon and not port.isdigit():
                raise CanonicalizationError()
            name = re.sub(rb"\.+", b".", name).strip(b".")
            if not name:
                raise CanonicalizationError()
            # Internationalized labels use the same UTS #46 mapping as input validation.
            text = name.decode("utf-8").lower()
            host = _ipv4(text) or (idna.encode(text, uts46=True, transitional=False).decode("ascii") if not text.isascii() else _escape(name.lower()))
        raw_path = b"/" + path if separator else b"/"
        segments: list[bytes] = []
        for segment in raw_path.split(b"/"):
            if segment == b"..":
                if segments:
                    segments.pop()
            elif segment not in (b"", b"."):
                segments.append(segment)
        cleaned = b"/" + b"/".join(segments)
        if raw_path.endswith(b"/") and segments:
            cleaned += b"/"
        return CanonicalUrl(host, _escape(cleaned), _escape(query))
    except (ValueError, UnicodeError, idna.IDNAError):
        raise CanonicalizationError() from None


@dataclass(frozen=True, repr=False)
class UrlHashes:
    full_hashes: frozenset[bytes] = field(repr=False)
    prefixes: tuple[bytes, ...] = field(repr=False)


def hash_url(url: str) -> UrlHashes:
    hashes = frozenset(sha256(value.encode("ascii")).digest() for value in canonicalize(url).expressions())
    return UrlHashes(hashes, tuple(sorted({value[:4] for value in hashes})))
