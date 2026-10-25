"""파일·네트워크 I/O 없는 이미지 처리와 교체 가능한 OCR 경계."""

import asyncio
import io
import os
import shutil
import warnings
from pathlib import Path
from typing import Protocol
from collections.abc import Awaitable, Callable

from PIL import Image, ImageOps, UnidentifiedImageError

from .contracts import UrlPreview, UrlOccurrence
from .urls import extract_urls

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
OCR_ERRORS = {
    "IMAGE_TOO_LARGE": (413, "JPG·PNG 한 장을 10 MiB 이하·2,000만 화소 이하로 줄여주세요. 문자로 직접 입력할 수도 있어요."),
    "UNSUPPORTED_MEDIA_TYPE": (415, "실제 JPG 또는 PNG 이미지 한 장을 선택해주세요. 확장자만 바꾼 파일은 사용할 수 없어요."),
    "INVALID_IMAGE": (422, "이미지를 읽지 못했어요. JPG·PNG로 다시 저장해 올리거나 문자로 직접 입력해주세요."),
    "OCR_NO_TEXT": (422, "이미지에서 문자를 찾지 못했어요. 글자가 선명한 이미지를 다시 올리거나 직접 입력해주세요."),
    "OCR_TEXT_TOO_LONG": (422, "추출한 문자가 10,000자를 초과해 자르지 않았어요. 이미지 범위를 줄이거나 문자로 직접 입력해주세요."),
    "OCR_TIMEOUT": (504, "글자 읽기 시간이 초과됐어요. 더 작은 이미지를 다시 올리거나 문자로 직접 입력해주세요."),
    "OCR_UNAVAILABLE": (503, "한국어 OCR 실행 파일 또는 kor·eng 언어 데이터가 준비되지 않았어요. 설치 안내를 확인하거나 문자로 직접 입력해주세요."),
    "OCR_FAILED": (503, "OCR 처리에 실패했어요. 다른 이미지를 다시 올리거나 문자로 직접 입력해주세요."),
    "OCR_CANCELLED": (409, "이미지 읽기가 취소됐어요. 이미지를 다시 올리거나 문자로 직접 입력해주세요."),
}


class OcrError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)  # 원문·파일명·공급자의 stderr를 예외 문자열에 넣지 않는다.


class OcrEngine(Protocol):
    async def extract(self, image: bytes) -> str: ...


async def extract_until_disconnect(engine: OcrEngine, image: bytes, disconnected: Callable[[], Awaitable[bool]]) -> str:
    """HTTP 연결이 닫혀도 서버 작업이 남지 않도록 엔진 취소를 전파한다."""
    # Starlette의 disconnect 확인은 CancelScope를 사용하므로 취소 신호 외에도 종료 조건을 둔다.
    stopped = False
    async def watch():
        while not stopped and not await disconnected():
            await asyncio.sleep(0.1)
    task = asyncio.create_task(engine.extract(image))
    watcher = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        watcher.result()
        raise OcrError("OCR_CANCELLED")
    finally:
        stopped = True
        for pending in (task, watcher):
            if not pending.done(): pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


def prepare_image(data: bytes | bytearray, content_type: str) -> bytes:
    """헤더·실제 형식·전체 디코딩을 확인하고 EXIF 없는 PNG를 반환한다."""
    if len(data) > MAX_IMAGE_BYTES:
        raise OcrError("IMAGE_TOO_LARGE")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with io.BytesIO(data) as source:
                with Image.open(source) as image:
                    actual = {"JPEG": "image/jpeg", "PNG": "image/png"}.get(image.format)
                    if actual is None or actual != content_type:
                        raise OcrError("UNSUPPORTED_MEDIA_TYPE")
                    if image.width * image.height > MAX_IMAGE_PIXELS:
                        raise OcrError("IMAGE_TOO_LARGE")
                    if getattr(image, "n_frames", 1) != 1:
                        raise OcrError("UNSUPPORTED_MEDIA_TYPE")
                    image.verify()
                source.seek(0)
                with Image.open(source) as image:
                    image.load()  # 깨진/잘린 스트림을 수용하지 않는다.
                    with ImageOps.exif_transpose(image) as oriented:
                        with oriented.convert("RGB") as rgb:
                            rgb.info.clear()
                            with io.BytesIO() as output:
                                rgb.save(output, format="PNG")
                                return output.getvalue()
    except OcrError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise OcrError("IMAGE_TOO_LARGE") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise OcrError("INVALID_IMAGE") from None


def url_previews(text: str) -> list[UrlPreview]:
    return [UrlPreview(
        original_url=record.original_url,
        normalized_url=record.value.normalized_url if record.value else None,
        ascii_host=record.value.ascii_host if record.value else None,
        validation_status="valid" if record.value else "invalid",
        validation_message=record.error or "문자열 형식만 확인했어요. 주소를 열거나 평판을 조회하지 않았어요.",
        warnings=record.warnings,
        occurrences=[UrlOccurrence(text=o.text, start=o.start, end=o.end) for o in record.occurrences],
    ) for record in extract_urls(text).records]


class TesseractOcr:
    """CLI stdin/stdout만 사용한다. tempfile/pytesseract/외부 서비스는 사용하지 않는다."""
    def __init__(self):
        self.command = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
        local_data = Path(__file__).resolve().parents[2] / ".ocr" / "tessdata"
        self.data_dir = os.environ.get("TESSDATA_PREFIX") or (str(local_data) if local_data.is_dir() else None)

    async def extract(self, image: bytes) -> str:
        if not self.command:
            raise OcrError("OCR_UNAVAILABLE")
        args = [self.command, "stdin", "stdout", "-l", "kor+eng", "--psm", "6"]
        if self.data_dir:
            args += ["--tessdata-dir", self.data_dir]
        process = None
        try:
            process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"})
            output, stderr = await process.communicate(image)
            if b"Error opening data file" in stderr or b"Failed loading language" in stderr:
                raise OcrError("OCR_UNAVAILABLE")
            if process.returncode:
                code = "OCR_UNAVAILABLE" if b"traineddata" in stderr or b"loading language" in stderr else "OCR_FAILED"
                raise OcrError(code)
            return output.decode("utf-8").strip()
        except (FileNotFoundError, PermissionError):
            raise OcrError("OCR_UNAVAILABLE") from None
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.communicate()
