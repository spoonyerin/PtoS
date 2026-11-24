"""사전학습 문장 임베딩(고정) + 로지스틱 회귀 후보 (비교와 학습용, 선택 사항).

- 임베딩 모델은 학습하지 않고(가중치 고정) 문장을 벡터로만 바꾼다. 그 위의 로지스틱 회귀만 dev 학습 행으로 학습한다.
- 인코더는 app/embedding_encoder.py의 것을 그대로 쓴다. 학습과 서버 추론이 같은 함수를 쓴다.
- 자동 테스트는 가짜 인코더로 연결 방식만 확인한다. 실제 인코더 테스트는 선택 실행이다.
"""

from pathlib import Path

from app.embedding_encoder import DEFAULT_MAX_LENGTH, EncodedClassifier, Encoder, local_transformer_encoder, weights_file
from app.model_adapter import file_sha256

DEFAULT_C = 1.0


class EmbeddingClassifier:
    """fit / predict_proba / classes_를 가진 후보. cross_validate와 score_texts가 그대로 쓴다."""

    def __init__(self, encode: Encoder, seed: int, C: float = DEFAULT_C):
        from sklearn.linear_model import LogisticRegression
        self._encode = encode
        self._clf = LogisticRegression(C=C, class_weight="balanced", max_iter=1000, random_state=seed)

    @property
    def classes_(self):
        return self._clf.classes_

    def fit(self, texts, labels):
        self._clf.fit(self._encode(list(texts)), list(labels))
        return self

    def predict_proba(self, texts):
        return EncodedClassifier(self._clf, self._encode).predict_proba(texts)

    def export(self):
        """모델 파일에 저장할 것. 인코더는 저장하지 않고 분류기만 저장한다."""
        return self._clf


def cached(encode: Encoder) -> Encoder:
    """인코더는 고정이라 같은 문장의 벡터는 fold와 무관하게 같다. 한 번만 계산한다."""
    cache: dict[str, list[float]] = {}

    def wrapper(texts: list[str]) -> list[list[float]]:
        missing = [text for text in dict.fromkeys(texts) if text not in cache]
        if missing:
            cache.update(zip(missing, encode(missing)))
        return [cache[text] for text in texts]

    return wrapper


def embedding_candidate(name: str, encode: Encoder, description: str | None = None) -> dict:
    """compare(extra_candidates=...)와 train(config=..., pipeline_factory=...)에 넣을 후보 항목."""
    return {"description": description or f"고정 임베딩({name}) + 로지스틱 회귀",
            "config": {"embedding": name, "classifier": {"C": DEFAULT_C, "class_weight": "balanced"}},
            "factory": lambda config, seed: EmbeddingClassifier(encode, seed)}


def embedding_manifest(name: str, model_dir: Path, prefix: str, max_length: int = DEFAULT_MAX_LENGTH) -> dict:
    """서버 로더가 같은 인코더를 다시 만들 수 있도록 manifest에 적는 값. 가중치 파일의 SHA-256을 함께 적는다."""
    weights = weights_file(model_dir)
    return {"kind": "local-transformer-mean-pool", "name": name, "directory": str(model_dir.resolve()),
            "prefix": prefix, "max_length": max_length, "weights_file": weights.name,
            "weights_sha256": file_sha256(weights)}


__all__ = ["EmbeddingClassifier", "cached", "embedding_candidate", "embedding_manifest", "local_transformer_encoder"]
