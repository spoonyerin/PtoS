"""rules-dev-v3 임시 신호의 회귀 검증. 모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다."""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F

URL = "https://example.invalid/notice"


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def rules(result):
    return {e.rule_id for e in result.evidence}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


# --- 가족 사칭 (호칭 + 1인칭 / 휴대폰 사정) ---

@pytest.mark.parametrize("text,snippet", [
    ("엄마 나야. 휴대폰을 잃어버려서 친구 폰으로 연락해.", "엄마 나"),
    ("할머니, 저예요. 오늘 좀 바빠요.", "할머니, 저"),
    ("아버지 휴대폰이 고장 나서 새 번호로 연락드려요.", "아버지 휴대폰이 고장"),
])
def test_family_call_is_weak_identity_only(text, snippet):
    result = analyze(text)
    assert "impersonation-family-v1" in rules(result)
    assert any(e.snippet == snippet for e in result.evidence)
    assert result.risk_level == "insufficient_information"
    assert "가족" in result.explanation
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "우리 엄마는 요즘 텃밭을 가꾸세요.",
    "아빠가 어제 낚시를 다녀오셨어요.",
    "할머니 댁에 다음 주에 갈 예정이에요.",
])
def test_family_word_without_call_form_is_not_identity(text):
    assert "impersonation-family-v1" not in rules(analyze(text))


# --- 반말·의문형 금전 요구 ---

@pytest.mark.parametrize("text", [
    "30만 원만 보내줄 수 있어?",
    "상품권 좀 사 줄래?",
    "이체 좀 부탁해.",
    "카드값 결제가 밀렸는데 네가 좀 해 줄 수 있어?",
    "돈 좀 빌려주면 안 돼?",
    "수수료를 입금해 주실 수 있나요?",
])
def test_informal_or_question_money_request_is_suspicious(text):
    result = analyze(text)
    assert F.MONEY_REQUEST in {e.factor_code for e in result.evidence}
    assert result.risk_level == "suspicious"
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "내가 내일 돈 보내줄게.",
    "용돈은 이미 보냈어.",
    "결제가 완료되었습니다. 내역은 앱에서 확인해 주세요.",
    "돈을 보내줄 수 있어도 보내지 마세요.",
])
def test_promise_or_completed_payment_is_not_money_request(text):
    assert F.MONEY_REQUEST not in {e.factor_code for e in analyze(text).evidence}


# --- 대괄호 기관 머리말 ---

@pytest.mark.parametrize("text,snippet", [
    ("[가나은행] 고객님 계좌 이용 안내입니다.", "[가나은행]"),
    ("[Web발신]\n[다라카드] 이번 달 이용 내역을 보내드립니다.", "[다라카드]"),
    ("[Web발신] [마바도시가스공사] 점검 일정 안내입니다.", "[마바도시가스공사]"),
    ("[사아구청] 주민 설명회 안내입니다.", "[사아구청]"),
])
def test_header_is_weak_identity_and_raises_nothing_alone(text, snippet):
    result = analyze(text)
    assert "impersonation-header-v1" in rules(result)
    assert any(e.snippet == snippet for e in result.evidence)
    assert result.risk_level == "insufficient_information"
    assert "머리말" in result.explanation
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "[Web발신] 오늘 모임은 7시입니다.",
    "[광고] 봄맞이 신상품 출시!",
    "[안내] 도서관 휴관일입니다.",
    "[예약안내] 다음 주 화요일 방문 예약입니다.",
    "인증번호 [123456]을 화면에 입력해 주세요.",
])
def test_generic_or_inline_brackets_are_not_header_identity(text):
    assert "impersonation-header-v1" not in rules(analyze(text))


def test_header_does_not_count_as_identity_for_existing_combination():
    result = analyze("[가나은행] 수수료를 입금해주세요.")
    assert result.risk_level == "suspicious"
    assert result.policy_reason == "ACTIONABLE_SIGNAL"


# --- "확인" 계열 링크 요구 ---

@pytest.mark.parametrize("text,rule", [
    (f"확인: {URL}", "link_click-confirm-v1"),
    ("첨부한 링크의 내용을 확인 부탁드립니다.", "link_click-confirm-v1"),
    (f"자세한 내용은 확인하세요 ▶ {URL}", "link_click-confirm-v1"),
    (f"서류를 보완해 주세요. 확인 바랍니다. {URL}", "link_click-confirm-v1"),
    (f"상세 내역 확인 및 납부: {URL}", "link_click-guided-v1"),
    ("링크로 들어가서 배송지를 고쳐 주세요.", "link_click-guided-v1"),
    (f"이 링크 눌러 보고 알려 줘 {URL}", "link_click-guided-v1"),
    (f"여기 접속해서 신청 좀 부탁해. {URL}", "link_click-guided-v1"),
])
def test_confirm_style_link_request_is_suspicious(text, rule):
    result = analyze(text)
    assert rule in rules(result)
    assert result.risk_level == "suspicious"
    assert_spans(text, result)
    assert "링크" in result.explanation


def test_confirm_label_snippet_covers_label_and_url():
    text = f"확인: {URL}"
    result = analyze(text)
    assert [e.snippet for e in result.evidence if e.rule_id == "link_click-confirm-v1"] == [text]


@pytest.mark.parametrize("text", [
    "회의 자료 확인 바랍니다.",
    "인증번호를 확인하세요.",
    "앱에서 주문 내역을 확인해 주세요.",
    "링크를 확인하지 마세요.",
    "여기로 연락해 줘.",
    f"여기로 연락해 줘. {URL}",
])
def test_confirm_without_link_target_is_not_link_request(text):
    assert F.LINK_CLICK not in {e.factor_code for e in analyze(text).evidence}


@pytest.mark.parametrize("text", [
    "모르는 링크는 주의하세요.",
    "의심스러운 링크는 삭제하세요.",
    "출처가 불분명한 링크는 신고해 주세요.",
    "링크 클릭을 자제하시기 바랍니다.",
])
def test_link_avoidance_advice_is_not_link_request(text):
    assert F.LINK_CLICK not in {e.factor_code for e in analyze(text).evidence}


def test_proxy_verb_after_other_task_noun_is_not_money_request():
    assert F.MONEY_REQUEST not in {e.factor_code for e in analyze("결제 내역 확인 좀 해 주세요.").evidence}


def test_every_bracket_in_leading_header_run_is_checked():
    result = analyze("[가나카드][광고] 이번 주 혜택 안내입니다.")
    assert any(e.snippet == "[가나카드]" and e.rule_id == "impersonation-header-v1" for e in result.evidence)


def test_url_label_does_not_split_message_context():
    # "확인:" 같은 항목 이름 뒤에 주소만 있으면 화자 라벨로 보지 않는다.
    result = analyze(f"[가나카드] 대금이 연체되어 오늘 자정까지 미확인 시 이용이 정지됩니다.\n해제하기: {URL}")
    assert result.risk_level == "dangerous"


def test_speaker_label_followed_by_text_still_splits():
    result = analyze("A: 은행입니다.\nB: 인증번호를 알려주세요.")
    assert result.risk_level == "suspicious"


# --- 불이익·청구 ---

@pytest.mark.parametrize("text,snippet", [
    ("이번 달 요금이 미납되었습니다.", "미납"),
    ("범칙금 고지서가 도착했습니다.", "범칙금"),
    ("확인하지 않으면 계정이 정지될 예정입니다.", "정지"),
    ("미확인 시 자동 반송됩니다.", "시 자동 반송"),
    ("기한 내 납부하지 않으면 가산금이 발생합니다.", "가산금"),
])
def test_penalty_word_is_signal_without_raising_level(text, snippet):
    result = analyze(text)
    assert "urgency_threat-penalty-v1" in rules(result)
    assert any(e.snippet == snippet for e in result.evidence)
    assert result.risk_level == "insufficient_information"
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "예약이 취소되었습니다.",
    "카드 이용이 정지되지 않습니다.",
    "미납 금액이 아닙니다.",
    "주문 취소를 원하시면 고객센터로 연락 주세요.",
    "배송이 시작되었습니다.",
])
def test_completed_or_negated_state_is_not_penalty(text):
    assert "urgency_threat-penalty-v1" not in rules(analyze(text))


# --- 임박 기한 (Q3: 당일·금일·오늘·자정까지·24시간 이내·내일·익일·1일 남음) ---

@pytest.mark.parametrize("phrase", [
    "오늘 자정까지", "금일 18시까지", "당일 오후 6시부터", "내일까지", "익일 15시까지",
    "24시간 이내", "12시간 내", "1일 남았습니다", "자정까지", "오늘(5일) 24시 예정",
])
def test_imminent_deadline(phrase):
    assert "urgency_threat-deadline-v1" in rules(analyze(f"신청 마감은 {phrase}입니다."))


@pytest.mark.parametrize("phrase", [
    "48시간 이내", "3일 이내", "2일 남았습니다", "10/28까지", "08/16일자", "다음 달 5일까지", "오늘 14~16시 사이",
])
def test_relaxed_or_date_only_deadline_is_not_imminent(phrase):
    assert "urgency_threat-deadline-v1" not in rules(analyze(f"처리 기한은 {phrase}입니다."))


def test_bare_day_word_counts_only_with_penalty_in_same_clause():
    assert "urgency_threat-deadline-v1" in rules(analyze("관리비가 미납되어 익일 단수 조치 예정입니다."))
    assert "urgency_threat-deadline-v1" not in rules(analyze("오늘 배송 예정입니다."))


# --- 규칙 A: 명의(머리말 포함) + 불이익 + 링크 + 임박 기한 ---

NOTICE = "[가나카드] 이용 대금이 연체되어 {deadline} 미확인 시 카드 이용이 정지됩니다. 확인: " + URL


def test_rule_a_dangerous_with_imminent_deadline():
    text = NOTICE.format(deadline="오늘 자정까지")
    result = analyze(text)
    assert result.risk_level == "dangerous"
    assert result.policy_reason == "COMBINED_NOTICE_PENALTY_DEADLINE"
    assert {"impersonation-header-v1", "urgency_threat-penalty-v1", "urgency_threat-deadline-v1", "link_click-confirm-v1"} <= rules(result)
    assert_spans(text, result)
    assert result.confidence is None
    assert "사기 확정은 아니에요" in result.explanation


@pytest.mark.parametrize("deadline", ["", "3일 이내", "10/28까지", "48시간 이내"])
def test_rule_a_without_imminent_deadline_is_suspicious(deadline):
    result = analyze(NOTICE.format(deadline=deadline))
    assert result.risk_level == "suspicious"


def test_rule_a_requires_identity():
    result = analyze(f"이용 대금이 연체되어 오늘 자정까지 미확인 시 카드 이용이 정지됩니다. 확인: {URL}")
    assert result.risk_level == "suspicious"


def test_rule_a_requires_link_request():
    result = analyze("[가나카드] 이용 대금이 연체되어 오늘 자정까지 미확인 시 카드 이용이 정지됩니다.")
    assert result.risk_level == "insufficient_information"


# --- 규칙 B: 가족 호칭 + 금전 요구 + 링크 요구 ---

def test_rule_b_family_money_link_is_dangerous():
    text = f"엄마 나 휴대폰 잃어버렸어. 친구한테 돈 보낼 게 있는데 엄마가 좀 해 줄 수 있어? 여기 눌러서 같이 처리해 줘 {URL}"
    result = analyze(text)
    assert result.risk_level == "dangerous"
    assert result.policy_reason == "COMBINED_FAMILY_MONEY_LINK"
    assert_spans(text, result)


def test_rule_b_reply_only_is_not_dangerous_yet():
    # 답장 유도 신호는 아직 없다(문서화한 한계). 금전 요구만으로는 의심이다.
    result = analyze("엄마 나 폰 고장 났어. 50만 원만 보내줄 수 있어? 이 번호로 답장 줘.")
    assert result.risk_level == "suspicious"


def test_existing_explicit_family_identity_keeps_rule_one():
    result = analyze("엄마 나 딸이야. 돈을 보내줘.")
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"


# --- 정상 안내문 음성 사례 ---

@pytest.mark.parametrize("text", [
    f"[가나택배] 오늘 14~16시 사이 배송 예정입니다. 배송조회: {URL}",
    "[가나택배] 주문하신 물건을 경비실에 맡겨 두었어요.",
    f"[가나카드] 이번 달 주말 외식 10% 할인 혜택! 자세히 보기: {URL}",
    "[가나페이] 인증번호 [123456]를 3분 안에 입력하세요. 타인에게 절대 알려주지 마세요.",
    "[가나치과] 내일 오전 10시 진료 예약이 있습니다. 변경은 전화로 연락 주세요.",
    f"[가나호텔] 예약이 확정되었습니다. 예약 확인: {URL}",
    "엄마 나 오늘 저녁 먹고 들어갈게.",
    f"[가나통신] 이번 달 요금 명세서입니다. 납부 기한은 다음 달 5일까지입니다. 상세 내역: {URL}",
])
def test_ordinary_notices_are_never_dangerous(text):
    result = analyze(text)
    assert result.risk_level != "dangerous"
    assert result.risk_level != "normal"
    assert_spans(text, result)


def test_reservation_and_otp_notices_stay_insufficient():
    assert analyze("[가나치과] 내일 오전 10시 진료 예약이 있습니다. 변경은 전화로 연락 주세요.").risk_level == "insufficient_information"
    assert analyze("[가나택배] 주문하신 물건을 경비실에 맡겨 두었어요.").risk_level == "insufficient_information"


def test_templates_follow_only_found_signals():
    result = analyze("[가나은행] 고객님 계좌 이용 안내입니다.")
    assert "가족" not in result.explanation and "불이익" not in result.explanation
    assert "링크" not in result.explanation + " ".join(result.action_guidance)
