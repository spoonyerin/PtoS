"""가짜 OCR로 계약·제어 흐름을 검증한다. 실제 인식 정확도 테스트가 아니다."""
import asyncio
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.ocr import OcrError, TesseractOcr, prepare_image, extract_until_disconnect


def picture(fmt="PNG", size=(80, 40)):
    with Image.new("RGB", size, "white") as image, io.BytesIO() as stream:
        image.save(stream, format=fmt)
        return stream.getvalue()


class FakeOcr:
    async def extract(self, image):
        assert image.startswith(b"\x89PNG")
        return "은행입니다. 인증번호를 알려주세요. https://example.invalid/O0l1"


def must_not_analyze():
    raise AssertionError("OCR/review must not call Analyzer")


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_upload_only_recognizes_and_reviews_without_analysis_or_reputation(fmt, mime, caplog):
    client = TestClient(create_app(analyzer_factory=must_not_analyze, ocr_factory=FakeOcr))
    result = client.post("/api/v1/ocr", content=picture(fmt), headers={"Content-Type": mime})
    assert result.status_code == 200
    body = result.json()
    assert body["text"].endswith("/O0l1")  # 치환·추측 복원 없음
    assert body["urls"][0]["original_url"].endswith("/O0l1")
    assert "risk_level" not in body and "reputation" not in body["urls"][0]
    assert body["ocr_confidence"] is None
    assert result.headers["cache-control"] == "no-store"
    edited = "😀 https://예시.한국/공지. https://-bad.invalid/"
    reviewed = client.post("/api/v1/ocr/review", json={"content": edited}).json()
    assert len(reviewed["urls"]) == 2
    assert reviewed["urls"][1]["validation_status"] == "invalid"
    for url in reviewed["urls"]:
        for occurrence in url["occurrences"]:
            assert edited[occurrence["start"]:occurrence["end"]] == occurrence["text"]
    assert body["text"] not in caplog.text and edited not in caplog.text


@pytest.mark.parametrize("content,mime,code,status", [
    (b"not an image", "image/png", "INVALID_IMAGE", 422),
    (b"<svg onload='secret'/>SECRET", "image/png", "INVALID_IMAGE", 422),
    (picture("GIF"), "image/png", "UNSUPPORTED_MEDIA_TYPE", 415),
    (picture("PNG"), "image/jpeg", "UNSUPPORTED_MEDIA_TYPE", 415),
    (picture("JPEG")[:-80], "image/jpeg", "INVALID_IMAGE", 422),
    (picture(), "application/octet-stream", "UNSUPPORTED_MEDIA_TYPE", 415),
    (b"", "image/png", "INVALID_IMAGE", 422),
])
def test_actual_format_decode_and_sanitized_errors(content, mime, code, status, caplog):
    client = TestClient(create_app(ocr_factory=must_not_analyze))
    result = client.post("/api/v1/ocr", content=content, headers={"Content-Type": mime})
    assert result.status_code == status
    assert result.json()["error"]["code"] == code
    assert "SECRET" not in result.text + caplog.text
    assert result.headers["cache-control"] == "no-store"


def test_pixel_and_received_byte_limits_before_ocr(monkeypatch):
    import app.ocr as module
    import app.main as main
    monkeypatch.setattr(module, "MAX_IMAGE_PIXELS", 10)
    client = TestClient(create_app(ocr_factory=must_not_analyze))
    assert client.post("/api/v1/ocr", content=picture(size=(4, 3)), headers={"Content-Type": "image/png"}).json()["error"]["code"] == "IMAGE_TOO_LARGE"
    monkeypatch.setattr(main, "MAX_IMAGE_BYTES", 50)
    assert client.post("/api/v1/ocr", content=picture(), headers={"Content-Type": "image/png"}).status_code == 413
    # Content-Length이 없거나 거짓이어도 수신 크기로 검사한다.
    assert client.post("/api/v1/ocr", content=iter([b"a" * 30, b"b" * 30]), headers={"Content-Type": "image/png"}).status_code == 413


def test_rotation_metadata_removal_and_animation_rejection():
    with Image.new("RGB", (80, 40), "white") as image, io.BytesIO() as source:
        exif = Image.Exif(); exif[274] = 6; exif[315] = "SECRET AUTHOR"
        image.save(source, format="JPEG", exif=exif)
        cleaned = prepare_image(source.getvalue(), "image/jpeg")
    with Image.open(io.BytesIO(cleaned)) as decoded:
        assert decoded.size == (40, 80) and not decoded.getexif()
        assert "SECRET AUTHOR".encode() not in cleaned
    with Image.new("RGB", (2, 2), "white") as one, Image.new("RGB", (2, 2), "black") as two, io.BytesIO() as stream:
        one.save(stream, format="PNG", save_all=True, append_images=[two])
        with pytest.raises(OcrError) as error:
            prepare_image(stream.getvalue(), "image/png")
        assert error.value.code == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.parametrize("value,code,status", [("", "OCR_NO_TEXT", 422), (" \n", "OCR_NO_TEXT", 422), ("가" * 10001, "OCR_TEXT_TOO_LONG", 422), (OcrError("OCR_UNAVAILABLE"), "OCR_UNAVAILABLE", 503), (RuntimeError("SECRET OCR output"), "OCR_FAILED", 503)])
def test_empty_long_unavailable_failed_are_distinct(value, code, status, caplog):
    class Engine:
        async def extract(self, image):
            if isinstance(value, Exception): raise value
            return value
    client = TestClient(create_app(ocr_factory=Engine))
    response = client.post("/api/v1/ocr", content=picture(), headers={"Content-Type": "image/png"})
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert "SECRET" not in response.text + caplog.text


def test_timeout_cancels_engine_and_releases_slot():
    cleaned = []
    class Slow:
        async def extract(self, image):
            try: await asyncio.sleep(5)
            finally: cleaned.append(True)
    client = TestClient(create_app(ocr_factory=Slow, ocr_timeout=0.01))
    for _ in range(2):
        response = client.post("/api/v1/ocr", content=picture(), headers={"Content-Type": "image/png"})
        assert response.status_code == 504 and response.json()["error"]["code"] == "OCR_TIMEOUT"
    assert cleaned == [True, True]


def test_concurrent_ocr_rejected_and_cancel_does_not_block_next_request():
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        class Engine:
            async def extract(self, image):
                started.set(); await finish.wait(); return "확인할 문자"
        app = create_app(ocr_factory=Engine)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            kwargs = {"content": picture(), "headers": {"Content-Type": "image/png"}}
            pending = asyncio.create_task(client.post("/api/v1/ocr", **kwargs))
            await started.wait()
            assert (await client.post("/api/v1/ocr", **kwargs)).status_code == 429
            pending.cancel()
            with pytest.raises(asyncio.CancelledError): await pending
            finish.set()
            assert (await client.post("/api/v1/ocr", **kwargs)).status_code == 200
    asyncio.run(run())


@pytest.mark.parametrize("confirmation", [None, False, 1, "true"])
def test_analysis_rejects_unconfirmed_ocr(confirmation):
    client = TestClient(create_app(analyzer_factory=must_not_analyze))
    body = {"input_type": "ocr_text", "content": "인증번호를 알려주세요."}
    if confirmation is not None: body["ocr_confirmed"] = confirmation
    assert client.post("/api/v1/analyses", json=body).status_code == 422


def test_explicitly_confirmed_edited_text_uses_existing_analyzer():
    client = TestClient(create_app())
    text = "😀 은행입니다. 인증번호를 알려주세요. https://example.invalid/"
    result = client.post("/api/v1/analyses", json={"input_type": "ocr_text", "content": text, "ocr_confirmed": True}).json()
    assert result["risk_level"] == "dangerous" and result["confidence"] is None
    assert result["urls"][0]["reputation"]["status"] == "not_connected"
    for evidence in result["evidence"]: assert text[evidence["start"]:evidence["end"]] == evidence["snippet"]


def test_ocr_too_many_urls_preserves_full_text_for_editing():
    text = " ".join(f"https://e.invalid/{i}" for i in range(11))
    class Engine:
        async def extract(self, image): return text
    client = TestClient(create_app(ocr_factory=Engine))
    response = client.post("/api/v1/ocr", content=picture(), headers={"Content-Type": "image/png"}).json()
    assert response["text"] == text and response["urls"] == []
    assert any("10개" in warning for warning in response["warnings"])
    assert client.post("/api/v1/ocr/review", json={"content": text}).status_code == 422
    assert client.post("/api/v1/ocr/review", json={"content": ""}).json()["urls"] == []


def test_tesseract_pipes_no_files_and_cleanup_on_cancellation(monkeypatch, tmp_path):
    calls = []
    class Process:
        returncode = None
        killed = False
        async def communicate(self, data=None):
            if self.killed: self.returncode = -9; return b"", b""
            await asyncio.sleep(5)
        def kill(self): self.killed = True
    process = Process()
    async def spawn(*args, **kwargs): calls.append((args, kwargs)); return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.chdir(tmp_path)
    engine = TesseractOcr(); engine.command = "test-only"
    async def run():
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01): await engine.extract(b"PNG")
    asyncio.run(run())
    assert process.killed and process.returncode == -9
    assert calls[0][0][1:3] == ("stdin", "stdout")
    assert list(tmp_path.iterdir()) == []


def test_missing_korean_data_never_silently_falls_back_to_english(monkeypatch):
    class Process:
        returncode = 0
        async def communicate(self, data): return b"Only English", b"Failed loading language 'kor'"
    async def spawn(*args, **kwargs): return Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    engine = TesseractOcr(); engine.command = "test-only"
    with pytest.raises(OcrError) as error: asyncio.run(engine.extract(b"PNG"))
    assert error.value.code == "OCR_UNAVAILABLE"


def test_http_disconnect_cancels_and_drains_engine():
    cleaned = []
    async def run():
        started = asyncio.Event()
        class Engine:
            async def extract(self, image):
                try: started.set(); await asyncio.sleep(5)
                finally: cleaned.append(True)
        async def disconnected():
            await started.wait()
            return True
        with pytest.raises(OcrError) as error:
            await extract_until_disconnect(Engine(), b"PNG", disconnected)
        assert error.value.code == "OCR_CANCELLED"
    asyncio.run(run())
    assert cleaned == [True]


def test_disconnect_checker_that_swallows_cancel_does_not_leave_a_watcher():
    async def run():
        class Engine:
            async def extract(self, image):
                await asyncio.sleep(0.01)
                return "확인할 문자"
        async def disconnected():
            try: await asyncio.sleep(5)
            except asyncio.CancelledError: return False
            return False
        result = await asyncio.wait_for(extract_until_disconnect(Engine(), b"PNG", disconnected), 1)
        assert result == "확인할 문자"
    asyncio.run(run())
