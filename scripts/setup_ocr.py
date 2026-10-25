"""Python 3: 공식 언어 데이터만 내려받는다. 이미지를 전송하지 않는다."""
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen

DATA = {
    "kor": "6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def main():
    destination = Path(__file__).resolve().parents[1] / ".ocr" / "tessdata"
    destination.mkdir(parents=True, exist_ok=True)
    for language, expected in DATA.items():
        target = destination / f"{language}.traineddata"
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            continue
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/{language}.traineddata"
        with urlopen(url, timeout=60) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit(f"{language}: SHA-256 불일치. 파일을 설치하지 않았습니다.")
        target.write_bytes(data)
    command = os.environ.get("TESSERACT_CMD", "tesseract")
    try:
        version = subprocess.run([command, "--version"], capture_output=True, check=True).stdout.decode(errors="replace")
        if not version.startswith(("tesseract 5.", "tesseract v5.")):
            raise SystemExit("Tesseract 5를 설치해주세요.")
        result = subprocess.run([command, "--tessdata-dir", str(destination), "--list-langs"], capture_output=True, check=True)
        if not {"kor", "eng"} <= set(result.stdout.decode().splitlines()):
            raise SystemExit("kor·eng 언어 데이터를 확인하지 못했습니다.")
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("Tesseract 5 설치와 TESSERACT_CMD를 확인해주세요. 언어 데이터는 준비되었습니다.") from None
    print("한국어 OCR 준비 완료: Tesseract 5, kor+eng, 실행 중 외부 전송 없음.")


if __name__ == "__main__":
    main()
