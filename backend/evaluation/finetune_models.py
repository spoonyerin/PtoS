"""사전학습 인코더 미세조정(파인튜닝) 후보 (비교와 학습용, 선택 사항, 2026-11-24).

- 저장소 밖 로컬 폴더의 모델만 읽는다(local_files_only). 네트워크로 내려받지 않는다.
- 학습: 학습 전용 세트(finetune-*-train)만. 조기 종료·최고 시점 선택은 같은 세트의 -val만 쓴다(dev·test 미사용).
- CPU 학습 기준 기본값(성능 근거로 고른 값 아님): 최대 128토큰, 배치 16, 2 epoch, AdamW, 선형 감소 + 6% warmup.
- fit_with_validation / predict_proba / classes_를 가져 external_training.run_candidate가 그대로 쓴다.
- 로그에는 단계·시간·검증 점수만 쓴다. 원문은 쓰지 않는다.
"""

import copy
import math
import random
import time
from pathlib import Path


from app.transformer_model import KoBertTokenizer  # noqa: E402  학습과 서버가 같은 토크나이저를 쓴다


class FineTunedClassifier:
    classes_ = [0, 1]

    def __init__(self, model_dir: Path, seed: int, prefix: str = "", max_length: int = 128, epochs: int = 2,
                 batch_size: int = 16, lr: float = 5e-5, eval_every: int = 300, patience: int = 3,
                 tokenizer_factory=None, log=print):
        self.model_dir, self.seed, self.prefix = Path(model_dir), seed, prefix
        self.max_length, self.epochs, self.batch_size, self.lr = max_length, epochs, batch_size, lr
        self.eval_every, self.patience, self.log = eval_every, patience, log
        self._tokenizer_factory = tokenizer_factory
        self.history: list[dict] = []
        self._model = self._tokenizer = None

    # -- 준비 --
    def _load(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.manual_seed(self.seed)
        if self._tokenizer_factory is not None:
            self._tokenizer = self._tokenizer_factory(self.model_dir)
        else:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_dir, local_files_only=True)
        safetensors = (self.model_dir / "model.safetensors").is_file()
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_dir, num_labels=2, local_files_only=True, use_safetensors=safetensors)

    def _batch(self, texts: list[str]):
        return self._tokenizer([self.prefix + t for t in texts], padding=True, truncation=True,
                               max_length=self.max_length, return_tensors="pt")

    # -- 학습 --
    def fit_with_validation(self, texts, labels, val_texts, val_labels):
        import torch
        from sklearn.metrics import roc_auc_score
        from transformers import get_linear_schedule_with_warmup

        self._load()
        model = self._model
        order = list(range(len(texts)))
        rng = random.Random(self.seed)
        steps_per_epoch = math.ceil(len(texts) / self.batch_size)
        total = steps_per_epoch * self.epochs
        no_decay = ("bias", "LayerNorm.weight", "layer_norm.weight")
        groups = [
            {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": 0.01},
            {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
        ]
        optimizer = torch.optim.AdamW(groups, lr=self.lr)
        scheduler = get_linear_schedule_with_warmup(optimizer, int(total * 0.06), total)
        best_auc, best_state, bad, step, started = -1.0, None, 0, 0, time.perf_counter()

        def evaluate() -> bool:
            nonlocal best_auc, best_state, bad
            auc = float(roc_auc_score(val_labels, self._scores(val_texts)))
            model.train()
            self.history.append({"step": step, "val_auc": round(auc, 5), "minutes": round((time.perf_counter() - started) / 60, 1)})
            self.log(f"  step {step}/{total} val AUC {auc:.4f} ({self.history[-1]['minutes']}분)")
            if auc > best_auc:
                best_auc, best_state, bad = auc, copy.deepcopy(model.state_dict()), 0
            else:
                bad += 1
            return bad >= self.patience

        model.train()
        stop = False
        for _ in range(self.epochs):
            rng.shuffle(order)
            for start in range(0, len(order), self.batch_size):
                idx = order[start:start + self.batch_size]
                batch = self._batch([texts[i] for i in idx])
                out = model(**batch, labels=torch.tensor([labels[i] for i in idx]))
                out.loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                step += 1
                if step % 50 == 0:
                    self.log(f"  step {step}/{total} loss {out.loss.item():.4f} ({(time.perf_counter() - started) / 60:.1f}분)")
                if step % self.eval_every == 0 and evaluate():
                    stop = True
                    break
            if stop:
                break
        if not stop and (not self.history or self.history[-1]["step"] != step):
            evaluate()
        model.load_state_dict(best_state)
        model.eval()
        self.best_val_auc = best_auc
        return self

    def fit(self, texts, labels):
        raise TypeError("파인튜닝 후보는 검증 세트가 필요해요 (--val).")

    # -- 추론 --
    def _scores(self, texts: list[str], batch_size: int = 64) -> list[float]:
        import torch

        self._model.eval()
        # 길이로 정렬해 묶으면 패딩이 줄어 빠르다. 결과는 원래 순서로 돌려준다.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = [0.0] * len(texts)
        with torch.no_grad():
            for start in range(0, len(order), batch_size):
                idx = order[start:start + batch_size]
                logits = self._model(**self._batch([texts[i] for i in idx])).logits
                for i, p in zip(idx, torch.softmax(logits, dim=-1)[:, 1].tolist()):
                    out[i] = float(p)
        return out

    def predict_proba(self, texts):
        return [[1.0 - s, s] for s in self._scores(list(texts))]

    def save(self, target: Path) -> dict:
        target.mkdir(parents=True, exist_ok=True)
        self._model.save_pretrained(target, safe_serialization=True)
        self._tokenizer.save_pretrained(target)
        return {"model_dir": target.name, "history": self.history, "best_val_auc": self.best_val_auc,
                "settings": {"max_length": self.max_length, "epochs": self.epochs, "batch_size": self.batch_size,
                             "lr": self.lr, "prefix": self.prefix, "eval_every": self.eval_every,
                             "patience": self.patience}}
