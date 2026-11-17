"""보낸 번호 비교(sender-check-dev-v1, 임시)의 회귀 검증. 이름과 번호는 모두 지어낸 것이다. 탐지 성능 검증이 아니다."""

import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput, RiskLevel
from app.main import create_app
from app.model_adapter import ModelState
from app.sender_check import (
    NO_CLAIM_LIMITATION, PATH_ENV, RULE_LIST, RULE_TYPE, SPOOF_LIMITATION, TYPE_ONLY_LIMITATION,
    load_official_numbers, normalize_number, parse_official_numbers, sender_type,
)

BANK = "[가상은행] 이번 달 이용 내역을 안내드립니다."
DELIVERY = "[가상택배] 주문하신 상품이 오늘 배송될 예정입니다."
DANGEROUS = "가상은행입니다. 인증번호를 알려주세요."
MOBILE = "010-0000-0000"
MAIN_LINE = "1500-0000"
OFFICIAL = parse_official_numbers({"organizations": [{"names": ["가상은행", "가상 뱅크"], "numbers": [MAIN_LINE, "02-000-0000"]}]})


class FakeModel:
    version = "fake-v1"
    threshold, normal_threshold = 0.7, 0.3

    def score(self, text):
        return 0.1


def analyze(text, sender=None, official=None, input_type="text"):
    data = AnalysisInput(input_type=input_type, content=text, sender_number=sender)
    return asyncio.run(RuleBasedAnalyzer(official_numbers=official).analyze(data))


def stage(result):
    return next(s.status for s in result.analysis_stages if s.name == "sender_check")


def sender_evidence(result):
    return [e for e in result.evidence if e.factor_code == "SENDER_MISMATCH"]


@pytest.mark.parametrize("raw,number,kind", [
    ("010-0000-0000", "01000000000", "mobile"),
    ("+82 10-0000-0000", "01000000000", "mobile"),
    ("+82 010 0000 0000", "01000000000", "mobile"),
    ("+1 555 000 0000", "+15550000000", "international"),
    ("006 1 555 000", "0061555000", "international"),
    ("1500-0000", "15000000", "other"),
    ("02-000-0000", "020000000", "other"),
])
def test_number_is_normalized_and_typed(raw, number, kind):
    assert (normalize_number(raw), sender_type(normalize_number(raw))) == (number, kind)


@pytest.mark.parametrize("text", [BANK, DANGEROUS, "도서관은 내일 휴무입니다."])
def test_without_a_number_nothing_changes_except_the_stage(text):
    result = analyze(text)
    assert stage(result) == "not_applicable" and not sender_evidence(result)
    assert SPOOF_LIMITATION not in result.limitations


@pytest.mark.parametrize("sender", [MOBILE, "+82 10-0000-0000", "+1 555 000 0000"])
def test_institution_name_with_a_personal_or_foreign_number_raises_to_suspicious(sender):
    before, result = analyze(BANK), analyze(BANK, sender)
    assert before.risk_level == RiskLevel.INSUFFICIENT_INFORMATION
    assert (result.risk_level, result.policy_reason, stage(result)) == (RiskLevel.SUSPICIOUS, "SENDER_MISMATCH", "completed")
    [item] = sender_evidence(result)
    # 번호는 원문에 없다. 근거 좌표는 문자 안의 기관 이름을 가리킨다.
    assert item.rule_id == RULE_TYPE and item.snippet == "[가상은행]" == BANK[item.start:item.end]
    assert result.evidence[:len(before.evidence)] == before.evidence
    assert {SPOOF_LIMITATION, TYPE_ONLY_LIMITATION} <= set(result.limitations)
    # 번호를 응답 문장에 되돌려 쓰지 않는다.
    dumped = result.model_dump_json()
    assert sender not in dumped and normalize_number(sender) not in dumped


def test_main_line_number_without_a_list_neither_raises_nor_lowers():
    before, result = analyze(BANK), analyze(BANK, MAIN_LINE)
    assert (result.risk_level, result.policy_reason, result.evidence) == (before.risk_level, before.policy_reason, before.evidence)
    assert stage(result) == "completed" and TYPE_ONLY_LIMITATION in result.limitations


def test_delivery_name_with_a_mobile_number_is_not_a_mismatch():
    result = analyze(DELIVERY, MOBILE)
    assert result.risk_level == RiskLevel.INSUFFICIENT_INFORMATION and not sender_evidence(result)


@pytest.mark.parametrize("text", ["엄마 나야. 폰이 고장났어.", "엄마 나 딸인데 지금 바빠?", "도서관은 내일 휴무입니다."])
def test_messages_without_an_institution_name_are_not_compared(text):
    before, result = analyze(text), analyze(text, MOBILE)
    assert (result.risk_level, result.evidence) == (before.risk_level, before.evidence)
    assert stage(result) == "not_applicable" and NO_CLAIM_LIMITATION in result.limitations


def test_mismatch_keeps_a_dangerous_result_and_adds_evidence():
    before, result = analyze(DANGEROUS), analyze(DANGEROUS, MOBILE)
    assert before.risk_level == RiskLevel.DANGEROUS
    assert (result.risk_level, result.policy_reason) == (before.risk_level, before.policy_reason)
    assert len(sender_evidence(result)) == 1 and result.explanation.startswith(before.explanation)


def test_listed_name_with_a_different_number_is_a_mismatch_even_for_a_main_line():
    result = analyze(BANK, "1500-9999", OFFICIAL)
    assert (result.risk_level, result.policy_reason) == (RiskLevel.SUSPICIOUS, "SENDER_MISMATCH")
    assert [e.rule_id for e in sender_evidence(result)] == [RULE_LIST]
    assert TYPE_ONLY_LIMITATION not in result.limitations


@pytest.mark.parametrize("sender", [MAIN_LINE, "1500 0000", "02-000-0000"])
def test_listed_number_never_lowers_or_clears_a_result(sender):
    for text in (BANK, DANGEROUS):
        before, result = analyze(text, official=OFFICIAL), analyze(text, sender, OFFICIAL)
        assert (result.risk_level, result.policy_reason, result.evidence) == (before.risk_level, before.policy_reason, before.evidence)
        assert stage(result) == "completed" and SPOOF_LIMITATION in result.limitations


def test_unlisted_name_falls_back_to_the_number_type():
    result = analyze("[다른은행] 이용 내역을 안내드립니다.", MOBILE, OFFICIAL)
    assert [e.rule_id for e in sender_evidence(result)] == [RULE_TYPE]


def test_url_input_ignores_the_number():
    result = analyze("https://example.com/a", MOBILE, input_type="url")
    assert stage(result) == "not_applicable" and not sender_evidence(result)


def test_mismatch_blocks_normal_and_a_match_does_not_grant_it():
    def composite(sender, official=None):
        analyzer = CompositeAnalyzer(RuleBasedAnalyzer(official_numbers=official), ModelState("loaded", FakeModel()))
        return asyncio.run(analyzer.analyze(AnalysisInput(input_type="text", content=BANK, sender_number=sender)))

    # 머리말뿐인 안내문은 번호 없이도 정상 후보다. 번호가 맞는다고 달라지지 않고, 불일치면 정상이 아니다.
    assert composite(None).risk_level == RiskLevel.NORMAL
    assert composite(MAIN_LINE, OFFICIAL).risk_level == composite(None).risk_level
    mismatch = composite(MOBILE)
    assert (mismatch.risk_level, mismatch.policy_reason) == (RiskLevel.SUSPICIOUS, "SENDER_MISMATCH")
    assert [s.name for s in mismatch.analysis_stages] == ["rules", "lightweight_model", "url_reputation", "sender_check", "llm_review"]


def test_number_is_not_sent_to_the_review_step():
    class Reviewer:
        seen: list[str] = []

        async def review(self, masked):
            self.seen.append(masked)
            from app.llm_review import LlmReview
            return LlmReview("completed", "no_clear_signs")

    text = "고객님 확인이 필요한 내용이 있어 연락드립니다."
    analyzer = CompositeAnalyzer(RuleBasedAnalyzer(), ModelState("not_configured"), llm=Reviewer(), llm_scope="any_sentence")
    asyncio.run(analyzer.analyze(AnalysisInput(input_type="text", content=text, sender_number=MOBILE)))
    assert Reviewer.seen and all("0000" not in sent for sent in Reviewer.seen)


@pytest.fixture
def client():
    with TestClient(create_app(model_loader=lambda: ModelState("not_configured"))) as client:
        yield client


def test_api_accepts_the_number_and_does_not_log_it(client, caplog):
    with caplog.at_level(logging.DEBUG):
        body = client.post("/api/v1/analyses", json={"input_type": "text", "content": BANK, "sender_number": MOBILE}).json()
    assert (body["risk_level"], body["policy_reason"]) == ("suspicious", "SENDER_MISMATCH")
    assert {"name": "sender_check", "status": "completed"} in body["analysis_stages"]
    assert MOBILE not in caplog.text and "01000000000" not in caplog.text


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_api_treats_a_blank_number_as_absent(client, blank):
    body = client.post("/api/v1/analyses", json={"input_type": "text", "content": BANK, "sender_number": blank}).json()
    assert body["risk_level"] == "insufficient_information"
    assert {"name": "sender_check", "status": "not_applicable"} in body["analysis_stages"]


@pytest.mark.parametrize("bad", ["전화번호 모름", "010-0000-0000 <b>", "12", "0" * 30, 1012345678])
def test_api_rejects_an_invalid_number_without_echoing_it(client, bad):
    response = client.post("/api/v1/analyses", json={"input_type": "text", "content": BANK, "sender_number": bad})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_SENDER_NUMBER"
    assert str(bad) not in response.text


def test_official_list_is_optional_and_a_bad_file_keeps_the_server_running(tmp_path):
    assert load_official_numbers({}) == (None, "off")
    assert load_official_numbers({PATH_ENV: str(tmp_path / "none.json")}) == (None, "file_missing")
    bad = tmp_path / "bad.json"
    for content in ("{", "[]", json.dumps({"organizations": [{"names": ["가"], "numbers": [MAIN_LINE]}]}),
                    json.dumps({"organizations": [{"names": ["가상은행"], "numbers": []}]}),
                    json.dumps({"organizations": ["가상은행"]})):
        bad.write_text(content, encoding="utf-8")
        assert load_official_numbers({PATH_ENV: str(bad)}) == (None, "invalid")
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"organizations": [{"names": ["가상은행"], "numbers": [MAIN_LINE]}]}), encoding="utf-8")
    numbers, state = load_official_numbers({PATH_ENV: str(good)})
    assert state == "loaded" and numbers.numbers_for("[가상 은행]") == frozenset({"15000000"})
    assert numbers.numbers_for("[다른은행]") is None


def test_app_reads_the_list_from_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "numbers.json"
    path.write_text(json.dumps({"organizations": [{"names": ["가상은행"], "numbers": [MAIN_LINE]}]}), encoding="utf-8")
    monkeypatch.setenv(PATH_ENV, str(path))
    with TestClient(create_app(model_loader=lambda: ModelState("not_configured"))) as client:
        body = client.post("/api/v1/analyses", json={"input_type": "text", "content": BANK, "sender_number": "1500-9999"}).json()
    assert [e["rule_id"] for e in body["evidence"] if e["factor_code"] == "SENDER_MISMATCH"] == [RULE_LIST]
