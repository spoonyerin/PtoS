import type { UrlFinding } from '../api/types'

const reputationLabels: Record<UrlFinding['reputation']['status'], string> = {
  not_connected: '평판 조회 미연결',
  not_requested: '평판 조회 안 함',
  malicious: '평판 자료에 위험 보고가 있어요',
  benign: '평판 자료에 위험 보고가 없어요 (안전 보장 아님)',
  unknown: '유효한 위협 목록 일치를 확인하지 못했어요 (안전 판정 아님)',
  unavailable: '평판 조회 장애',
  timeout: '평판 조회 시간 초과',
  auth_error: '평판 조회 인증 오류',
  rate_limited: '평판 조회 호출 제한',
}

export function UrlResults({ urls }: { urls: UrlFinding[] }) {
  return <section className="result-section" aria-labelledby="urls-title">
    <h3 id="urls-title">URL 형식 및 평판</h3>
    {!urls.length ? <p>이 입력에서 URL 후보를 찾지 못했어요.</p> : <ol>
      {urls.map((url, index) => <li key={index} style={{ overflowWrap: 'anywhere' }}>
        <p>{url.original_url}</p>
        <p><strong>{url.validation_status === 'valid' ? '형식 확인' : '형식 확인 필요'}</strong> · {reputationLabels[url.reputation.status]}</p>
        {url.reputation.reason === 'policy_pending' && <p>이용 조건 확인 전이라 외부 조회를 보류했어요.</p>}
        {url.reputation.reason === 'local_limit' && <p>개발용 로컬 호출 예산에 도달했어요. 안전 여부를 확인한 것이 아니에요.</p>}
        {url.reputation.reason === 'unsupported_details' && <p>현재 판정에 사용할 수 없는 위협 유형·속성이 포함되어 있어요.</p>}
        {url.reputation.provider === 'google_safe_browsing_v5' && <>
          <p>평판 조회 공급자: Google Safe Browsing</p>
          <p>목록에 없는 위험을 놓치거나 잘못 경고할 수 있어요. 안전을 보장하지 않아요.</p>
        </>}
        {url.reputation.full_hash_verified && <p>위협 목록의 전체 SHA-256 해시 일치를 확인했어요.</p>}
        {url.reputation.threat_types?.length ? <p>보고된 위협 유형: {url.reputation.threat_types.join(', ')}</p> : null}
        {url.reputation.checked_at && <p>자료 확인 시각: {url.reputation.checked_at}{url.reputation.cache_hit ? ' (캐시 사용)' : ''}</p>}
        <p>{url.validation_message}</p>
        {url.normalized_url && url.normalized_url !== url.original_url && <p>정규화 주소: {url.normalized_url}</p>}
        {url.ascii_host && <p>호스트 ASCII 표기: {url.ascii_host}</p>}
        {url.occurrences.length > 1 && <p>같은 주소가 {url.occurrences.length}회 등장했어요.</p>}
        {url.warnings.map(warning => <p key={warning}>{warning}</p>)}
      </li>)}
    </ol>}
  </section>
}
