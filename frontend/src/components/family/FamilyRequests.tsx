import { useCallback, useEffect, useRef, useState, type FormEvent, type Ref } from 'react'
import type { FamilyReplyChoice, FamilyRequestItem } from '../../api/family'
import { useFamily } from '../../hooks/useFamily'
import { factorLabels, formatTime, replyLabels, replyText } from '../../family/labels'
import { Avatar } from './FamilyParts'
import { riskLevels } from '../../riskLevels'
import { Icon } from '../Icons'
import { FactorList, FamilyHeader, ReplyCard, RequestTimeline, RiskChip, WaitWarning } from './FamilyParts'

type Go = (hash: string, replace?: boolean) => void
type Props = { go: Go; titleRef: Ref<HTMLHeadingElement> }

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'
}


export function RecordsPage({ box, go, titleRef }: Props & { box: 'sent' | 'received' }) {
  const family = useFamily()
  const [items, setItems] = useState<FamilyRequestItem[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setItems(null)
    setError('')
    family.actions.listRequests(box)
      .then(list => { if (active) setItems(list) })
      .catch(e => { if (active) setError(errorText(e)) })
    return () => { active = false }
  }, [box, family.actions])
  useEffect(() => {
    let active = true
    const refresh = () => {
      if (document.visibilityState !== 'visible') return
      family.actions.listRequests(box).then(list => { if (active) { setItems(list); setError('') } }).catch(e => { if (active) setError(errorText(e)) })
    }
    const timer = window.setInterval(refresh, 4_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh) }
  }, [box, family.actions])
  const tabs = [
    { box: 'received' as const, label: '받은 요청', count: family.summary?.waiting_requests ?? 0 },
    { box: 'sent' as const, label: '보낸 요청', count: family.summary?.new_replies ?? 0 },
  ]
  return <>
    <FamilyHeader title="가족 보호 기록" onBack={() => go('family')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      <div className="family-tabs" role="tablist" aria-label="기록 종류">
        {tabs.map(tab => <button key={tab.box} role="tab" aria-selected={box === tab.box}
          className={box === tab.box ? 'selected' : ''} onClick={() => go(`family/records/${tab.box}`, true)}>
          {tab.label}{tab.count > 0 && <span className="family-badge">{tab.count}</span>}
        </button>)}
      </div>
      <p className="hint">{box === 'sent' ? '내가 가족에게 확인을 요청한 기록이에요.' : '가족이 나에게 확인을 요청한 기록이에요.'} 기록은 7일이 지나면 지워져요.</p>
      {error && <p className="error-message" role="alert">{error}</p>}
      {!items && !error && <p role="status">기록을 불러오고 있어요.</p>}
      {items?.length === 0 && <p className="family-empty">아직 기록이 없어요.</p>}
      <div className="live-history">
        {items?.map(item => <section className="history-date-group" key={item.id}>
          <h2>{new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'Asia/Seoul' }).format(new Date(item.created_at))}</h2>
          <article className={`history-request${box === 'received' && !item.reply ? ' is-pending' : ''}`}>
            <button className="history-open" aria-label={`${item.name} 님${box === 'received' ? '이 요청' : '에게 보낸 요청'} 확인하기`} onClick={() => go(`family/request/${encodeURIComponent(item.id)}`)}>
              <span className="history-meta"><RiskChip level={item.risk_level} /><small>{formatTime(item.created_at)}{item.auto ? ' · 자동 알림' : ''}</small><Icon name="chevron" /></span>
              <span className="history-subject"><Avatar name={item.name} /><span><small>{item.name}</small><strong>{item.factor_codes.map(code => factorLabels[code]).join(' · ') || '분석 결과 확인 요청'}</strong></span></span>
            </button>
            <div className="history-responses history-my-response"><p className="history-my-reply"><span className="history-plane" aria-hidden="true" /><strong>{box === 'received' ? '나' : item.name}</strong><span className="history-my-reply-text">{item.reply ? replyText(item.reply) : ''}</span></p></div>
          </article>
        </section>)}
      </div>
    </main>
  </>
}

const choices: { value: FamilyReplyChoice; label: string }[] = [
  { value: 'looks_dangerous', label: replyLabels.looks_dangerous },
  { value: 'looks_fine', label: replyLabels.looks_fine },
  { value: 'custom', label: '직접 입력하기' },
]

export function RequestPage({ id, go, titleRef }: Props & { id: string }) {
  const family = useFamily()
  const [item, setItem] = useState<FamilyRequestItem | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try { setItem(await family.actions.getRequest(id)); setError('') } catch (e) { setError(errorText(e)) }
  }, [family.actions, id])
  useEffect(() => { void load() }, [load])
  // 보낸 사람은 확인·의견이 올 때까지 가끔 다시 확인한다.
  useEffect(() => {
    if (!item || item.box !== 'sent' || item.reply) return
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 8_000)
    return () => window.clearInterval(timer)
  }, [item, load])
  const title = item?.box === 'received' ? '가족 보호 요청' : '확인 요청 상태'
  return <>
    <FamilyHeader title={title} onBack={() => go(item?.box === 'received' ? 'family/records/received' : 'family/records')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      {error && <>
        <p className="error-message" role="alert">{error}</p>
        <button className="primary-button" onClick={() => go('family/records')}>가족 보호 기록으로</button>
      </>}
      {!item && !error && <p role="status">내용을 불러오고 있어요.</p>}
      {item?.box === 'received' && <ReceivedRequest item={item} onReplied={setItem} />}
      {item?.box === 'sent' && <>
        <section className="family-panel">
          <p className="family-request-head"><strong>{item.name} 님에게 보낸 확인 요청</strong><RiskChip level={item.risk_level} /></p>
          <RequestTimeline item={item} pushOn={!!family.summary?.push_subscribed} />
        </section>
        <ReplyCard item={item} />
        {!item.reply && <WaitWarning />}
        <h3 className="family-subtitle">보낸 위험 요소</h3>
        <FactorList codes={item.factor_codes} level={item.risk_level} />
        <button className="primary-button family-submit" onClick={() => go('')}><Icon name="home" />홈으로</button>
      </>}
    </main>
  </>
}

function ReceivedRequest({ item, onReplied }: { item: FamilyRequestItem; onReplied: (item: FamilyRequestItem) => void }) {
  const family = useFamily()
  const [choice, setChoice] = useState<FamilyReplyChoice>('looks_dangerous')
  const [text, setText] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const confirmation = useRef<HTMLDialogElement>(null)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      onReplied(await family.actions.reply(item.id, choice, choice === 'custom' ? text : undefined))
      confirmation.current?.showModal()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setPending(false)
    }
  }
  return <>
    <div className="guardian-requester"><Avatar name={item.name} /><p className="live-requester-copy">
      <span><strong>{item.name}</strong> 님이 확인을 요청했어요.</span>
      <small>{formatTime(item.created_at)}{item.auto ? ' · 위험 결과 자동 알림' : ''}</small>
    </p><button className="guardian-history" aria-label="가족 보호 기록 보기" onClick={() => { location.hash = 'family/records/received' }}><span aria-hidden="true" />기록</button></div>
    <section className={`result-card ${item.risk_level} family-result guardian-analysis`} aria-labelledby="family-result-title">
      <div className="family-result-banner guardian-risk">
        <span className="guardian-risk-icon" aria-hidden="true"><img src={`/assets/status-${item.risk_level === 'dangerous' ? 'danger' : item.risk_level === 'suspicious' ? 'suspicious' : item.risk_level === 'normal' ? 'normal' : 'insufficient'}.svg`} alt="" /></span>
        <div><h2 id="family-result-title">{riskLevels[item.risk_level].label}{item.risk_level !== 'insufficient_information' && <> <small>단계</small></>}</h2><p>PtoS 분석 결과이며 안전을 보장하지 않아요.</p></div>
      </div>
      <h3 className="family-subtitle">발견된 위험 요소</h3>
      <FactorList codes={item.factor_codes} level={item.risk_level} />
      <p className="hint">개인정보 보호를 위해 문자 원문과 링크 주소는 보내지 않았어요. 자세한 내용은 직접 연락해서 물어봐 주세요.</p>
    </section>
    {item.reply ? <section className="family-panel" aria-labelledby="sent-reply">
      <h3 id="sent-reply">보낸 의견</h3>
      <p className="family-reply-text">{replyText(item.reply)}</p>
      <small>{formatTime(item.reply.replied_at)}</small>
    </section> : <form onSubmit={submit} className="family-reply-form">
      <fieldset className="family-fieldset">
        <legend className="field-label">확인 메시지 보내기</legend>
        {choices.map(option => <label key={option.value} className={`family-option${choice === option.value ? ' selected' : ''}`}>
          <input type="radio" name="reply" value={option.value} checked={choice === option.value} onChange={() => setChoice(option.value)} />
          {option.label}
        </label>)}
      </fieldset>
      {choice === 'custom' && <>
        <label className="visually-hidden" htmlFor="reply-text">보낼 메시지</label>
        <textarea id="reply-text" className="family-reply-input" value={text} maxLength={100} placeholder="메시지 직접 입력하기"
          onChange={e => setText(e.target.value)} />
        <p className="hint">{Array.from(text).length}/100자</p>
      </>}
      {error && <p className="error-message" role="alert">{error}</p>}
      <button className="primary-button family-submit" disabled={pending || (choice === 'custom' && !text.trim())}>
        <span className="guardian-send-icon" aria-hidden="true" />의견 보내기
      </button>
    </form>}
    <dialog ref={confirmation} className="guardian-confirm" aria-labelledby="live-opinion-title"><div><h2 id="live-opinion-title"><span className="guardian-send-icon" aria-hidden="true" />의견 보내기</h2><p>의견이 정상적으로 전송됐어요!<br />자세한 내역은 가족 보호 기록에서 확인할 수 있어요.</p></div><button onClick={() => confirmation.current?.close()}>확인</button></dialog>
  </>
}
