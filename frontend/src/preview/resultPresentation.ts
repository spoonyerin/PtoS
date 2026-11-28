// These describe signals supplied by the API, not additional classifications.
export const factorDisplay: Record<string, { icon: string; description: string }> = {
  IMPERSONATION: {
    icon: 'risk-impersonation',
    description:
      '기관이나 지인의 명의를 내세운 표현이 있어요. 실제 발신자인지는 공식 연락처로 확인하세요.',
  },
  MONEY_REQUEST: {
    icon: 'risk-money',
    description:
      '금전을 보내거나 지급하라는 요구가 있어요. 송금하기 전에 상대방을 직접 확인하세요.',
  },
  CREDENTIAL_REQUEST: {
    icon: 'risk-credentials',
    description:
      '인증번호나 개인정보를 전달·입력하라는 요구가 있어요. 요청 출처를 별도로 확인하세요.',
  },
  LINK_CLICK: {
    icon: 'risk-link',
    description:
      '링크를 누르거나 주소에 접속하라는 표현이 있어요. 주소를 열기 전에 공식 경로로 확인하세요.',
  },
  APP_INSTALL: {
    icon: 'risk-app',
    description:
      '앱이나 프로그램을 설치·실행하라는 요구가 있어요. 공식 배포처와 요청 출처를 확인하세요.',
  },
  URGENCY_THREAT: {
    icon: 'risk-urgency',
    description:
      '빠른 처리를 재촉하거나 불이익을 언급하는 표현이 있어요. 서두르지 말고 요청을 확인하세요.',
  },
  URL_REPUTATION_MATCH: {
    icon: 'risk-link',
    description:
      'URL의 전체 해시가 위협 목록과 일치했어요. 링크를 누르지 마세요.',
  },
}

export const resultDescriptions = {
  dangerous: ['이 메시지는 위험해 보여요.', '요청에 응하기 전에 확인하세요.'],
  suspicious: ['조금 수상한 부분이 있어요.', '직접 확인이 필요해요.'],
  normal: ['현재까지 위험한 요소가 보이지 않아요.', '개인정보를 요구하면 주의하세요.'],
  insufficient_information: ['정보가 부족해 판단하기 어려워요.', '요청 출처를 별도로 확인하세요.'],
}
