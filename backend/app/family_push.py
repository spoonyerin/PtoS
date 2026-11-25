"""가족 보호(발표 시연 한정)의 켜는 조건과 웹 푸시 어댑터.

- 가족 기능은 백엔드 환경 변수 PTOS_FAMILY_DB_PATH가 있을 때만 켠다. 저장소 안 경로는 거부한다.
  ":memory:"는 서버를 끄면 사라지는 임시 저장(자동 테스트·로컬 확인용)이다.
- 웹 푸시는 PTOS_PUSH_MODE=live-webpush(정확히 일치)와 VAPID 공개·비공개 키, 연락처(subject)가 모두 있을 때만 켠다.
  자동 테스트는 가짜 전송기만 쓴다.
- 알림 내용은 고정 문장뿐이다. 이름·위험 단계·위험 요소·원문을 넣지 않는다. 결과는 앱을 열어야 보인다.
- 키·구독 주소·오류 본문을 로그에 남기지 않는다. 로그에는 고정 코드만 남긴다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit

from .family_store import DEFAULT_RETENTION_DAYS, FamilyStore, PushTarget

logger = logging.getLogger("ptos.family")

DB_PATH_ENV = "PTOS_FAMILY_DB_PATH"
RETENTION_ENV = "PTOS_FAMILY_RETENTION_DAYS"
PUSH_MODE_ENV = "PTOS_PUSH_MODE"
PUSH_MODE_LIVE = "live-webpush"
VAPID_PUBLIC_ENV = "PTOS_VAPID_PUBLIC_KEY"
VAPID_PRIVATE_ENV = "PTOS_VAPID_PRIVATE_KEY"
VAPID_SUBJECT_ENV = "PTOS_VAPID_SUBJECT"
ALL_ENV = (DB_PATH_ENV, RETENTION_ENV, PUSH_MODE_ENV, VAPID_PUBLIC_ENV, VAPID_PRIVATE_ENV, VAPID_SUBJECT_ENV)

REPO_ROOT = Path(__file__).resolve().parents[2]
PUSH_TIMEOUT_SECONDS = 5.0

NotificationKind = Literal["request", "reply", "linked"]
MESSAGES: dict[str, tuple[str, str]] = {
    "request": ("PtoS 가족 보호", "가족이 문자 확인을 요청했어요. 눌러서 확인해 주세요."),
    "reply": ("PtoS 가족 보호", "가족 의견이 도착했어요. 눌러서 확인해 주세요."),
    "linked": ("PtoS 가족 보호", "가족 연결이 완료됐어요."),
}

SendResult = Literal["sent", "gone", "failed"]

# 브라우저 푸시 서비스 주소만 받는다. 서버가 사용자가 준 주소로 요청을 보내므로(SSRF 방지)
# 이 목록 밖의 호스트, 443이 아닌 포트, 사용자 정보가 붙은 주소는 거부한다.
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")


def is_push_endpoint(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        return False
    if port not in (None, 443) or not host or "\\" in endpoint:
        return False
    return host in PUSH_HOSTS or any(host.endswith(suffix) and len(host) > len(suffix) for suffix in PUSH_HOST_SUFFIXES)


def _push_session():
    """리디렉션을 따라가지 않고 환경 프록시를 쓰지 않는 요청 세션."""
    import requests

    session = requests.Session()
    session.max_redirects = 0
    session.trust_env = False
    return session


class PushSender(Protocol):
    async def send(self, target: PushTarget, payload: str) -> SendResult: ...


class WebPushSender:
    """pywebpush로 브라우저 푸시 서비스에 암호화된 알림을 보낸다."""

    def __init__(self, private_key: str, subject: str):
        self._private_key = private_key
        self._subject = subject

    def _send_sync(self, target: PushTarget, payload: str) -> SendResult:
        from pywebpush import WebPushException, webpush

        if not is_push_endpoint(target.endpoint):
            return "gone"
        session = _push_session()
        try:
            response = webpush(
                subscription_info={"endpoint": target.endpoint, "keys": {"p256dh": target.p256dh, "auth": target.auth}},
                data=payload,
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._subject},
                ttl=24 * 60 * 60,
                timeout=PUSH_TIMEOUT_SECONDS,
                requests_session=session,
            )
            # 리디렉션(3xx)은 따라가지 않고 실패로 본다.
            status = getattr(response, "status_code", 201)
            return "sent" if 200 <= status < 300 else "failed"
        except WebPushException as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            return "gone" if status in (404, 410) else "failed"
        except Exception:
            return "failed"
        finally:
            session.close()

    async def send(self, target: PushTarget, payload: str) -> SendResult:
        try:
            async with asyncio.timeout(PUSH_TIMEOUT_SECONDS + 1):
                return await asyncio.to_thread(self._send_sync, target, payload)
        except TimeoutError:
            return "failed"


@dataclass
class FamilySetup:
    store: FamilyStore | None
    sender: PushSender | None
    public_key: str | None
    reason: str


def _inside_repo(path: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(REPO_ROOT)
    except OSError:
        return True


def create_family(env: dict[str, str]) -> FamilySetup:
    path = env.get(DB_PATH_ENV, "").strip()
    if not path:
        return FamilySetup(None, None, None, "db_missing")
    if path != ":memory:" and _inside_repo(path):
        return FamilySetup(None, None, None, "db_in_repo")
    try:
        retention = int(env.get(RETENTION_ENV, "") or DEFAULT_RETENTION_DAYS)
        if not 1 <= retention <= 30:
            raise ValueError
    except ValueError:
        return FamilySetup(None, None, None, "invalid_config")
    try:
        store = FamilyStore(path, retention_days=retention)
    except Exception:
        return FamilySetup(None, None, None, "db_unavailable")
    public = env.get(VAPID_PUBLIC_ENV, "").strip()
    private = env.get(VAPID_PRIVATE_ENV, "").strip()
    subject = env.get(VAPID_SUBJECT_ENV, "").strip()
    if env.get(PUSH_MODE_ENV) != PUSH_MODE_LIVE:
        return FamilySetup(store, None, None, "push_off")
    if not (public and private and subject.startswith(("mailto:", "https://"))):
        return FamilySetup(store, None, None, "push_invalid_config")
    return FamilySetup(store, WebPushSender(private, subject), public, "push_live")


class FamilyNotifier:
    def __init__(self, store: FamilyStore, sender: PushSender | None):
        self.store = store
        self.sender = sender

    async def notify(self, device_id: str, kind: NotificationKind, url: str) -> None:
        if self.sender is None:
            return
        title, body = MESSAGES[kind]
        payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
        for target in self.store.push_targets(device_id):
            if not is_push_endpoint(target.endpoint):
                self.store.drop_subscription(target.endpoint)
                continue
            result = await self.sender.send(target, payload)
            if result == "gone":
                self.store.drop_subscription(target.endpoint)
            elif result == "failed":
                logger.info("FAMILY_PUSH result=failed")


def env_snapshot() -> dict[str, str]:
    return {name: os.environ.get(name, "") for name in ALL_ENV}
