import { Icon } from './Icons'

export type FamilyPreviewState = 'free' | 'paid-connected' | 'paid-unlinked'
export const initialFamilyPreview: FamilyPreviewState = import.meta.env.DEV ? 'paid-connected' : 'free'

export function FamilyProtectionCard({ state, connectionSummary, onOpen }: { state: FamilyPreviewState; connectionSummary: string | null; onOpen: () => void }) {
  const locked = state === 'free'
  return <button type="button" className={`family-protection-card${locked ? ' is-locked' : ''}`}
    aria-label="가족 보호" aria-describedby="family-protection-state" onClick={onOpen}>
    <span className="family-card-top" aria-hidden="true">
      <span className="family-card-icon"><span className="family-people-glyph" />
        {locked && <span className="family-card-lock"><Icon name="lock" /></span>}
      </span>
      <Icon name="chevron" />
    </span>
    <strong>가족 보호</strong>
    {locked ? <small id="family-protection-state">프리미엄 이용권으로<br />사용할 수 있어요.</small>
      : connectionSummary ? <small id="family-protection-state" className="family-connected"><img className="family-connected-check" src="/assets/icon-check.svg" alt="" />{connectionSummary}</small>
      : <small id="family-protection-state">가족 및 보호자를 연결해<br />주세요!</small>}
  </button>
}

// Mock subscription state is confined to a development-only panel. No persistence,
// entitlement API, payment, contact access or invitation dispatch is performed.
export function FamilyDevelopmentPanel({ state, onChange, onOpenGuardian, historyBox, onHistoryBoxChange, onOpenHistory }: { historyBox?: 'sent' | 'received'; onHistoryBoxChange?: (box: 'sent' | 'received') => void; onOpenHistory?: () => void; onOpenGuardian?: () => void; state: FamilyPreviewState; onChange: (state: FamilyPreviewState) => void }) {
  if (!import.meta.env.DEV) return null
  return <details className="family-dev-panel">
    <summary>개발용 미리보기</summary>
    <label htmlFor="family-preview-state">가족 보호 이용 상태</label>
    <select id="family-preview-state" value={state} onChange={event => onChange(event.target.value as FamilyPreviewState)}>
      <option value="free">무료 · 활성화 전</option>
      <option value="paid-connected">유료 · 가족 연결 완료</option>
      <option value="paid-unlinked">유료 · 가족 미연결</option>
    </select>
    <button type="button" onClick={() => onChange(initialFamilyPreview)}>기본 상태로 초기화</button>
    {onOpenGuardian && <button type="button" onClick={onOpenGuardian}>보호자 공유 화면 보기</button>}
    {onHistoryBoxChange && <><label htmlFor="history-preview-box">가족 보호 기록 관점</label><select id="history-preview-box" value={historyBox} onChange={event => onHistoryBoxChange(event.target.value as 'sent' | 'received')}><option value="sent">보낸 요청 · 고령자</option><option value="received">받은 요청 · 보호자</option></select><button type="button" onClick={onOpenHistory}>가족 보호 기록 보기</button></>}
    <p>화면 확인용 상태입니다. 가족 이름은 예시이며 실제 결제·초대·알림은 실행되지 않습니다. 새로고침하면 기본 상태로 돌아갑니다.</p>
  </details>
}
