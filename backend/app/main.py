import asyncio
import logging
from collections.abc import Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .analyzers import Analyzer, RuleBasedAnalyzer
from .contracts import (
    AnalysisInput,
    AnalysisRequest,
    AnalysisResponse,
    ErrorDetail,
    ErrorResponse,
)
from .urls import PUBLIC_ERRORS
from .ocr import OcrEngine, TesseractOcr, OcrError, OCR_ERRORS, MAX_IMAGE_BYTES, prepare_image, url_previews, extract_until_disconnect
from .contracts import OcrResponse, OcrReviewRequest, OcrReviewResponse, MAX_CONTENT_LENGTH
from .urls import UrlInputError
from .url_reputation import configured_reputation_provider

logger = logging.getLogger(__name__)

# OpenAPI 설명을 고정한다. 기본값은 Python 버전별 http.HTTPStatus 문구라 3.13에서 422·413이 바뀐다.
ERROR_DESCRIPTIONS = {
    409: "Conflict",
    413: "Request Entity Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def error_responses(*codes: int) -> dict:
    return {code: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code]} for code in codes}


def create_app(
    analyzer_factory: Callable[[], Analyzer] | None = None,
    analysis_timeout: float = 5.0,
    ocr_factory: Callable[[], OcrEngine] = TesseractOcr,
    ocr_timeout: float = 15.0,
) -> FastAPI:
    app = FastAPI(title="PtoS 규칙·URL·OCR 개발 API", version="0.5.0")
    # App-scoped boundary for a future shared in-memory cache/budget, never per-request keys.
    if analyzer_factory is None:
        reputation_provider = configured_reputation_provider()
        analyzer_factory = lambda: RuleBasedAnalyzer(reputation_provider)
    ocr_lock = asyncio.Lock()

    def error_response(request: Request, status: int, code: str, message: str, retryable: bool):
        body = ErrorResponse(
            error=ErrorDetail(code=code, message=message, retryable=retryable),
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    @app.middleware("http")
    async def privacy_headers(request: Request, call_next):
        request.state.request_id = uuid4()
        try:
            response = await call_next(request)
        except Exception:
            # 예외 문자열/traceback에는 입력이 섞일 수 있어 기록하지 않는다.
            logger.error("ANALYSIS_UNAVAILABLE request_id=%s", request.state.request_id)
            response = error_response(request, 503, "ANALYSIS_UNAVAILABLE", "서버에서 요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.", True)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        # 기본 422 응답은 검증 오류에 원문을 포함하므로 별도 응답을 사용한다.
        too_long = any(e["type"] == "string_too_long" for e in exc.errors())
        for error in exc.errors():
            if error["type"] == "OCR_CONFIRMATION_REQUIRED":
                return error_response(request, 422, error["type"], "추출한 문자와 URL을 확인한 뒤 분석해주세요.", False)
            if error["type"] in PUBLIC_ERRORS:
                return error_response(request, 422, error["type"], PUBLIC_ERRORS[error["type"]], False)
        return error_response(
            request, 422, "INPUT_TOO_LONG" if too_long else "INVALID_INPUT",
            "메시지는 10,000자 이하로 입력해주세요." if too_long else "메시지 내용을 확인해주세요.", False,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "HTTP_ERROR", "요청 주소와 방법을 확인해주세요.", False)

    @app.get("/api/v1/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    async def ready():
        return {"status": "ready", "mode": "rules"}

    @app.post("/api/v1/ocr/review", response_model=OcrReviewResponse, responses=error_responses(422))
    async def review_ocr(body: OcrReviewRequest, request: Request):
        try:
            return OcrReviewResponse(urls=url_previews(body.content), request_id=request.state.request_id)
        except UrlInputError as error:
            return error_response(request, 422, error.code, PUBLIC_ERRORS[error.code], False)

    @app.post("/api/v1/ocr", response_model=OcrResponse,
        responses=error_responses(409, 413, 415, 422, 429, 503, 504),
        openapi_extra={"requestBody": {"required": True, "content": {mime: {"schema": {"type": "string", "format": "binary"}} for mime in ("image/jpeg", "image/png")}}},
    )
    async def recognize(request: Request):
        # 파서의 디스크 스풀을 피하고 실제 수신 바이트에 제한을 적용한다.
        if ocr_lock.locked():
            return error_response(request, 429, "OCR_BUSY", "다른 이미지의 글자를 읽고 있어요. 잠시 후 다시 시도하거나 직접 입력해주세요.", True)
        async with ocr_lock:
            data = bytearray()
            prepared = b""
            try:
                if request.headers.get("content-type", "").split(";", 1)[0].lower() not in {"image/jpeg", "image/png"}:
                    raise OcrError("UNSUPPORTED_MEDIA_TYPE")
                length = request.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_IMAGE_BYTES:
                    raise OcrError("IMAGE_TOO_LARGE")
                async for chunk in request.stream():
                    if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                        raise OcrError("IMAGE_TOO_LARGE")
                    data.extend(chunk)
                prepared = prepare_image(data, request.headers["content-type"].split(";", 1)[0].lower())
                data.clear()
                try:
                    async with asyncio.timeout(ocr_timeout):
                        text = await extract_until_disconnect(ocr_factory(), prepared, request.is_disconnected)
                except TimeoutError:
                    raise OcrError("OCR_TIMEOUT") from None
                if not text.strip():
                    raise OcrError("OCR_NO_TEXT")
                if len(text) > MAX_CONTENT_LENGTH:
                    raise OcrError("OCR_TEXT_TOO_LONG")
                warnings = ["OCR은 글자·URL을 빠뜨리거나 잘못 읽을 수 있어요. 원본과 비교해 전체 내용을 수정하고 확인해주세요. 누락된 내용은 자동 복원하지 않아요.", "아직 위험 분석을 하지 않았고 URL을 열거나 평판 조회하지 않았어요."]
                try:
                    urls = url_previews(text)
                except UrlInputError:
                    urls = []
                    warnings.append("URL 후보가 10개를 초과해 목록을 표시하지 않았어요. 텍스트를 수정한 뒤 확인해주세요.")
                return OcrResponse(text=text, urls=urls, warnings=warnings, request_id=request.state.request_id)
            except OcrError as error:
                status, message = OCR_ERRORS[error.code]
                return error_response(request, status, error.code, message, status in {429, 503, 504})
            except Exception:
                return error_response(request, 503, "OCR_FAILED", OCR_ERRORS["OCR_FAILED"][1], True)
            finally:
                data.clear()
                prepared = b""

    @app.post(
        "/api/v1/analyses", response_model=AnalysisResponse,
        responses=error_responses(422, 503, 504),
    )
    async def analyze(body: AnalysisRequest, request: Request):
        try:
            async with asyncio.timeout(analysis_timeout):
                analyzer = analyzer_factory()
                result = await analyzer.analyze(AnalysisInput(input_type=body.input_type, content=body.content, ocr_confirmed=body.ocr_confirmed))
        except TimeoutError:
            return error_response(request, 504, "ANALYSIS_TIMEOUT", "분석 시간이 길어지고 있어요. 잠시 후 다시 시도해주세요.", True)
        return AnalysisResponse(**result.model_dump(), request_id=request.state.request_id)

    return app


app = create_app()
