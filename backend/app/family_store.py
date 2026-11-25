"""가족 보호(발표 시연 한정) 저장소. 표준 라이브러리 sqlite3만 쓴다.

저장하는 것: 기기 열쇠의 SHA-256, 시연용 가입 여부, 가족 연결(서로 부르는 호칭·관계), 초대 열쇠의 SHA-256,
확인 요청(위험 단계·위험 요소 코드·시각), 가족 의견(고정 선택지 또는 100자 이하 직접 입력), 웹 푸시 구독 정보.
저장하지 않는 것: 입력 원문, URL, 보낸 번호, 근거 구절, 전화번호, 분석 응답 전체.
확인 요청과 의견은 보관 기간(기본 7일, 임시)이 지나면 지운다. 초대는 24시간, 1회용이다.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from collections import deque
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

INVITE_HOURS = 24
DEFAULT_RETENTION_DAYS = 7
MAX_LINKS_PER_DEVICE = 5
MAX_REQUESTS_PER_DAY = 50
MAX_DEVICES = 2_000
# 기기 등록 남용 방지(개발 제안). 서버 전체에서 10분에 30개까지 등록하고,
# 연결·초대·알림 구독이 하나도 없이 24시간이 지난 기기는 지운다(한도를 채워 시연을 막지 못하게).
REGISTER_WINDOW = timedelta(minutes=10)
MAX_REGISTER_PER_WINDOW = 30
IDLE_DEVICE_HOURS = 24
MAX_NAME_LENGTH = 20
MAX_REPLY_LENGTH = 100
RELATIONS = ("child", "spouse", "sibling", "other")
REPLY_CHOICES = ("looks_dangerous", "looks_fine", "custom")

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    premium INTEGER NOT NULL DEFAULT 0,
    auto_alert_link_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY,
    protected_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    guardian_id TEXT REFERENCES devices(id) ON DELETE CASCADE,
    guardian_name TEXT NOT NULL,
    relation TEXT NOT NULL,
    protected_name TEXT,
    invite_hash TEXT UNIQUE,
    invite_expires_at TEXT,
    created_at TEXT NOT NULL,
    accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    link_id TEXT NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    risk_level TEXT NOT NULL,
    factor_codes TEXT NOT NULL,
    auto INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    viewed_at TEXT,
    reply_choice TEXT,
    reply_text TEXT,
    replied_at TEXT,
    reply_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS links_protected ON links(protected_id);
CREATE INDEX IF NOT EXISTS links_guardian ON links(guardian_id);
CREATE INDEX IF NOT EXISTS requests_link ON requests(link_id);
"""


class FamilyError(Exception):
    """API가 고정 코드로 바꿔 돌려주는 오류. 메시지에 입력값을 넣지 않는다."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def clean_name(value: str) -> str:
    """호칭은 1~20자 일반 문자만. 제어 문자·줄바꿈은 거부한다."""
    name = " ".join(value.split())
    if not name or len(name) > MAX_NAME_LENGTH:
        raise FamilyError("INVALID_NAME")
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        raise FamilyError("INVALID_NAME")
    return name


def clean_reply(value: str | None) -> str:
    text = (value or "").strip()
    if not text or len(text) > MAX_REPLY_LENGTH:
        raise FamilyError("INVALID_REPLY")
    if any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in text):
        raise FamilyError("INVALID_REPLY")
    return text


class FamilyStore:
    def __init__(self, path: str, *, retention_days: int = DEFAULT_RETENTION_DAYS,
                 now: Callable[[], datetime] | None = None):
        self._now = now or (lambda: datetime.now(UTC))
        self.retention = timedelta(days=retention_days)
        self._lock = threading.Lock()
        self._registered: deque[datetime] = deque()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        self.purge()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- 내부 도구 -------------------------------------------------------
    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._lock.acquire()
                store._db.execute("BEGIN IMMEDIATE")
                return store._db

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    store._db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store._lock.release()
                return False

        return _Tx()

    def purge(self) -> None:
        now = _iso(self._now())
        with self._tx() as db:
            db.execute("DELETE FROM requests WHERE expires_at <= ?", (now,))
            # 수락되지 않은 채 만료된 초대는 연결 후보에서 지운다.
            db.execute("DELETE FROM links WHERE guardian_id IS NULL AND invite_expires_at <= ?", (now,))
            # 연결·초대·알림 구독이 없는 채로 오래된 기기는 지운다.
            idle_before = _iso(self._now() - timedelta(hours=IDLE_DEVICE_HOURS))
            db.execute(
                "DELETE FROM devices WHERE created_at <= ? "
                "AND NOT EXISTS (SELECT 1 FROM links l WHERE l.protected_id = devices.id OR l.guardian_id = devices.id) "
                "AND NOT EXISTS (SELECT 1 FROM push_subscriptions p WHERE p.device_id = devices.id)", (idle_before,))

    # ---- 기기 ------------------------------------------------------------
    def register_device(self) -> str:
        token = secrets.token_urlsafe(32)
        now = self._now()
        self.purge()
        with self._tx() as db:
            while self._registered and self._registered[0] <= now - REGISTER_WINDOW:
                self._registered.popleft()
            if len(self._registered) >= MAX_REGISTER_PER_WINDOW:
                raise FamilyError("FAMILY_LIMIT")
            if db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] >= MAX_DEVICES:
                raise FamilyError("FAMILY_LIMIT")
            db.execute("INSERT INTO devices (id, token_hash, created_at) VALUES (?, ?, ?)",
                       (str(uuid.uuid4()), _hash(token), _iso(now)))
            self._registered.append(now)
        return token

    def device_id(self, token: str | None) -> str:
        if not token or len(token) > 128:
            raise FamilyError("DEVICE_REQUIRED")
        with self._lock:
            row = self._db.execute("SELECT id FROM devices WHERE token_hash = ?", (_hash(token),)).fetchone()
        if row is None:
            raise FamilyError("DEVICE_REQUIRED")
        return row["id"]

    def delete_device(self, device_id: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    def set_premium(self, device_id: str, active: bool) -> None:
        with self._tx() as db:
            db.execute("UPDATE devices SET premium = ?, auto_alert_link_id = CASE WHEN ? THEN auto_alert_link_id END WHERE id = ?",
                       (int(active), int(active), device_id))

    def _require_premium(self, db, device_id: str) -> None:
        if not db.execute("SELECT premium FROM devices WHERE id = ?", (device_id,)).fetchone()["premium"]:
            raise FamilyError("PREMIUM_REQUIRED")

    # ---- 조회 ------------------------------------------------------------
    def summary(self, device_id: str, push_subscribed_endpoint: str | None = None) -> dict:
        self.purge()
        now = self._now()
        with self._lock:
            device = self._db.execute("SELECT premium, auto_alert_link_id FROM devices WHERE id = ?", (device_id,)).fetchone()
            rows = self._db.execute(
                "SELECT * FROM links WHERE protected_id = ? OR guardian_id = ? ORDER BY created_at", (device_id, device_id)).fetchall()
            subscribed = self._db.execute("SELECT COUNT(*) FROM push_subscriptions WHERE device_id = ?", (device_id,)).fetchone()[0]
            waiting = self._db.execute(
                "SELECT COUNT(*) FROM requests r JOIN links l ON l.id = r.link_id WHERE l.guardian_id = ? AND r.replied_at IS NULL",
                (device_id,)).fetchone()[0]
            new_replies = self._db.execute(
                "SELECT COUNT(*) FROM requests r JOIN links l ON l.id = r.link_id "
                "WHERE l.protected_id = ? AND r.replied_at IS NOT NULL AND r.reply_seen_at IS NULL", (device_id,)).fetchone()[0]
        links = []
        for row in rows:
            mine = row["protected_id"] == device_id
            links.append({
                "id": row["id"],
                "role": "guardian" if mine else "protected",
                "name": row["guardian_name"] if mine else (row["protected_name"] or "가족"),
                "relation": row["relation"] if mine else None,
                "status": "connected" if row["guardian_id"] else "pending",
                "invite_expires_at": None if row["guardian_id"] else row["invite_expires_at"],
            })
        auto_link = device["auto_alert_link_id"]
        return {
            "premium": bool(device["premium"]),
            "auto_alert": {"enabled": auto_link is not None, "link_id": auto_link},
            "links": links,
            "push_subscribed": subscribed > 0,
            "waiting_requests": waiting,
            "new_replies": new_replies,
            "server_time": _iso(now),
        }

    # ---- 초대와 연결 ----------------------------------------------------
    def create_invite(self, device_id: str, name: str, relation: str) -> tuple[str, str, str]:
        name = clean_name(name)
        if relation not in RELATIONS:
            raise FamilyError("INVALID_RELATION")
        token = secrets.token_urlsafe(24)
        now = self._now()
        expires = _iso(now + timedelta(hours=INVITE_HOURS))
        link_id = str(uuid.uuid4())
        self.purge()
        with self._tx() as db:
            self._require_premium(db, device_id)
            count = db.execute("SELECT COUNT(*) FROM links WHERE protected_id = ?", (device_id,)).fetchone()[0]
            if count >= MAX_LINKS_PER_DEVICE:
                raise FamilyError("FAMILY_LIMIT")
            db.execute(
                "INSERT INTO links (id, protected_id, guardian_name, relation, invite_hash, invite_expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (link_id, device_id, name, relation, _hash(token), expires, _iso(now)))
        return link_id, token, expires

    def _open_invite(self, db, token: str):
        row = db.execute("SELECT * FROM links WHERE invite_hash = ?", (_hash(token),)).fetchone() if token and len(token) <= 128 else None
        if row is None:
            raise FamilyError("INVITE_NOT_FOUND")
        if row["guardian_id"] is not None:
            raise FamilyError("INVITE_USED")
        if row["invite_expires_at"] <= _iso(self._now()):
            raise FamilyError("INVITE_EXPIRED")
        return row

    def preview_invite(self, token: str) -> dict:
        with self._tx() as db:
            row = self._open_invite(db, token)
        return {"guardian_name": row["guardian_name"], "relation": row["relation"], "expires_at": row["invite_expires_at"]}

    def accept_invite(self, device_id: str, token: str, protected_name: str) -> str:
        protected_name = clean_name(protected_name)
        with self._tx() as db:
            row = self._open_invite(db, token)
            if row["protected_id"] == device_id:
                raise FamilyError("INVITE_SELF")
            if db.execute("SELECT 1 FROM links WHERE protected_id = ? AND guardian_id = ?",
                          (row["protected_id"], device_id)).fetchone():
                raise FamilyError("ALREADY_LINKED")
            db.execute("UPDATE links SET guardian_id = ?, protected_name = ?, invite_hash = NULL, invite_expires_at = NULL, "
                       "accepted_at = ? WHERE id = ?", (device_id, protected_name, _iso(self._now()), row["id"]))
        return row["protected_id"]

    def remove_link(self, device_id: str, link_id: str) -> None:
        with self._tx() as db:
            row = db.execute("SELECT protected_id, guardian_id FROM links WHERE id = ?", (link_id,)).fetchone()
            if row is None or device_id not in (row["protected_id"], row["guardian_id"]):
                raise FamilyError("NOT_FOUND")
            db.execute("UPDATE devices SET auto_alert_link_id = NULL WHERE auto_alert_link_id = ?", (link_id,))
            db.execute("DELETE FROM links WHERE id = ?", (link_id,))

    def set_auto_alert(self, device_id: str, link_id: str | None) -> None:
        with self._tx() as db:
            if link_id is not None:
                self._require_premium(db, device_id)
                row = db.execute("SELECT 1 FROM links WHERE id = ? AND protected_id = ? AND guardian_id IS NOT NULL",
                                 (link_id, device_id)).fetchone()
                if row is None:
                    raise FamilyError("NOT_FOUND")
            db.execute("UPDATE devices SET auto_alert_link_id = ? WHERE id = ?", (link_id, device_id))

    # ---- 확인 요청 ------------------------------------------------------
    def create_requests(self, device_id: str, link_ids: list[str], risk_level: str, factor_codes: list[str],
                        auto: bool) -> list[tuple[str, str]]:
        """확인 요청을 만들고 (요청 id, 받는 기기 id) 목록을 돌려준다."""
        now = self._now()
        self.purge()
        created: list[tuple[str, str]] = []
        with self._tx() as db:
            self._require_premium(db, device_id)
            if auto:
                auto_link = db.execute("SELECT auto_alert_link_id FROM devices WHERE id = ?", (device_id,)).fetchone()[0]
                if auto_link is None or link_ids != [auto_link]:
                    raise FamilyError("AUTO_ALERT_OFF")
            since = _iso(now - timedelta(days=1))
            sent = db.execute("SELECT COUNT(*) FROM requests r JOIN links l ON l.id = r.link_id "
                              "WHERE l.protected_id = ? AND r.created_at > ?", (device_id, since)).fetchone()[0]
            if sent + len(link_ids) > MAX_REQUESTS_PER_DAY:
                raise FamilyError("FAMILY_LIMIT")
            for link_id in dict.fromkeys(link_ids):
                row = db.execute("SELECT guardian_id FROM links WHERE id = ? AND protected_id = ? AND guardian_id IS NOT NULL",
                                 (link_id, device_id)).fetchone()
                if row is None:
                    raise FamilyError("NOT_FOUND")
                request_id = str(uuid.uuid4())
                db.execute("INSERT INTO requests (id, link_id, risk_level, factor_codes, auto, created_at, expires_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (request_id, link_id, risk_level, json.dumps(factor_codes), int(auto), _iso(now),
                            _iso(now + self.retention)))
                created.append((request_id, row["guardian_id"]))
        return created

    def _request_row(self, db, device_id: str, request_id: str):
        row = db.execute(
            "SELECT r.*, l.protected_id, l.guardian_id, l.guardian_name, l.protected_name, l.relation "
            "FROM requests r JOIN links l ON l.id = r.link_id WHERE r.id = ?", (request_id,)).fetchone()
        if row is None or device_id not in (row["protected_id"], row["guardian_id"]):
            raise FamilyError("NOT_FOUND")
        return row

    @staticmethod
    def _request_view(row, device_id: str) -> dict:
        sent = row["protected_id"] == device_id
        reply = None
        if row["replied_at"]:
            reply = {"choice": row["reply_choice"], "text": row["reply_text"], "replied_at": row["replied_at"]}
        return {
            "id": row["id"],
            "box": "sent" if sent else "received",
            "name": row["guardian_name"] if sent else (row["protected_name"] or "가족"),
            "risk_level": row["risk_level"],
            "factor_codes": json.loads(row["factor_codes"]),
            "auto": bool(row["auto"]),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "viewed_at": row["viewed_at"],
            "reply": reply,
        }

    def list_requests(self, device_id: str, box: str) -> list[dict]:
        self.purge()
        column = "l.protected_id" if box == "sent" else "l.guardian_id"
        with self._lock:
            rows = self._db.execute(
                "SELECT r.*, l.protected_id, l.guardian_id, l.guardian_name, l.protected_name, l.relation "
                f"FROM requests r JOIN links l ON l.id = r.link_id WHERE {column} = ? ORDER BY r.created_at DESC LIMIT 100",
                (device_id,)).fetchall()
        return [self._request_view(row, device_id) for row in rows]

    def get_request(self, device_id: str, request_id: str) -> dict:
        self.purge()
        with self._tx() as db:
            row = self._request_row(db, device_id, request_id)
            now = _iso(self._now())
            # 받은 사람이 열면 '확인함', 보낸 사람이 도착한 의견을 열면 '의견 읽음'으로 표시한다.
            if row["guardian_id"] == device_id and row["viewed_at"] is None:
                db.execute("UPDATE requests SET viewed_at = ? WHERE id = ?", (now, request_id))
            if row["protected_id"] == device_id and row["replied_at"] and row["reply_seen_at"] is None:
                db.execute("UPDATE requests SET reply_seen_at = ? WHERE id = ?", (now, request_id))
            row = self._request_row(db, device_id, request_id)
        return self._request_view(row, device_id)

    def reply(self, device_id: str, request_id: str, choice: str, text: str | None) -> str:
        """의견을 저장하고 알림을 받을 기기 id를 돌려준다."""
        if choice not in REPLY_CHOICES:
            raise FamilyError("INVALID_REPLY")
        reply_text = clean_reply(text) if choice == "custom" else None
        with self._tx() as db:
            row = self._request_row(db, device_id, request_id)
            if row["guardian_id"] != device_id:
                raise FamilyError("NOT_FOUND")
            if row["replied_at"]:
                raise FamilyError("ALREADY_REPLIED")
            now = _iso(self._now())
            db.execute("UPDATE requests SET reply_choice = ?, reply_text = ?, replied_at = ?, viewed_at = COALESCE(viewed_at, ?) "
                       "WHERE id = ?", (choice, reply_text, now, now, request_id))
        return row["protected_id"]

    # ---- 웹 푸시 구독 ----------------------------------------------------
    def subscribe(self, device_id: str, endpoint: str, p256dh: str, auth: str) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO push_subscriptions (endpoint, device_id, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?) "
                       "ON CONFLICT(endpoint) DO UPDATE SET device_id = excluded.device_id, p256dh = excluded.p256dh, auth = excluded.auth",
                       (endpoint, device_id, p256dh, auth, _iso(self._now())))
            # 한 기기에 구독을 몇 개만 남긴다(브라우저를 바꿀 때마다 쌓이지 않게).
            db.execute("DELETE FROM push_subscriptions WHERE device_id = ? AND endpoint NOT IN "
                       "(SELECT endpoint FROM push_subscriptions WHERE device_id = ? ORDER BY created_at DESC LIMIT 3)",
                       (device_id, device_id))

    def unsubscribe(self, device_id: str, endpoint: str | None = None) -> None:
        with self._tx() as db:
            if endpoint is None:
                db.execute("DELETE FROM push_subscriptions WHERE device_id = ?", (device_id,))
            else:
                db.execute("DELETE FROM push_subscriptions WHERE device_id = ? AND endpoint = ?", (device_id, endpoint))

    def push_targets(self, device_id: str) -> list[PushTarget]:
        with self._lock:
            rows = self._db.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE device_id = ?",
                                    (device_id,)).fetchall()
        return [PushTarget(row["endpoint"], row["p256dh"], row["auth"]) for row in rows]

    def drop_subscription(self, endpoint: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
