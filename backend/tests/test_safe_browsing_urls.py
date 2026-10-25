"""Offline URL procedure vectors; never send a sample URL to a server."""

import hashlib

import pytest

from app.safe_browsing_urls import CanonicalizationError, canonicalize, hash_url


@pytest.mark.parametrize("url,host,path,query", [
    ("http://host/%25%32%35", "host", "/%25", ""),
    ("http://host/%25%32%35%25%32%35", "host", "/%25%25", ""),
    ("http://host/%2525252525252525", "host", "/%25", ""),
    ("http://host/asdf%25%32%35asd", "host", "/asdf%25asd", ""),
    ("http://host/%%%25%32%35asd%%", "host", "/%25%25%25asd%25%25", ""),
    ("http://www.evil.com/blah#frag", "www.evil.com", "/blah", ""),
    ("HTTP://www.GOOgle.com:80", "www.google.com", "/", ""),
    ("  http://www.google.com.../  ", "www.google.com", "/", ""),
    ("http://..a...b..c./a//b///c/", "a.b.c", "/a/b/c/", ""),
    ("http://a.com/\ta\rb\nc", "a.com", "/abc", ""),
    ("http://a.com/a/.././bar/./../foo.html", "a.com", "/foo.html", ""),
    ("http://a.com/%2e%2e/a/%2E/b/%2e%2e/c", "a.com", "/a/c", ""),
    ("http://a.com/a;b?x=1&y=2#discard", "a.com", "/a;b", "x=1&y=2"),
    ("http://a.com/%2523part?x=%2525%23", "a.com", "/%23part", "x=%25%23"),
    ("http://a.com/%3Fkey=value", "a.com", "/", "key=value"),
    ("https://a.com/%ff%00%20", "a.com", "/%FF%00%20", ""),
    ("http://3279880203/blah", "195.127.0.11", "/blah", ""),
    ("http://0xC3.0177.0.0x0b/", "195.127.0.11", "/", ""),
    ("http://0303.0177.013/", "195.127.0.11", "/", ""),
    ("http://192.168.257/", "192.168.1.1", "/", ""),
    ("http://%31%36%38%2e188.99.26/", "168.188.99.26", "/", ""),
    ("https://[2001:0DB8:0000:0:0:0:0:1]:443/a", "[2001:db8::1]", "/a", ""),
    ("https://예시.한국/공지?내용=확인", "xn--vv4b11d.xn--3e0b707e", "/%EA%B3%B5%EC%A7%80", "%EB%82%B4%EC%9A%A9=%ED%99%95%EC%9D%B8"),
    ("https://www.ümlat.com/", "www.xn--mlat-zra.com", "/", ""),
])
def test_canonicalization(url, host, path, query):
    result = canonicalize(url)
    assert (result.host, result.path, result.query) == (host, path, query)


def test_host_and_path_combinations_are_bounded_and_keep_query_order():
    result = canonicalize("https://a.b.c.d.e.f.g/1/2/3/4/5?q=2&q=1#frag")
    assert result.expressions() == tuple(
        host + path for host in ["a.b.c.d.e.f.g", "c.d.e.f.g", "d.e.f.g", "e.f.g", "f.g"]
        for path in ["/", "/1/", "/1/2/", "/1/2/3/", "/1/2/3/4/5", "/1/2/3/4/5?q=2&q=1"]
    )
    assert len(result.expressions()) == 30


@pytest.mark.parametrize("url,expected", [
    ("http://a.b.c/1/2.html?param=1/2", tuple(h + p for h in ("a.b.c", "b.c") for p in ("/", "/1/", "/1/2.html", "/1/2.html?param=1/2"))),
    ("http://192.168.0.1/a", ("192.168.0.1/", "192.168.0.1/a")),
    ("https://[::1]/a", ("[::1]/", "[::1]/a")),
    ("http://localhost/?", ("localhost/",)),
])
def test_expression_variants(url, expected):
    assert canonicalize(url).expressions() == expected


def test_sha256_is_calculated_over_expression_not_url_scheme_or_fragment():
    expected = hashlib.sha256(b"example.invalid/path?x=1").digest()
    result = hash_url("https://EXAMPLE.invalid:443/path?x=1#secret")
    assert expected in result.full_hashes and expected[:4] in result.prefixes
    assert all(len(value) == 4 for value in result.prefixes)
    assert hash_url("http://example.invalid/path?x=1") == result
    assert hash_url("http://example.invalid/path?x=2") != result
    assert "secret" not in repr(result)


@pytest.mark.parametrize("url", ["ftp://a.com/", "http:///a", "http://user:secret@a.com/", "http://[bad]/", "http://999999999999999999999/", "http://1.2.999999/", "http://a.com:port/", "http://a\\b/"])
def test_unsupported_input_never_becomes_no_match(url):
    with pytest.raises(CanonicalizationError, match="URL canonicalization unavailable"):
        canonicalize(url)
