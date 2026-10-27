"""문장 전체 위험 점수 모델의 교체 가능한 경계와 로더. 서버 시작 시 한 번만 로드한다.

모델 파일은 저장소 밖 디렉터리(PTOS_MODEL_PATH)의 manifest.json과 그 안에 적힌 joblib 파일이다.
joblib(pickle)은 로드할 때 코드를 실행할 수 있으므로 SHA-256이 manifest와 같을 때만 연다.
로그와 실패 사유에는 경로·원문·예외 문자열을 넣지 않고 고정 코드만 쓴다.
"""

import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

logger = logging.getLogger(__name__)

MODEL_PATH_ENV = "PTOS_MODEL_PATH"
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = "ptos-text-model-v1"
URL_PLACEHOLDER = "<URL>"
REPO_ROOT = Path(__file__).resolve().parents[2]


class TextRiskModel(Protocol):
    """사기 문자와 비슷한 정도를 0~1 점수로 낸다. 점수는 안전 확률이 아니다."""

    version: str
    threshold: float

    def score(self, text: str) -> float: ...


@dataclass(frozen=True)
class ModelState:
    status: Literal["loaded", "not_configured", "load_failed"]
    model: TextRiskModel | None = None
    # 고정 코드만 담는다 (예: MANIFEST_MISSING). 경로나 예외 문자열을 넣지 않는다.
    reason: str | None = None


class ModelLoadError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def prepare_model_text(content: str, url_spans: list[tuple[int, int]]) -> str:
    """URL 구간(코드포인트 좌표)을 자리표시자로 바꾼다. 학습과 추론이 같은 함수를 쓴다."""
    chars = list(content)
    for start, end in sorted(url_spans, reverse=True):
        chars[start:end] = URL_PLACEHOLDER
    return "".join(chars)


def is_inside_repo(path: Path, repo: Path = REPO_ROOT) -> bool:
    # Windows는 대소문자를 구분하지 않으므로 normcase로 비교한다.
    target = os.path.normcase(str(path.resolve()))
    root = os.path.normcase(str(repo.resolve()))
    return target == root or target.startswith(root.rstrip(os.sep) + os.sep)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


class JoblibTextModel:
    """predict_proba와 classes_를 가진 학습 파이프라인(예: TF-IDF + 로지스틱 회귀)을 감싼다."""

    def __init__(self, pipeline, version: str, threshold: float):
        classes = list(getattr(pipeline, "classes_", []))
        if not hasattr(pipeline, "predict_proba") or 1 not in classes:
            raise ModelLoadError("MODEL_INTERFACE_INVALID")
        self._pipeline = pipeline
        self._positive = classes.index(1)
        self.version = version
        self.threshold = threshold

    def score(self, text: str) -> float:
        return float(self._pipeline.predict_proba([text])[0][self._positive])


def read_manifest(directory: Path) -> dict:
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ModelLoadError("MANIFEST_MISSING")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ModelLoadError("MANIFEST_INVALID") from None
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise ModelLoadError("MANIFEST_INVALID")
    model_file, version, sha = manifest.get("model_file"), manifest.get("model_version"), manifest.get("model_sha256")
    threshold = manifest.get("threshold")
    # 모델 파일은 manifest와 같은 디렉터리의 파일 이름만 허용한다.
    if (not isinstance(model_file, str) or not model_file or Path(model_file).name != model_file
            or not isinstance(version, str) or not version or not isinstance(sha, str)
            or isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0 <= threshold <= 1):
        raise ModelLoadError("MANIFEST_INVALID")
    return manifest


def load_model(directory: Path) -> TextRiskModel:
    if is_inside_repo(directory):
        raise ModelLoadError("MODEL_PATH_INSIDE_REPO")
    if not directory.is_dir():
        raise ModelLoadError("MODEL_PATH_NOT_DIRECTORY")
    manifest = read_manifest(directory)
    model_path = directory / manifest["model_file"]
    if not model_path.is_file() or is_inside_repo(model_path):
        raise ModelLoadError("MODEL_FILE_MISSING")
    if file_sha256(model_path) != manifest["model_sha256"].lower():
        raise ModelLoadError("MODEL_SHA256_MISMATCH")
    try:
        import joblib
        pipeline = joblib.load(model_path)
    except Exception:
        raise ModelLoadError("MODEL_LOAD_ERROR") from None
    return JoblibTextModel(pipeline, manifest["model_version"], float(manifest["threshold"]))


def load_configured_model(env: dict[str, str] | None = None) -> ModelState:
    value = (os.environ if env is None else env).get(MODEL_PATH_ENV, "").strip()
    if not value:
        return ModelState("not_configured")
    try:
        model = load_model(Path(value))
    except ModelLoadError as error:
        logger.warning("MODEL_LOAD_FAILED reason=%s", error.code)
        return ModelState("load_failed", reason=error.code)
    except Exception:
        logger.warning("MODEL_LOAD_FAILED reason=MODEL_LOAD_ERROR")
        return ModelState("load_failed", reason="MODEL_LOAD_ERROR")
    logger.info("MODEL_LOADED version=%s", model.version)
    return ModelState("loaded", model)
