import { useCallback, useEffect, useRef, useState } from 'react'
import type { FactorCode, FamilyRequestItem } from '../../api/family'
import type { AnalysisResponse } from '../../api/types'
import { useFamily } from '../../hooks/useFamily'
import { factorLabels, relationLabels } from '../../family/labels'
import { Icon } from '../Icons'
import { Avatar, ReplyCard, RequestTimeline, RiskChip, WaitWarning } from './FamilyParts'

// 확인 요청에는 위험 단계와 위험 요소 코드만 넣는다. 원문·근거 구절·URL·보낸 번호·요청 id는 넣지 않는다.
export function factorCodes(result: AnalysisResponse): FactorCode[] {
  return [...new Set(result.evidence.map(item => item.factor_code))]
}

export function FamilySendSheet({ result, large, onClose, onOtherShare, go }: {
  result: AnalysisResponse; large: boolean; onClose: () => void; onOtherShare: () => void; go: (hash: string) => void
}) {
  const family = useFamily()
  const dialog = useRef<HTMLDialogElement>(null)
  const guardians = family.summary?.links.filter(link => link.role === 'guardian') ?? []
  const [selected, setSelected] = useState<string[]>(() => guardians.filter(link => link.status === 'connected').slice(0, 1).map(link => link.id))
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState<FamilyRequestItem[] | null>(null)
  const codes = factorCodes(result)
  useEffect(() => {
    const node = dialog.current!
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    node.showModal()
    return () => { node.close(); document.body.style.overflow = overflow }
  }, [])
  const reload = useCallback(async (ids: string[]) => {
    try { setSent(await Promise.all(ids.map(id => family.actions.getRequest(id)))) } catch { /* 다음 확인 때 다시 시도한다. */ }
  }, [family.actions])
  // 보낸 뒤에는 창이 열려 있는 동안 확인·의견 상태를 가끔 다시 확인한다.
  useEffect(() => {
    if (!sent || sent.every(item => item.reply)) return
    const ids = sent.map(item => item.id)
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void reload(ids) }, 5_000)
    return () => window.clearInterval(timer)
  }, [sent, reload])
  async function send() {
    if (pending || !selected.length) return
    setPending(true)
    setError('')
    try {
      const { request_ids } = await family.actions.sendRequests({ link_ids: selected, risk_level: result.risk_level, factor_codes: codes })
      await reload(request_ids)
    } catch (e) {
      setError(e instanceof Error ? e.message : '보내지 못했어요. 다시 시도해 주세요.')
    } finally {
      setPending(false)
    }
  }
  const names = sent?.map(item => item.name).join(', ')
  return <dialog ref={dialog} className={`share-sheet family-sheet${large ? ' share-sheet-large' : ''}`} aria-labelledby="family-send-title"
    onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="share-sheet-content">
      <header className="share-sheet-header">
        <h2 id="family-send-title">가족에게 공유하기</h2>
        <button type="button" className="icon-button" aria-label="공유 창 닫기" onClick={onClose}><Icon name="close" /></button>
      </header>
      {!sent ? <>
        <p><strong>가족에게 이렇게 보내요.</strong><br />보낼 내용을 먼저 확인해 주세요.</p>
        <section className="family-preview" aria-label="보낼 내용">
          <p className="family-request-head"><strong>PtoS 분석 결과</strong><RiskChip level={result.risk_level} /></p>
          <h3>발견된 위험 요소</h3>
          {codes.length
            ? <ul>{codes.map(code => <li key={code}>{factorLabels[code]}</li>)}</ul>
            : <p>확인된 위험 신호가 없어요. 정상이라는 뜻은 아니에요.</p>}
          <p className="hint">입력한 문자 원문, 링크 주소, 보낸 번호는 보내지 않아요.</p>
        </section>
        <fieldset className="family-fieldset">
          <legend className="field-label">누구에게 보낼까요?</legend>
          {guardians.map(link => {
            const disabled = link.status !== 'connected'
            const checked = selected.includes(link.id)
            return <label key={link.id} className={`family-option${checked ? ' selected' : ''}${disabled ? ' disabled' : ''}`}>
              <input type="checkbox" disabled={disabled} checked={checked}
                onChange={() => setSelected(checked ? selected.filter(id => id !== link.id) : [...selected, link.id])} />
              <Avatar name={link.name} />
              <span><strong>{link.name}</strong>{link.relation && <small> ({relationLabels[link.relation]})</small>}
                {disabled && <small className="family-option-note">초대 수락 전이라 보낼 수 없어요.</small>}</span>
            </label>
          })}
        </fieldset>
        {error && <p className="error-message" role="alert">{error}</p>}
        <div className="share-sheet-actions family-single-action">
          <button type="button" className="primary-button" disabled={pending || !selected.length} onClick={send}>
            <Icon name="share" />{pending ? '보내는 중' : '공유하기'}
          </button>
        </div>
        <button type="button" className="text-button" onClick={onOtherShare}>다른 앱으로 공유하거나 복사하기</button>
      </> : <>
        <div className="family-hero compact">
          <span className="family-hero-icon" aria-hidden="true">⏱</span>
          <p role="status"><strong>{names} 님에게 결과를 보냈어요.</strong><br />
            {family.summary?.push_subscribed ? '가족이 의견을 보내면 알림으로 알려드릴게요.' : '가족의 의견은 이 창이나 가족 보호 기록에서 볼 수 있어요.'}</p>
        </div>
        {sent.map(item => <div key={item.id} className="family-panel">
          {sent.length > 1 && <p><strong>{item.name}</strong></p>}
          <RequestTimeline item={item} pushOn={!!family.summary?.push_subscribed} />
          <ReplyCard item={item} />
        </div>)}
        {!sent.every(item => item.reply) && <WaitWarning />}
        <div className="share-sheet-actions">
          <button type="button" className="primary-button" onClick={() => { onClose(); go('family/records') }}>가족 보호 기록 보기</button>
          <button type="button" className="secondary-button" onClick={onClose}>닫기</button>
        </div>
      </>}
    </div>
  </dialog>
}
