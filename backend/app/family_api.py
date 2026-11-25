"""가족 보호 API (/api/v1/family, 발표 시연 한정, 팀 확정 필요, docs/FAMILY_SHARE.md).

기기는 서버가 발급한 무작위 열쇠(Authorization: Bearer)로만 구분한다. 계정·전화번호·로그인은 없다.
요청과 응답에 원문·URL·보낸 번호·근거 구절을 넣지 않는다. 오류 응답에는 고정 코드와 문장만 넣는다.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .contracts import (
    ErrorResponse,
    FamilyAcceptRequest,
    FamilyAutoAlertRequest,
    FamilyDeviceResponse,
    FamilyInvitePreview,
    FamilyInviteRequest,
    FamilyInviteResponse,
    FamilyInviteTokenRequest,
    FamilyPremiumRequest,
    FamilyPushKey,
    FamilyPushRemove,
    FamilyPushSubscription,
    FamilyReplyRequest,
    FamilyRequestItem,
    FamilyRequestList,
    FamilyShareRequest,
    FamilyShareResponse,
    FamilySummary,
)
from .family_push import FamilyNotifier, FamilySetup, is_push_endpoint
from .family_store import FamilyError

PREFIX = "/api/v1/family"

FAMILY_ERRORS: dict[str, tuple[int, str]] = {
    "FAMILY_OFF": (503, "가족 보호 기능이 이 서버에서 꺼져 있어요."),
    "DEVICE_REQUIRED": (401, "이 기기 정보를 찾지 못했어요. 가족 보호 화면을 다시 열어 주세요."),
    "PREMIUM_REQUIRED": (403, "가족 보호 프리미엄(시연용)을 먼저 시작해 주세요."),
    "NOT_FOUND": (404, "내용을 찾지 못했어요. 이미 지워졌거나 보관 기간이 지났을 수 있어요."),
    "INVITE_NOT_FOUND": (404, "초대를 찾지 못했어요. 초대한 가족에게 새 초대 링크를 받아 주세요."),
    "INVITE_USED": (409, "이미 사용한 초대예요. 초대한 가족에게 새 초대 링크를 받아 주세요."),
    "INVITE_EXPIRED": (410, "초대 기한(24시간)이 지났어요. 초대한 가족에게 새 초대 링크를 받아 주세요."),
    "INVITE_SELF": (409, "내가 만든 초대는 이 기기에서 수락할 수 없어요. 가족의 휴대폰에서 열어 주세요."),
    "ALREADY_LINKED": (409, "이미 연결된 가족이에요."),
    "ALREADY_REPLIED": (409, "이미 의견을 보냈어요."),
    "AUTO_ALERT_OFF": (409, "자동 알림이 꺼져 있어요."),
    "FAMILY_LIMIT": (429, "가족 보호 사용 한도에 이르렀어요. 잠시 후 다시 시도해 주세요."),
    "INVALID_NAME": (422, "부르는 이름은 1~20자로 입력해 주세요."),
    "INVALID_RELATION": (422, "관계를 골라 주세요."),
    "INVALID_REPLY": (422, "보낼 의견을 고르거나 100자 이하로 입력해 주세요."),
    "INVALID_PUSH": (422, "이 브라우저의 알림 주소를 쓸 수 없어요. 다른 브라우저로 알림을 켜 주세요."),
    "PUSH_OFF": (503, "이 서버에서는 알림을 보낼 수 없어요."),
}


def _family_responses(*codes: int) -> dict:
    descriptions = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 410: "Gone",
                    422: "Unprocessable Entity", 429: "Too Many Requests", 503: "Service Unavailable"}
    return {code: {"model": ErrorResponse, "description": descriptions[code]} for code in codes}


def register_family_routes(app: FastAPI, setup: FamilySetup,
                           error_response: Callable[[Request, int, str, str, bool], JSONResponse]) -> None:
    store = setup.store
    notifier = FamilyNotifier(store, setup.sender) if store is not None else None

    def fail(request: Request, code: str) -> JSONResponse:
        status, message = FAMILY_ERRORS.get(code, (503, "가족 보호 요청을 처리하지 못했어요."))
        return error_response(request, status, code, message, status in (429, 503))

    def device(request: Request) -> str:
        if store is None:
            raise FamilyError("FAMILY_OFF")
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            raise FamilyError("DEVICE_REQUIRED")
        return store.device_id(token.strip())

    def run(request: Request, action: Callable[[], object]):
        try:
            if store is None:
                raise FamilyError("FAMILY_OFF")
            return action()
        except FamilyError as error:
            return fail(request, error.code)

    common = _family_responses(401, 404, 422, 503)

    @app.post(f"{PREFIX}/devices", response_model=FamilyDeviceResponse, status_code=201,
              responses=_family_responses(429, 503))
    async def register_device(request: Request):
        return run(request, lambda: FamilyDeviceResponse(device_token=store.register_device()))

    @app.delete(f"{PREFIX}/devices/me", status_code=204, responses=common)
    async def delete_device(request: Request):
        def action():
            store.delete_device(device(request))
            return Response(status_code=204)
        return run(request, action)

    @app.get(f"{PREFIX}/me", response_model=FamilySummary, responses=common)
    async def summary(request: Request):
        return run(request, lambda: FamilySummary(**store.summary(device(request))))

    @app.put(f"{PREFIX}/premium", response_model=FamilySummary, responses=common)
    async def premium(body: FamilyPremiumRequest, request: Request):
        def action():
            me = device(request)
            store.set_premium(me, body.active)
            return FamilySummary(**store.summary(me))
        return run(request, action)

    @app.post(f"{PREFIX}/invites", response_model=FamilyInviteResponse, status_code=201,
              responses=_family_responses(401, 403, 404, 422, 429, 503))
    async def create_invite(body: FamilyInviteRequest, request: Request):
        def action():
            link_id, token, expires = store.create_invite(device(request), body.name, body.relation)
            return FamilyInviteResponse(link_id=link_id, invite_token=token, expires_at=expires)
        return run(request, action)

    @app.post(f"{PREFIX}/invites/preview", response_model=FamilyInvitePreview,
              responses=_family_responses(401, 404, 409, 410, 422, 503))
    async def preview_invite(body: FamilyInviteTokenRequest, request: Request):
        def action():
            device(request)
            return FamilyInvitePreview(**store.preview_invite(body.token))
        return run(request, action)

    @app.post(f"{PREFIX}/invites/accept", response_model=FamilySummary,
              responses=_family_responses(401, 404, 409, 410, 422, 503))
    async def accept_invite(body: FamilyAcceptRequest, request: Request, background: BackgroundTasks):
        def action():
            me = device(request)
            inviter = store.accept_invite(me, body.token, body.name)
            background.add_task(notifier.notify, inviter, "linked", "/#family")
            return FamilySummary(**store.summary(me))
        return run(request, action)

    @app.delete(f"{PREFIX}/links/{{link_id}}", response_model=FamilySummary, responses=common)
    async def remove_link(link_id: str, request: Request):
        def action():
            me = device(request)
            store.remove_link(me, link_id)
            return FamilySummary(**store.summary(me))
        return run(request, action)

    @app.put(f"{PREFIX}/auto-alert", response_model=FamilySummary,
             responses=_family_responses(401, 403, 404, 422, 503))
    async def auto_alert(body: FamilyAutoAlertRequest, request: Request):
        def action():
            me = device(request)
            store.set_auto_alert(me, body.link_id)
            return FamilySummary(**store.summary(me))
        return run(request, action)

    @app.post(f"{PREFIX}/requests", response_model=FamilyShareResponse, status_code=201,
              responses=_family_responses(401, 403, 404, 409, 422, 429, 503))
    async def share(body: FamilyShareRequest, request: Request, background: BackgroundTasks):
        def action():
            codes = list(dict.fromkeys(code.value for code in body.factor_codes))
            created = store.create_requests(device(request), body.link_ids, body.risk_level.value, codes, body.auto)
            for request_id, guardian in created:
                background.add_task(notifier.notify, guardian, "request", f"/#family/request/{request_id}")
            return FamilyShareResponse(request_ids=[request_id for request_id, _ in created])
        return run(request, action)

    @app.get(f"{PREFIX}/requests", response_model=FamilyRequestList, responses=common)
    async def list_requests(request: Request, box: str = "sent"):
        def action():
            if box not in ("sent", "received"):
                raise FamilyError("NOT_FOUND")
            return FamilyRequestList(items=store.list_requests(device(request), box))
        return run(request, action)

    @app.get(f"{PREFIX}/requests/{{request_id}}", response_model=FamilyRequestItem, responses=common)
    async def get_request(request_id: str, request: Request):
        return run(request, lambda: FamilyRequestItem(**store.get_request(device(request), request_id)))

    @app.post(f"{PREFIX}/requests/{{request_id}}/reply", response_model=FamilyRequestItem,
              responses=_family_responses(401, 404, 409, 422, 503))
    async def reply(request_id: str, body: FamilyReplyRequest, request: Request, background: BackgroundTasks):
        def action():
            me = device(request)
            sender = store.reply(me, request_id, body.choice, body.text)
            background.add_task(notifier.notify, sender, "reply", f"/#family/request/{request_id}")
            return FamilyRequestItem(**store.get_request(me, request_id))
        return run(request, action)

    @app.get(f"{PREFIX}/push/key", response_model=FamilyPushKey, responses=_family_responses(503))
    async def push_key(request: Request):
        return run(request, lambda: FamilyPushKey(public_key=setup.public_key if setup.sender else None))

    @app.put(f"{PREFIX}/push", response_model=FamilySummary, responses=common)
    async def subscribe(body: FamilyPushSubscription, request: Request):
        def action():
            me = device(request)
            if setup.sender is None:
                raise FamilyError("PUSH_OFF")
            if not is_push_endpoint(body.endpoint):
                raise FamilyError("INVALID_PUSH")
            store.subscribe(me, body.endpoint, body.keys.p256dh, body.keys.auth)
            return FamilySummary(**store.summary(me))
        return run(request, action)

    @app.post(f"{PREFIX}/push/remove", response_model=FamilySummary, responses=common)
    async def unsubscribe(body: FamilyPushRemove, request: Request):
        def action():
            me = device(request)
            store.unsubscribe(me, body.endpoint)
            return FamilySummary(**store.summary(me))
        return run(request, action)
