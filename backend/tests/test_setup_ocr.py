"""실제 설치/다운로드 없이 Windows·Linux의 버전 출력 호환성을 검사한다."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("version,accepted", [
    ("tesseract 5.5.0\n leptonica-1.84.1", True),
    ("tesseract v5.5.3.20260724\r\n leptonica-1.86.0", True),
    ("tesseract v5.0.0-alpha", True),
    ("tesseract 4.1.1", False),
    ("tesseract v4.1.1", False),
    ("tesseract 6.0.0", False),
    ("another-tool 5.5.0", False),
])
def test_setup_version_outputs(version, accepted, monkeypatch, tmp_path, capsys):
    path = Path(__file__).resolve().parents[2] / "scripts" / "setup_ocr.py"
    spec = importlib.util.spec_from_file_location("setup_ocr_under_test", path)
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    setup.__file__ = str(tmp_path / "scripts" / "setup_ocr.py")
    data = b"test-only-language-data"
    setup.DATA = {key: hashlib.sha256(data).hexdigest() for key in ("kor", "eng")}
    destination = tmp_path / ".ocr" / "tessdata"
    destination.mkdir(parents=True)
    for key in setup.DATA: (destination / f"{key}.traineddata").write_bytes(data)
    def no_download(*args, **kwargs): raise AssertionError("No network for version tests")
    monkeypatch.setattr(setup, "urlopen", no_download)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        output = version if args[-1] == "--version" else "List of available languages (2):\nkor\neng\n"
        return subprocess.CompletedProcess(args, 0, stdout=output.encode(), stderr=b"")
    monkeypatch.setattr(setup.subprocess, "run", run)
    if accepted:
        setup.main()
        assert "한국어 OCR 준비 완료" in capsys.readouterr().out
        assert calls[-1][-1] == "--list-langs"
    else:
        with pytest.raises(SystemExit, match="Tesseract 5"): setup.main()
        assert len(calls) == 1
