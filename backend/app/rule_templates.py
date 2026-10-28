"""확인한 신호의 설명과 행동만 선택한다. 외부 사실이나 연락처를 생성하지 않는다."""

from .contracts import FactorCode as F, RiskLevel
from .rule_detection import RuleScan

TEMPLATES = {
    F.IMPERSONATION: ("기관이나 지인의 명의를 내세우는 표현이 있어요. 실제 신원이나 사칭 여부를 검증한 것은 아니에요.", "메시지의 연락처 대신, 직접 확인한 공식 연락처나 알고 있던 지인의 번호로 확인하세요."),
    F.MONEY_REQUEST: ("돈을 보내거나 결제하도록 요구하는 표현이 있어요.", "돈을 보내기 전에 상대방과 요청 목적을 별도로 확인하세요."),
    F.CREDENTIAL_REQUEST: ("인증번호나 개인정보를 전달·입력하도록 요구하는 표현이 있어요.", "인증번호나 개인정보를 알려주거나 입력하기 전에 요청 출처를 별도로 확인하세요."),
    F.LINK_CLICK: ("링크를 누르거나 접속하도록 요구하는 표현이 있어요. 이 요구만으로 링크의 악성 여부를 판단하지 않아요.", "메시지의 링크를 바로 누르지 말고, 직접 확인한 공식 홈페이지로 확인하세요."),
    F.APP_INSTALL: ("앱이나 프로그램을 설치·실행하도록 요구하는 표현이 있어요.", "안내받은 앱을 설치·실행하기 전에 요청한 곳과 앱의 출처를 별도로 확인하세요."),
    F.URGENCY_THREAT: ("빠른 처리를 재촉하거나 불이익을 언급하는 표현이 있어요.", "재촉하더라도 바로 따르지 말고 시간을 두고 요청 내용을 확인하세요."),
}
# 세부 규칙의 설명. 없으면 같은 코드의 기본 템플릿을 쓴다.
RULE_TEMPLATES = {
    "impersonation-header-v1": ("메시지 첫머리의 대괄호 안에 기관·업체 이름이 있어요. 머리말만으로 실제 발신자를 확인한 것은 아니에요.", "머리말의 이름만 믿지 말고, 직접 확인한 공식 연락처나 공식 앱으로 확인하세요."),
    "impersonation-family-v1": ("가족을 부르며 본인이라고 말하거나 휴대폰 사정을 설명하는 표현이 있어요. 실제로 가족이 보냈는지 확인한 것은 아니에요.", "답장하거나 돈을 보내기 전에, 알고 있던 가족의 번호로 직접 전화해 확인하세요."),
    "urgency_threat-penalty-v1": ("미납·정지·반송 같은 불이익이나 청구를 언급하는 표현이 있어요. 실제 청구나 처분이 있는지 확인한 것은 아니에요.", "메시지의 링크나 연락처 대신, 직접 확인한 공식 홈페이지나 연락처로 청구·처분 내용을 확인하세요."),
    "urgency_threat-deadline-v1": ("당일·24시간 이내처럼 짧은 처리 기한을 제시하는 표현이 있어요.", TEMPLATES[F.URGENCY_THREAT][1]),
    "link_click-guided-v1": ("링크나 주소를 가리키며 그곳에서 처리하도록 안내하는 표현이 있어요. 이 표현만으로 링크의 악성 여부를 판단하지 않아요.", TEMPLATES[F.LINK_CLICK][1]),
    "link_click-confirm-v1": ("주소를 보여주며 확인하도록 안내하는 표현이 있어요. 이 표현만으로 링크의 악성 여부를 판단하지 않아요.", TEMPLATES[F.LINK_CLICK][1]),
}
HEADINGS = {
    RiskLevel.DANGEROUS: "위험 신호가 함께 발견됐어요. 임시 규칙 정책에 따른 경고이며 사기 확정은 아니에요.",
    RiskLevel.SUSPICIOUS: "확인이 필요한 요구 표현을 발견했어요. 규칙만으로 전체 위험을 판단할 수는 없어요.",
    RiskLevel.INSUFFICIENT_INFORMATION: "현재 입력과 규칙만으로 판단하기 어려워요. 분석하지 못한 단계가 있어 정상으로 판단하지 않았어요.",
}


def render(scan: RuleScan, level: RiskLevel) -> tuple[str, list[str]]:
    keys = [f.evidence.rule_id if f.evidence.rule_id in RULE_TEMPLATES else f.evidence.factor_code for f in scan.findings]
    templates = [RULE_TEMPLATES.get(key) or TEMPLATES[key] for key in dict.fromkeys(keys)]
    explanation = " ".join([HEADINGS[level], *dict.fromkeys(template[0] for template in templates)])
    actions = list(dict.fromkeys(template[1] for template in templates))
    if not actions:
        actions = ["보낸 사람과 요구하는 행동, 앞뒤 내용을 확인해주세요.", "확실하지 않다면 직접 확인한 공식 연락처로 확인하세요."]
    return explanation, actions
