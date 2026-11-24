"""로컬 폴더의 사전학습 인코더로 문장 임베딩을 만든다 (선택 기능).

- torch·transformers는 기본 의존성이 아니다(backend/requirements-embedding.txt). 없으면 임베딩 모델만 쓸 수 없고 규칙 결과는 그대로다.
- 모델은 미리 내려받아 둔 로컬 폴더에서만 읽는다(local_files_only). 이 코드는 네트워크로 내려받지 않는다.
- 인코더 가중치는 고정이다. 문장을 벡터로만 바꾸고, 판단은 그 위에 따로 학습한 분류기가 한다.
"""

from collections.abc import Callable
from pathlib import Path

Encoder = Callable[[list[str]], list[list[float]]]
# 가중치 파일 후보. safetensors를 먼저 쓴다(pickle 형식인 .bin은 safetensors가 없을 때만).
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
DEFAULT_MAX_LENGTH = 256


class EncoderUnavailable(RuntimeError):
    """인코더를 준비하지 못함. 메시지에 경로를 넣지 않는다."""


def weights_file(model_dir: Path) -> Path:
    for name in WEIGHT_FILES:
        if (model_dir / name).is_file():
            return model_dir / name
    raise EncoderUnavailable("임베딩 모델 폴더에서 가중치 파일을 찾지 못했어요.")


def local_transformer_encoder(model_dir: Path, prefix: str = "", batch_size: int = 16,
                              max_length: int = DEFAULT_MAX_LENGTH) -> Encoder:
    """평균 풀링 + L2 정규화 임베딩. prefix는 모델이 요구할 때만 쓴다(예: "query: ")."""
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError:
        raise EncoderUnavailable("torch와 transformers가 설치된 환경에서만 임베딩 모델을 쓸 수 있어요.") from None
    if not model_dir.is_dir():
        raise EncoderUnavailable("임베딩 모델 폴더를 찾지 못했어요. 먼저 내려받아 둔 로컬 폴더를 지정해주세요.")
    use_safetensors = weights_file(model_dir).suffix == ".safetensors"
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        model = AutoModel.from_pretrained(model_dir, local_files_only=True, use_safetensors=use_safetensors)
    except Exception:
        # 예외 문자열에 경로가 들어가므로 넘기지 않는다.
        raise EncoderUnavailable("임베딩 모델을 불러오지 못했어요.") from None
    model.eval()

    def encode(texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = tokenizer([prefix + text for text in texts[start:start + batch_size]], padding=True,
                                  truncation=True, max_length=max_length, return_tensors="pt")
                hidden = model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
                vectors.extend(torch.nn.functional.normalize(pooled, dim=1).tolist())
        return vectors

    return encode


class EncodedClassifier:
    """인코더 + 분류기를 predict_proba / classes_를 가진 하나의 파이프라인처럼 쓴다."""

    def __init__(self, classifier, encode: Encoder):
        self._classifier, self._encode = classifier, encode

    @property
    def classes_(self):
        return self._classifier.classes_

    def predict_proba(self, texts):
        return self._classifier.predict_proba(self._encode(list(texts)))
