"""분석기 경계. 규칙(평판 포함)과 문장 전체 점수 모델은 CompositeAnalyzer에서 종합한다."""

import asyncio
from typing import Protocol

from .contracts import AnalysisInput, AnalysisResult, AnalysisStage, InputAssessment, UrlFinding, UrlOccurrence, UrlReputation
from .rule_detection import RuleScan, scan_rules
from .rule_policy import decide
from .rule_templates import render
from .reputation_policy import combine_reputation
from .urls import extract_urls
from .model_adapter import ModelState, prepare_model_text
from .model_policy import BASE_LIMITATION, MODEL_LIMITATIONS, STAGE_STATUS, ModelOutcome, combine_model
from .url_reputation import configured_reputation_provider, UrlReputationProvider


RULES_ONLY_LIMITATION = "규칙 기반 개발 버전: 경량 모델의 문맥 분석은 아직 없어요. 결과는 안전을 보장하지 않아요."


class Analyzer(Protocol):
    async def analyze(self, data: AnalysisInput) -> AnalysisResult: ...


class RuleBasedAnalyzer:
    def __init__(self, reputation_provider: UrlReputationProvider | None = None):
        self.reputation_provider = reputation_provider if reputation_provider is not None else configured_reputation_provider()

    async def analyze(self, data: AnalysisInput) -> AnalysisResult:
        extraction = extract_urls(data.content, direct=data.input_type == "url")
        async def lookup(record):
            return await self.reputation_provider.lookup(record.value) if record.value else UrlReputation(status="not_requested")

        # The provider includes queue wait in its deadline. One slow URL must
        # not multiply the analysis deadline and erase already found text rules.
        reputations = await asyncio.gather(*(lookup(record) for record in extraction.records))
        urls = []
        for record, reputation in zip(extraction.records, reputations):
            urls.append(UrlFinding(
                original_url=record.original_url,
                normalized_url=record.value.normalized_url if record.value else None,
                ascii_host=record.value.ascii_host if record.value else None,
                validation_status="valid" if record.value else "invalid",
                validation_message=record.error or "HTTP(S) 주소 형식만 확인했어요. 실제 존재 여부나 안전 여부를 확인한 것은 아니에요.",
                warnings=record.warnings,
                occurrences=[UrlOccurrence(text=o.text, start=o.start, end=o.end) for o in record.occurrences],
                reputation=reputation,
            ))
        if data.input_type == "url":
            scan = RuleScan([], True, InputAssessment(status="url_only", reasons=["URL만으로는 문자의 발신자·요구 행동을 확인할 수 없어요."]))
        else:
            scan = scan_rules(data.content, url_spans=extraction.spans)
        level, reason = decide(scan)
        explanation, actions = render(scan, level)
        evidence = [finding.evidence for finding in scan.findings]
        level, reason, explanation, actions, evidence = combine_reputation(level, reason, explanation, actions, evidence, urls)
        limitations = [
            RULES_ONLY_LIMITATION,
            "부정·인용·대화 주체를 처리하는 규칙은 제한적이며 우회 표현을 놓치거나 잘못 경고할 수 있어요.",
            *scan.assessment.reasons,
        ]
        valid_urls = [url for url in urls if url.validation_status == "valid"]
        if not valid_urls:
            reputation_stage = "not_applicable"
            if urls:
                limitations.append("형식 확인이 필요한 URL 후보는 평판 조회 대상으로 전달하지 않았어요.")
        elif all(url.reputation.status == "not_connected" for url in valid_urls):
            reputation_stage = "not_connected"
            limitations.append("URL의 형식과 평판은 별개예요. 평판 조회는 미연결이며 주소를 열거나 외부로 조회하지 않았어요.")
        elif any(url.reputation.status in {"unavailable", "timeout", "auth_error", "rate_limited", "not_connected"} for url in valid_urls):
            reputation_stage = "unavailable"
            limitations.append("평판 조회를 완료하지 못한 주소가 있어요. 규칙 결과를 안전 보증으로 사용하지 마세요.")
        else:
            reputation_stage = "completed"
            limitations.append("평판 결과 없음은 안전 판정이 아니며, 위협 목록 일치도 문자의 발신자나 사기를 확정하지 않아요. 문자 규칙의 근거는 함께 유지해요.")
        if any(url.reputation.status == "unknown" for url in valid_urls):
            limitations.append("전체 해시와 유효한 위협 유형이 일치하는 자료를 확인하지 못했어요. 미등록·새로운 위협을 놓칠 수 있어요.")
        return AnalysisResult(
            risk_level=level, confidence=None,
            risk_factors=list(dict.fromkeys(item.label for item in evidence)),
            explanation=explanation, action_guidance=actions,
            limitations=limitations, analysis_version="rules-reputation-dev-v2",
            evidence=evidence, input_assessment=scan.assessment,
            analysis_stages=[
                AnalysisStage(name="rules", status="completed"),
                AnalysisStage(name="lightweight_model", status="not_implemented"),
                AnalysisStage(name="url_reputation", status=reputation_stage),
            ],
            policy_reason=reason, urls=urls,
        )


class CompositeAnalyzer:
    """규칙과 모델을 둘 다 실행하고 종합한다. 규칙 결과로 모델을 생략하지 않는다 (short-circuit 금지).

    모델 단계가 없거나 실패하면 규칙 결과와 근거를 그대로 두고 analysis_stages와 limitations에만 표시한다.
    """

    VERSION = "rules-model-dev-v1"

    def __init__(self, rules: RuleBasedAnalyzer, model_state: ModelState, model_timeout: float = 1.0):
        self.rules = rules
        self.model_state = model_state
        self.model_timeout = model_timeout

    async def _model_outcome(self, data: AnalysisInput) -> ModelOutcome:
        if data.input_type == "url":
            return "not_applicable"
        if self.model_state.status != "loaded" or self.model_state.model is None:
            return self.model_state.status
        model = self.model_state.model
        text = prepare_model_text(data.content, extract_urls(data.content).spans)
        try:
            # CPU 추론은 스레드에서 돌린다. 시간 초과 시 스레드는 끝까지 돌지만 결과는 버린다.
            async with asyncio.timeout(self.model_timeout):
                score = await asyncio.to_thread(model.score, text)
        except TimeoutError:
            return "timeout"
        except Exception:
            # 예외 문자열에 입력이 섞일 수 있어 기록하지 않는다.
            return "error"
        return "flagged" if score >= model.threshold else "not_flagged"

    async def analyze(self, data: AnalysisInput) -> AnalysisResult:
        result, outcome = await asyncio.gather(self.rules.analyze(data), self._model_outcome(data))
        level, reason, explanation = combine_model(result.risk_level, result.policy_reason, result.explanation, outcome)
        limitations = [BASE_LIMITATION, MODEL_LIMITATIONS[outcome], *(text for text in result.limitations if text != RULES_ONLY_LIMITATION)]
        stages = [stage if stage.name != "lightweight_model" else AnalysisStage(name="lightweight_model", status=STAGE_STATUS[outcome])
                  for stage in result.analysis_stages]
        return result.model_copy(update={
            "risk_level": level, "policy_reason": reason, "explanation": explanation,
            "limitations": limitations, "analysis_version": self.VERSION, "analysis_stages": stages,
        })
