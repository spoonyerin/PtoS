"""API 계약의 원본. OpenAPI → TypeScript로 프론트엔드에 전달한다."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

MAX_CONTENT_LENGTH = 10_000
SENDER_NUMBER = re.compile(r"\+?[0-9][0-9 \-]{2,19}")


class RiskLevel(StrEnum):
    NORMAL = "normal"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class AnalysisInput(BaseModel):
    """문자·직접 URL·사용자가 확인한 OCR 문자. URL 검증은 네트워크 없이 수행한다."""

    model_config = ConfigDict(extra="forbid")
    input_type: Literal["text", "url", "ocr_text"]
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    ocr_confirmed: Literal[True] | None = None
    # 2026-11-17 계약 추가(임시, 팀 확정 필요): 사용자가 직접 적은 보낸 번호. 선택이며 불일치일 때만 판정을 올린다.
    sender_number: str | None = Field(default=None, max_length=24)

    @field_validator("sender_number", mode="before")
    @classmethod
    def clean_sender_number(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        # 오류 응답에 입력값을 되돌려 주지 않는다.
        if not isinstance(value, str) or not SENDER_NUMBER.fullmatch(value.strip()):
            raise PydanticCustomError("INVALID_SENDER_NUMBER", "보낸 번호는 숫자와 +, -만 입력해주세요.")
        return value.strip()

    @field_validator("ocr_confirmed", mode="before")
    @classmethod
    def require_explicit_true(cls, value):
        if value is not None and value is not True:
            raise PydanticCustomError("OCR_CONFIRMATION_REQUIRED", "추출한 문자와 URL을 확인한 뒤 분석해주세요.")
        return value

    @field_validator("content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("메시지 내용을 입력해주세요.")
        return value

    @model_validator(mode="after")
    def validate_urls(self):
        from .urls import UrlInputError, extract_urls
        if self.input_type == "ocr_text" and self.ocr_confirmed is not True:
            raise PydanticCustomError("OCR_CONFIRMATION_REQUIRED", "추출한 문자와 URL을 확인한 뒤 분석해주세요.")
        if self.input_type != "ocr_text" and self.ocr_confirmed is not None:
            raise PydanticCustomError("INVALID_INPUT", "OCR 확인은 OCR 입력에서만 사용해주세요.")
        try:
            extract_urls(self.content, direct=self.input_type == "url")
        except UrlInputError as error:
            raise PydanticCustomError(error.code, str(error)) from None
        return self


class AnalysisRequest(AnalysisInput):
    """개발용 결과 선택을 받지 않는다. 입력만으로 분석한다."""


class FactorCode(StrEnum):
    IMPERSONATION = "IMPERSONATION"
    MONEY_REQUEST = "MONEY_REQUEST"
    CREDENTIAL_REQUEST = "CREDENTIAL_REQUEST"
    LINK_CLICK = "LINK_CLICK"
    APP_INSTALL = "APP_INSTALL"
    URGENCY_THREAT = "URGENCY_THREAT"
    URL_REPUTATION_MATCH = "URL_REPUTATION_MATCH"
    # 2026-11-17 계약 추가(임시, 팀 확정 필요): 전화·답장 등 연락 유도, 과도한 혜택·당첨, 비밀 유지 요구.
    CONTACT_REQUEST = "CONTACT_REQUEST"
    BENEFIT_LURE = "BENEFIT_LURE"
    SECRECY_REQUEST = "SECRECY_REQUEST"
    # 2026-11-17 계약 추가(임시, 팀 확정 필요): 문자가 내세운 기관 이름과 사용자가 적은 보낸 번호의 불일치.
    SENDER_MISMATCH = "SENDER_MISMATCH"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factor_code: FactorCode
    label: str
    source: Literal["rule", "url_reputation"] = "rule"
    rule_id: str
    snippet: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class InputAssessment(BaseModel):
    status: Literal["action_identified", "sentence_present", "fragment", "url_only"]
    reasons: list[str]


class AnalysisStage(BaseModel):
    # llm_review(2026-11-17 계약 추가): 조건부 추가 검토 단계. CompositeAnalyzer의 결과에만 있다.
    # sender_check(2026-11-17 계약 추가): 보낸 번호 비교. 번호가 없거나 비교할 기관 이름이 없으면 not_applicable.
    name: Literal["rules", "lightweight_model", "url_reputation", "sender_check", "llm_review"]
    status: Literal["completed", "not_implemented", "not_connected", "not_applicable", "unavailable"]


class UrlReputation(BaseModel):
    status: Literal["not_connected", "not_requested", "malicious", "benign", "unknown", "unavailable", "timeout", "auth_error", "rate_limited"]
    provider: str | None = None
    checked_at: datetime | None = None
    reason: str | None = None
    full_hash_verified: bool = False
    threat_types: list[Literal["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]] = Field(default_factory=list)
    cache_expires_at: datetime | None = None
    cache_hit: bool = False


class UrlOccurrence(BaseModel):
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class UrlPreview(BaseModel):
    original_url: str
    normalized_url: str | None
    ascii_host: str | None
    validation_status: Literal["valid", "invalid"]
    validation_message: str
    warnings: list[str]
    occurrences: list[UrlOccurrence]


class UrlFinding(UrlPreview):
    reputation: UrlReputation


class OcrReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=MAX_CONTENT_LENGTH)


class OcrReviewResponse(BaseModel):
    urls: list[UrlPreview]
    request_id: UUID


class OcrResponse(OcrReviewResponse):
    text: str
    warnings: list[str]
    engine: Literal["tesseract-5"] = "tesseract-5"
    ocr_confidence: None = None


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_level: RiskLevel
    confidence: None = None
    risk_factors: list[str]
    explanation: str
    action_guidance: list[str]
    limitations: list[str]
    analysis_version: str
    is_demo: Literal[False] = False
    analysis_mode: Literal["rules"] = "rules"
    evidence: list[Evidence]
    input_assessment: InputAssessment
    analysis_stages: list[AnalysisStage]
    policy_reason: str
    urls: list[UrlFinding]


class AnalysisResponse(AnalysisResult):
    request_id: UUID


class ReadyResponse(BaseModel):
    """준비 상태. url_reputation은 실제 외부 평판 조회가, llm_review는 조건부 추가 검토(가린 문장의 외부 전송)가 켜졌는지만 알린다.

    키·주소·모델 이름·시간 제한·공급자 세부 상태는 넣지 않는다.
    """

    status: Literal["ready"] = "ready"
    mode: Literal["rules"] = "rules"
    url_reputation: Literal["live", "off"]
    llm_review: Literal["live", "off"]
    # 2026-11-25 계약 추가(발표 시연 한정, 팀 확정 필요): 가족 보호 저장소와 웹 푸시가 켜졌는지만 알린다.
    family: Literal["live", "off"]
    push: Literal["live", "off"]


# ---- 가족 보호 (2026-11-25 계약 추가, 발표 시연 한정, 팀 확정 필요, docs/FAMILY_SHARE.md) ----
# 원문·URL·보낸 번호·근거 구절은 요청과 응답 어디에도 없다. 확인 요청은 위험 단계와 위험 요소 코드만 담는다.

FamilyRelation = Literal["child", "spouse", "sibling", "other"]
FamilyReplyChoice = Literal["looks_dangerous", "looks_fine", "custom"]


class FamilyDeviceResponse(BaseModel):
    device_token: str


class FamilyLink(BaseModel):
    id: str
    # guardian: 나를 지켜 주는 가족(내가 초대함), protected: 내가 지켜 주는 가족(내가 초대를 받음)
    role: Literal["guardian", "protected"]
    name: str
    relation: FamilyRelation | None
    status: Literal["pending", "connected"]
    invite_expires_at: datetime | None


class FamilyAutoAlert(BaseModel):
    enabled: bool
    link_id: str | None


class FamilySummary(BaseModel):
    premium: bool
    auto_alert: FamilyAutoAlert
    links: list[FamilyLink]
    push_subscribed: bool
    waiting_requests: int
    new_replies: int
    server_time: datetime


class FamilyPremiumRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


class FamilyInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    relation: FamilyRelation


class FamilyInviteResponse(BaseModel):
    link_id: str
    invite_token: str
    expires_at: datetime


class FamilyInviteTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)


class FamilyInvitePreview(BaseModel):
    guardian_name: str
    relation: FamilyRelation
    expires_at: datetime


class FamilyAcceptRequest(FamilyInviteTokenRequest):
    name: str = Field(min_length=1, max_length=40)


class FamilyAutoAlertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link_id: str | None


class FamilyShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link_ids: list[str] = Field(min_length=1, max_length=5)
    risk_level: RiskLevel
    factor_codes: list[FactorCode] = Field(max_length=len(FactorCode))
    auto: bool = False


class FamilyShareResponse(BaseModel):
    request_ids: list[str]


class FamilyReply(BaseModel):
    choice: FamilyReplyChoice
    text: str | None
    replied_at: datetime


class FamilyRequestItem(BaseModel):
    id: str
    box: Literal["sent", "received"]
    name: str
    risk_level: RiskLevel
    factor_codes: list[FactorCode]
    auto: bool
    created_at: datetime
    expires_at: datetime
    viewed_at: datetime | None
    reply: FamilyReply | None


class FamilyRequestList(BaseModel):
    items: list[FamilyRequestItem]


class FamilyReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: FamilyReplyChoice
    text: str | None = Field(default=None, max_length=200)


class FamilyPushKey(BaseModel):
    public_key: str | None


class FamilyPushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class FamilyPushSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=9, max_length=1024, pattern=r"^https://")
    keys: FamilyPushKeys


class FamilyPushRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str | None = Field(default=None, max_length=1024)


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: UUID
