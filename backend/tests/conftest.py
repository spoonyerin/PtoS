"""자동 테스트 전체에서 실제 외부 호출을 막고, 시도가 있으면 해당 테스트를 실패시킨다.

- 셸에 키나 PTOS_SAFE_BROWSING_MODE가 남아 있어도 테스트에는 전달하지 않는다 (모듈 import 전에 제거).
- 루프백(127.0.0.1, ::1, localhost) 외의 주소 해석·연결 시도는 기록하고 막는다.
  Windows asyncio의 내부 socketpair가 루프백을 쓰므로 루프백은 허용한다.
"""

import ipaddress
import os
import socket

import pytest

from app.url_reputation import API_KEY_ENV, MODE_ENV, TIMEOUT_ENV

for _name in (API_KEY_ENV, MODE_ENV, TIMEOUT_ENV):
    os.environ.pop(_name, None)

EXTERNAL_ATTEMPTS: list[str] = []


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _block(host) -> None:
    EXTERNAL_ATTEMPTS.append(host.decode("ascii", "replace") if isinstance(host, bytes) else str(host))
    raise ConnectionRefusedError("External network is blocked in automated tests")


_getaddrinfo = socket.getaddrinfo
_create_connection = socket.create_connection
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _is_loopback(host):
        _block(host)
    return _getaddrinfo(host, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    if not _is_loopback(address[0]):
        _block(address[0])
    return _create_connection(address, *args, **kwargs)


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(address[0]):
        _block(address[0])
    return _connect(self, address)


def _guarded_connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(address[0]):
        _block(address[0])
    return _connect_ex(self, address)


socket.getaddrinfo = _guarded_getaddrinfo
socket.create_connection = _guarded_create_connection
socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    for name in (API_KEY_ENV, MODE_ENV, TIMEOUT_ENV):
        monkeypatch.delenv(name, raising=False)
    EXTERNAL_ATTEMPTS.clear()
    yield EXTERNAL_ATTEMPTS
    attempts = list(EXTERNAL_ATTEMPTS)
    EXTERNAL_ATTEMPTS.clear()
    # The provider turns network errors into results, so the attempt itself must fail the test.
    assert not attempts, f"External network attempted in a test: {attempts}"
