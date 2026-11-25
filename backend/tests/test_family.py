"""가족 보호(발표 시연 한정) API 테스트. 실제 푸시 서비스는 호출하지 않고 가짜 전송기만 쓴다."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.analyzers import RuleBasedAnalyzer
from app.family_push import (
    DB_PATH_ENV,
    PUSH_MODE_ENV,
    PUSH_MODE_LIVE,
    VAPID_PRIVATE_ENV,
    VAPID_PUBLIC_ENV,
    VAPID_SUBJECT_ENV,
    FamilySetup,
    WebPushSender,
    create_family,
)
from app.family_store import FamilyStore
from app.main import create_app

PRIVATE_TEXT = "PRIVATE 은행입니다 010-1234-5678 https://private.invalid/?secret=1"


class FakeSender:
    def __init__(self, result="sent"):
        self.sent: list[tuple[str, dict]] = []
        self.result = result

    async def send(self, target, payload):
        self.sent.append((target.endpoint, json.loads(payload)))
        return self.result


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 25, 1, 0, tzinfo=UTC)

    def __call__(self):
        return self.value


@pytest.fixture
def family(tmp_path):
    clock = Clock()
    sender = FakeSender()
    store = FamilyStore(str(tmp_path / "family.db"), now=clock)
    setup = FamilySetup(store, sender, "PUBLIC-KEY", "push_live")
    app = create_app(analyzer_factory=RuleBasedAnalyzer, family_setup=lambda: setup)
    return TestClient(app), store, sender, clock, tmp_path / "family.db"


def register(client) -> dict:
    response = client.post("/api/v1/family/devices")
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['device_token']}"}


def connect(client):
    """고령자(elder)가 가입하고 초대를 만들고, 보호자(guardian)가 수락한다."""
    elder, guardian = register(client), register(client)
    assert client.put("/api/v1/family/premium", json={"active": True}, headers=elder).json()["premium"] is True
    invite = client.post("/api/v1/family/invites", json={"name": "우리 딸♥", "relation": "child"}, headers=elder)
    assert invite.status_code == 201
    token = invite.json()["invite_token"]
    accepted = client.post("/api/v1/family/invites/accept", json={"token": token, "name": "엄마"}, headers=guardian)
    assert accepted.status_code == 200
    link_id = invite.json()["link_id"]
    return elder, guardian, link_id


def subscribe(client, headers, endpoint):
    response = client.put("/api/v1/family/push", headers=headers,
                          json={"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}})
    assert response.status_code == 200


def test_family_is_off_without_db_path():
    client = TestClient(create_app(analyzer_factory=RuleBasedAnalyzer))
    assert client.get("/api/v1/health/ready").json()["family"] == "off"
    response = client.post("/api/v1/family/devices")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FAMILY_OFF"


def test_create_family_conditions(tmp_path):
    assert create_family({}).reason == "db_missing"
    # 저장소 안 경로는 커밋될 수 있어 거부한다.
    assert create_family({DB_PATH_ENV: "family.db"}).reason == "db_in_repo"
    assert create_family({DB_PATH_ENV: str(tmp_path / "f.db"), "PTOS_FAMILY_RETENTION_DAYS": "0"}).reason == "invalid_config"
    off = create_family({DB_PATH_ENV: str(tmp_path / "f.db")})
    assert off.store is not None and off.sender is None and off.reason == "push_off"
    base = {DB_PATH_ENV: ":memory:", PUSH_MODE_ENV: PUSH_MODE_LIVE, VAPID_PUBLIC_ENV: "pub", VAPID_PRIVATE_ENV: "priv"}
    assert create_family(base).reason == "push_invalid_config"
    # 모드 값은 정확히 일치해야 한다.
    assert create_family({**base, VAPID_SUBJECT_ENV: "mailto:team@example.invalid", PUSH_MODE_ENV: "live"}).reason == "push_off"
    live = create_family({**base, VAPID_SUBJECT_ENV: "mailto:team@example.invalid"})
    assert isinstance(live.sender, WebPushSender) and live.public_key == "pub"


def test_ready_reports_family_and_push(family):
    client, *_ = family
    body = client.get("/api/v1/health/ready").json()
    assert body["family"] == "live" and body["push"] == "live"


def test_device_token_is_required_and_only_hash_is_stored(family):
    client, store, _, _, path = family
    assert client.get("/api/v1/family/me").status_code == 401
    assert client.get("/api/v1/family/me", headers={"Authorization": "Bearer wrong"}).json()["error"]["code"] == "DEVICE_REQUIRED"
    headers = register(client)
    me = client.get("/api/v1/family/me", headers=headers).json()
    assert me["premium"] is False and me["links"] == []
    token = headers["Authorization"].split()[1]
    rows = sqlite3.connect(path).execute("SELECT token_hash FROM devices").fetchall()
    assert all(token not in row[0] for row in rows)


def test_premium_is_required_for_invites(family):
    client, *_ = family
    headers = register(client)
    response = client.post("/api/v1/family/invites", json={"name": "딸", "relation": "child"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PREMIUM_REQUIRED"


def test_invite_flow_links_both_sides_and_notifies(family):
    client, _, sender, _, _ = family
    elder = register(client)
    subscribe(client, elder, "https://fcm.googleapis.com/fcm/send/test-elder")
    client.put("/api/v1/family/premium", json={"active": True}, headers=elder)
    invite = client.post("/api/v1/family/invites", json={"name": "우리 딸♥", "relation": "child"}, headers=elder).json()
    pending = client.get("/api/v1/family/me", headers=elder).json()["links"]
    assert pending[0]["status"] == "pending" and pending[0]["name"] == "우리 딸♥"
    guardian = register(client)
    preview = client.post("/api/v1/family/invites/preview", json={"token": invite["invite_token"]}, headers=guardian).json()
    assert preview["guardian_name"] == "우리 딸♥" and preview["relation"] == "child"
    client.post("/api/v1/family/invites/accept", json={"token": invite["invite_token"], "name": "엄마"}, headers=guardian)
    elder_links = client.get("/api/v1/family/me", headers=elder).json()["links"]
    guardian_links = client.get("/api/v1/family/me", headers=guardian).json()["links"]
    assert elder_links[0] | {"invite_expires_at": None} == {
        "id": invite["link_id"], "role": "guardian", "name": "우리 딸♥", "relation": "child", "status": "connected",
        "invite_expires_at": None}
    assert guardian_links[0]["role"] == "protected" and guardian_links[0]["name"] == "엄마"
    assert sender.sent == [("https://fcm.googleapis.com/fcm/send/test-elder",
                            {"title": "PtoS 가족 보호", "body": "가족 연결이 완료됐어요.", "url": "/#family"})]


def test_invite_is_single_use_and_expires(family):
    client, _, _, clock, _ = family
    elder = register(client)
    client.put("/api/v1/family/premium", json={"active": True}, headers=elder)
    token = client.post("/api/v1/family/invites", json={"name": "딸", "relation": "child"}, headers=elder).json()["invite_token"]
    self_accept = client.post("/api/v1/family/invites/accept", json={"token": token, "name": "엄마"}, headers=elder)
    assert self_accept.json()["error"]["code"] == "INVITE_SELF"
    first, second = register(client), register(client)
    assert client.post("/api/v1/family/invites/accept", json={"token": token, "name": "엄마"}, headers=first).status_code == 200
    used = client.post("/api/v1/family/invites/accept", json={"token": token, "name": "엄마"}, headers=second)
    assert used.json()["error"]["code"] in ("INVITE_USED", "INVITE_NOT_FOUND")
    late = client.post("/api/v1/family/invites", json={"name": "아들", "relation": "child"}, headers=elder).json()["invite_token"]
    clock.value += timedelta(hours=25)
    expired = client.post("/api/v1/family/invites/accept", json={"token": late, "name": "엄마"}, headers=second)
    assert expired.json()["error"]["code"] in ("INVITE_EXPIRED", "INVITE_NOT_FOUND")
    assert expired.status_code in (404, 410)


def test_names_are_validated(family):
    client, *_ = family
    elder = register(client)
    client.put("/api/v1/family/premium", json={"active": True}, headers=elder)
    for name in (" ", "a" * 21, "딸\u0000"):
        response = client.post("/api/v1/family/invites", json={"name": name, "relation": "child"}, headers=elder)
        assert response.status_code == 422
    assert client.post("/api/v1/family/invites", json={"name": "딸", "relation": "friend"}, headers=elder).status_code == 422


def test_share_request_reply_flow_and_status(family):
    client, _, sender, _, _ = family
    elder, guardian, link_id = connect(client)
    subscribe(client, guardian, "https://fcm.googleapis.com/fcm/send/test-guardian")
    subscribe(client, elder, "https://fcm.googleapis.com/fcm/send/test-elder")
    sender.sent.clear()
    created = client.post("/api/v1/family/requests", headers=elder, json={
        "link_ids": [link_id], "risk_level": "dangerous", "factor_codes": ["LINK_CLICK", "IMPERSONATION", "LINK_CLICK"]})
    assert created.status_code == 201
    request_id = created.json()["request_ids"][0]
    assert sender.sent == [("https://fcm.googleapis.com/fcm/send/test-guardian", {
        "title": "PtoS 가족 보호", "body": "가족이 문자 확인을 요청했어요. 눌러서 확인해 주세요.",
        "url": f"/#family/request/{request_id}"})]
    sent = client.get(f"/api/v1/family/requests/{request_id}", headers=elder).json()
    assert sent["box"] == "sent" and sent["name"] == "우리 딸♥" and sent["viewed_at"] is None
    assert sent["factor_codes"] == ["LINK_CLICK", "IMPERSONATION"]
    assert client.get("/api/v1/family/me", headers=guardian).json()["waiting_requests"] == 1
    received = client.get(f"/api/v1/family/requests/{request_id}", headers=guardian).json()
    assert received["box"] == "received" and received["name"] == "엄마"
    assert client.get(f"/api/v1/family/requests/{request_id}", headers=elder).json()["viewed_at"] is not None
    sender.sent.clear()
    replied = client.post(f"/api/v1/family/requests/{request_id}/reply", headers=guardian,
                          json={"choice": "custom", "text": "링크 누르지 말고 전화해요"})
    assert replied.status_code == 200
    assert replied.json()["reply"]["text"] == "링크 누르지 말고 전화해요"
    assert sender.sent[0][1]["body"] == "가족 의견이 도착했어요. 눌러서 확인해 주세요."
    assert client.post(f"/api/v1/family/requests/{request_id}/reply", headers=guardian,
                       json={"choice": "looks_fine"}).json()["error"]["code"] == "ALREADY_REPLIED"
    assert client.get("/api/v1/family/me", headers=elder).json()["new_replies"] == 1
    client.get(f"/api/v1/family/requests/{request_id}", headers=elder)
    assert client.get("/api/v1/family/me", headers=elder).json()["new_replies"] == 0
    assert [item["id"] for item in client.get("/api/v1/family/requests?box=sent", headers=elder).json()["items"]] == [request_id]
    assert [item["id"] for item in client.get("/api/v1/family/requests?box=received", headers=guardian).json()["items"]] == [request_id]
    assert client.get("/api/v1/family/requests?box=received", headers=elder).json()["items"] == []


def test_only_guardian_can_reply_and_others_cannot_read(family):
    client, *_ = family
    elder, guardian, link_id = connect(client)
    stranger = register(client)
    request_id = client.post("/api/v1/family/requests", headers=elder, json={
        "link_ids": [link_id], "risk_level": "suspicious", "factor_codes": []}).json()["request_ids"][0]
    assert client.get(f"/api/v1/family/requests/{request_id}", headers=stranger).status_code == 404
    assert client.post(f"/api/v1/family/requests/{request_id}/reply", headers=elder,
                       json={"choice": "looks_fine"}).status_code == 404
    assert client.post(f"/api/v1/family/requests/{request_id}/reply", headers=guardian,
                       json={"choice": "custom", "text": " "}).status_code == 422
    # 남의 연결로는 보낼 수 없다.
    client.put("/api/v1/family/premium", json={"active": True}, headers=stranger)
    assert client.post("/api/v1/family/requests", headers=stranger, json={
        "link_ids": [link_id], "risk_level": "dangerous", "factor_codes": []}).status_code == 404


def test_share_request_rejects_source_text_fields(family):
    client, *_ = family
    elder, _, link_id = connect(client)
    response = client.post("/api/v1/family/requests", headers=elder, json={
        "link_ids": [link_id], "risk_level": "dangerous", "factor_codes": [], "content": PRIVATE_TEXT})
    assert response.status_code == 422
    assert "PRIVATE" not in response.text


def test_database_never_contains_source_text(family):
    client, _, _, _, path = family
    elder, guardian, link_id = connect(client)
    analysis = client.post("/api/v1/analyses", json={"input_type": "text", "content": PRIVATE_TEXT}).json()
    codes = list(dict.fromkeys(item["factor_code"] for item in analysis["evidence"]))
    request_id = client.post("/api/v1/family/requests", headers=elder, json={
        "link_ids": [link_id], "risk_level": analysis["risk_level"], "factor_codes": codes}).json()["request_ids"][0]
    client.post(f"/api/v1/family/requests/{request_id}/reply", headers=guardian, json={"choice": "looks_dangerous"})
    dump = "\n".join(sqlite3.connect(path).iterdump())
    for secret in ("PRIVATE", "010-1234-5678", "private.invalid", "secret=1"):
        assert secret not in dump


def test_requests_expire_after_retention(family):
    client, _, _, clock, _ = family
    elder, guardian, link_id = connect(client)
    client.post("/api/v1/family/requests", headers=elder, json={"link_ids": [link_id], "risk_level": "dangerous", "factor_codes": []})
    clock.value += timedelta(days=7, seconds=1)
    assert client.get("/api/v1/family/requests?box=sent", headers=elder).json()["items"] == []
    assert client.get("/api/v1/family/me", headers=guardian).json()["waiting_requests"] == 0


def test_auto_alert_requires_matching_consent(family):
    client, _, sender, _, _ = family
    elder, guardian, link_id = connect(client)
    body = {"link_ids": [link_id], "risk_level": "dangerous", "factor_codes": ["MONEY_REQUEST"], "auto": True}
    assert client.post("/api/v1/family/requests", headers=elder, json=body).json()["error"]["code"] == "AUTO_ALERT_OFF"
    me = client.put("/api/v1/family/auto-alert", headers=elder, json={"link_id": link_id}).json()
    assert me["auto_alert"] == {"enabled": True, "link_id": link_id}
    created = client.post("/api/v1/family/requests", headers=elder, json=body)
    assert created.status_code == 201
    item = client.get(f"/api/v1/family/requests/{created.json()['request_ids'][0]}", headers=guardian).json()
    assert item["auto"] is True
    # 연결을 끊으면 자동 알림도 꺼진다.
    me = client.delete(f"/api/v1/family/links/{link_id}", headers=elder).json()
    assert me["auto_alert"]["enabled"] is False and me["links"] == []
    # 가입을 끄면 자동 알림을 켤 수 없다.
    client.put("/api/v1/family/premium", json={"active": False}, headers=elder)
    assert client.put("/api/v1/family/auto-alert", headers=elder, json={"link_id": link_id}).status_code in (403, 404)


def test_gone_push_subscription_is_removed(family):
    client, store, sender, _, _ = family
    elder, guardian, link_id = connect(client)
    subscribe(client, guardian, "https://fcm.googleapis.com/fcm/send/test-old")
    sender.result = "gone"
    client.post("/api/v1/family/requests", headers=elder, json={"link_ids": [link_id], "risk_level": "dangerous", "factor_codes": []})
    assert client.get("/api/v1/family/me", headers=guardian).json()["push_subscribed"] is False


def test_push_subscription_requires_push_on(tmp_path):
    store = FamilyStore(":memory:")
    client = TestClient(create_app(analyzer_factory=RuleBasedAnalyzer,
                                   family_setup=lambda: FamilySetup(store, None, None, "push_off")))
    headers = register(client)
    assert client.get("/api/v1/family/push/key").json() == {"public_key": None}
    response = client.put("/api/v1/family/push", headers=headers,
                          json={"endpoint": "https://fcm.googleapis.com/fcm/send/test-x", "keys": {"p256dh": "p", "auth": "a"}})
    assert response.json()["error"]["code"] == "PUSH_OFF"
    assert client.get("/api/v1/health/ready").json()["push"] == "off"


def test_device_can_be_deleted(family):
    client, *_ = family
    elder, guardian, link_id = connect(client)
    assert client.delete("/api/v1/family/devices/me", headers=elder).status_code == 204
    assert client.get("/api/v1/family/me", headers=elder).status_code == 401
    assert client.get("/api/v1/family/me", headers=guardian).json()["links"] == []


@pytest.mark.parametrize("endpoint", [
    "https://127.0.0.1/push",
    "https://169.254.169.254/opc/v1/instance/",
    "https://localhost:8000/api/v1/family/me",
    "https://fcm.googleapis.com.evil.invalid/x",
    "https://evilfcm.googleapis.com/x",
    "https://user@fcm.googleapis.com/x",
    "https://fcm.googleapis.com:8443/x",
    "https://push.apple.com/x",
    "https://example.invalid/x",
])
def test_push_subscription_rejects_non_push_hosts(family, endpoint):
    client, store, *_ = family
    headers = register(client)
    response = client.put("/api/v1/family/push", headers=headers,
                          json={"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PUSH"
    assert store.push_targets(store.device_id(headers["Authorization"].split(" ", 1)[1])) == []


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/abc",
    "https://api.push.apple.com/abc",
    "https://wns2-par02p.notify.windows.com/w/?token=abc",
])
def test_push_subscription_accepts_browser_push_hosts(family, endpoint):
    client, *_ = family
    subscribe(client, register(client), endpoint)


def test_stored_non_push_endpoint_is_never_called(family):
    client, store, sender, _, _ = family
    elder, guardian, link_id = connect(client)
    guardian_id = store.device_id(guardian["Authorization"].split(" ", 1)[1])
    store.subscribe(guardian_id, "https://127.0.0.1/internal", "p", "a")  # 예전 버전이 저장했을 수 있는 주소
    client.post("/api/v1/family/requests", headers=elder, json={"link_ids": [link_id], "risk_level": "dangerous", "factor_codes": []})
    assert sender.sent == []
    assert store.push_targets(guardian_id) == []


def test_web_push_sender_does_not_follow_redirects_or_bad_hosts(monkeypatch):
    import asyncio

    import pywebpush

    from app.family_store import PushTarget

    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)
        session = kwargs["requests_session"]
        assert session.max_redirects == 0 and session.trust_env is False
        return type("Response", (), {"status_code": 302})()

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    sender = WebPushSender("PRIVATE", "mailto:team@example.invalid")
    assert asyncio.run(sender.send(PushTarget("https://fcm.googleapis.com/x", "p", "a"), "{}")) == "failed"
    assert asyncio.run(sender.send(PushTarget("https://127.0.0.1/x", "p", "a"), "{}")) == "gone"
    assert len(calls) == 1


def test_device_registration_is_rate_limited(family):
    client, _, _, clock, _ = family
    for _ in range(30):
        register(client)
    response = client.post("/api/v1/family/devices")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "FAMILY_LIMIT"
    clock.value += timedelta(minutes=11)
    register(client)


def test_idle_devices_are_removed_but_linked_devices_stay(family):
    client, store, _, clock, _ = family
    idle = register(client)
    elder, guardian, link_id = connect(client)
    subscribed = register(client)
    subscribe(client, subscribed, "https://fcm.googleapis.com/fcm/send/keep")
    clock.value += timedelta(hours=25)
    store.purge()
    assert client.get("/api/v1/family/me", headers=idle).status_code == 401
    assert client.get("/api/v1/family/me", headers=elder).status_code == 200
    assert client.get("/api/v1/family/me", headers=guardian).status_code == 200
    assert client.get("/api/v1/family/me", headers=subscribed).status_code == 200
