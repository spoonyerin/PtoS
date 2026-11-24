"""미세조정(파인튜닝)한 문장 분류 모델을 서버에서 읽는다 (선택 기능, 2026-11-24).

- torch·transformers가 있을 때만 쓴다(backend/requirements-embedding.txt). 없으면 모델 로드 실패이고 규칙 결과는 그대로다.
- 모델 폴더(PTOS_MODEL_PATH) 안의 config.json·model.safetensors·토크나이저 파일만 읽는다. 내려받지 않는다(local_files_only).
  가중치는 safetensors만 허용한다(pickle 형식 .bin은 열지 않는다). 원격 코드는 실행하지 않는다.
- 토크나이저: "auto"(폴더의 토크나이저 파일) 또는 "kobert-sentencepiece"(skt/kobert-base-v1, [CLS] 문장 [SEP]).
- 학습(evaluation/finetune_models.py)과 서버가 같은 토크나이저·전처리를 쓴다.
"""

from pathlib import Path

TOKENIZER_KINDS = ("auto", "kobert-sentencepiece")


class TransformerUnavailable(RuntimeError):
    """모델을 준비하지 못함. 메시지에 경로를 넣지 않는다."""


class KoBertTokenizer:
    """skt/kobert-base-v1용 최소 토크나이저: sentencepiece 조각 id를 그대로 쓰고 [CLS] 문장 [SEP](BERT 형식)으로 만든다.

    원 저장소 설정은 XLNetTokenizer지만 XLNet 형식(끝에 <sep><cls>, 왼쪽 패딩)은 KoBERT 학습 형식과 다르다.
    특수 토큰 id: [UNK] 0, [PAD] 1, [CLS] 2, [SEP] 3.
    """

    PAD, CLS, SEP = 1, 2, 3

    def __init__(self, model_dir: Path):
        import sentencepiece

        self.model_dir = Path(model_dir)
        self._sp = sentencepiece.SentencePieceProcessor(model_file=str(self.model_dir / "spiece.model"))

    def __call__(self, texts, padding=True, truncation=True, max_length=128, return_tensors="pt"):
        import torch

        ids = [[self.CLS, *self._sp.encode(t)[:max_length - 2], self.SEP] for t in texts]
        width = max(len(x) for x in ids)
        input_ids = torch.full((len(ids), width), self.PAD, dtype=torch.long)
        mask = torch.zeros((len(ids), width), dtype=torch.long)
        for row, x in enumerate(ids):
            input_ids[row, :len(x)] = torch.tensor(x)
            mask[row, :len(x)] = 1
        return {"input_ids": input_ids, "attention_mask": mask, "token_type_ids": torch.zeros_like(input_ids)}

    def save_pretrained(self, target: Path):
        import shutil

        if (Path(target) / "spiece.model").resolve() != (self.model_dir / "spiece.model").resolve():
            shutil.copyfile(self.model_dir / "spiece.model", Path(target) / "spiece.model")


def load_tokenizer(model_dir: Path, kind: str):
    if kind == "kobert-sentencepiece":
        return KoBertTokenizer(model_dir)
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model_dir, local_files_only=True)


class SequenceClassifier:
    """predict_proba / classes_를 가진 파이프라인처럼 쓴다(JoblibTextModel이 감싼다)."""

    classes_ = [0, 1]

    def __init__(self, model_dir: Path, tokenizer_kind: str, prefix: str, max_length: int):
        try:
            import torch
            from transformers import AutoModelForSequenceClassification
        except ImportError:
            raise TransformerUnavailable("torch와 transformers가 필요해요.") from None
        try:
            self._tokenizer = load_tokenizer(model_dir, tokenizer_kind)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                model_dir, local_files_only=True, use_safetensors=True)
        except Exception:
            # 예외 문자열에 경로가 들어가므로 넘기지 않는다.
            raise TransformerUnavailable("모델을 불러오지 못했어요.") from None
        self._model.eval()
        self._torch, self._prefix, self._max_length = torch, prefix, max_length

    def predict_proba(self, texts):
        torch = self._torch
        batch = self._tokenizer([self._prefix + t for t in texts], padding=True, truncation=True,
                                max_length=self._max_length, return_tensors="pt")
        with torch.no_grad():
            probs = torch.softmax(self._model(**batch).logits, dim=-1)[:, 1].tolist()
        return [[1.0 - p, p] for p in probs]
