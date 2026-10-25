"""API 계약의 원본. OpenAPI → TypeScript로 프론트엔드에 전달한다."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

MAX_CONTENT_LENGTH = 10_000


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
    name: Literal["rules", "lightweight_model", "url_reputation"]
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


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: UUID
