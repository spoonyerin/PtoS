"""RUN_REAL_OCR=1 때만 실제 OS Tesseract와 한국어 언어 데이터로 실행한다."""
import asyncio
import io
import os
from pathlib import Path

import pytest
from PIL import Image

from app.ocr import TesseractOcr, prepare_image, url_previews

pytestmark = pytest.mark.skipif(os.environ.get("RUN_REAL_OCR") != "1", reason="실제 OCR은 RUN_REAL_OCR=1로 별도 실행")


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_real_korean_image_without_fake_ocr(fmt, mime, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with Image.open(Path(__file__).parent / "fixtures" / "korean-message.png") as image, io.BytesIO() as source:
        image.save(source, format=fmt)
        prepared = prepare_image(source.getvalue(), mime)
    text = asyncio.run(TesseractOcr().extract(prepared))
    assert "은행 담당자입니다" in text and "인증번호를 알려주세요" in text
    assert url_previews(text)[0].original_url == "https://example.invalid/notice"
    assert list(tmp_path.iterdir()) == []
