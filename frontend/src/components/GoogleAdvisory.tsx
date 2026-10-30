import type { AnalysisResponse, UrlFinding } from '../api/types'

// Google Safe Browsing 이용 지침: Google 자료에서 나온 경고에만 이 표기와 Advisory 링크를 붙인다.
// 화면의 유일한 외부 링크이며 고정 주소다. 사용자 URL은 링크로 만들지 않는다.
export const GOOGLE_ADVISORY_URL = 'https://developers.google.com/safe-browsing/v4/advisory'
export const GOOGLE_PROVIDER = 'google_safe_browsing_v5'

export function isGoogleWarning(url: UrlFinding): boolean {
  return url.reputation.provider === GOOGLE_PROVIDER && url.reputation.status === 'malicious' && url.reputation.full_hash_verified
}

// URL 평판 근거 중 Google 경고가 있는 URL의 출현 위치와 같은 것만 Google 근거로 본다.
export function isGoogleEvidence(item: AnalysisResponse['evidence'][number], urls: UrlFinding[]): boolean {
  return item.source === 'url_reputation' && urls.some(url => isGoogleWarning(url)
    && url.occurrences.some(o => o.start === item.start && o.end === item.end))
}

export function GoogleAdvisory() {
  return <p className="hint google-advisory">
    <a href={GOOGLE_ADVISORY_URL} target="_blank" rel="noopener noreferrer">Advisory provided by Google</a> (Google 제공 경고)
  </p>
}
