import { useCallback, useEffect, useState, type FormEvent, type Ref } from 'react'
import type { FamilyReplyChoice, FamilyRequestItem } from '../../api/family'
import { useFamily } from '../../hooks/useFamily'
import { factorLabels, formatTime, replyLabels, replyText } from '../../family/labels'
import { Icon } from '../Icons'
import { FactorList, FamilyHeader, ReplyCard, RequestTimeline, RiskChip, WaitWarning } from './FamilyParts'

type Go = (hash: string, replace?: boolean) => void
type Props = { go: Go; titleRef: Ref<HTMLHeadingElement> }

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'
}

function statusText(item: FamilyRequestItem): string {
  if (item.box === 'received') return item.reply ? `보낸 의견: ${replyText(item.reply)}` : '아직 의견을 보내지 않았어요.'
  if (item.reply) return `의견 도착: ${replyText(item.reply)}`
  return item.viewed_at ? '가족이 확인했어요. 의견을 기다리는 중이에요.' : '가족이 아직 확인하지 않았어요.'
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
  const tabs = [
    { box: 'sent' as const, label: '보낸 요청', count: family.summary?.new_replies ?? 0 },
    { box: 'received' as const, label: '받은 요청', count: family.summary?.waiting_requests ?? 0 },
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
      <ul className="family-record-list">
        {items?.map(item => <li key={item.id}>
          <button className="family-record" onClick={() => go(`family/request/${encodeURIComponent(item.id)}`)}>
            <span className="family-record-top">
              <strong>{item.box === 'sent' ? `${item.name} 님에게` : `${item.name} 님이 요청`}</strong>
              <RiskChip level={item.risk_level} />
            </span>
            <small>{formatTime(item.created_at)}{item.auto ? ' · 자동 알림' : ''}</small>
            <span className="family-record-factors">{item.factor_codes.map(code => factorLabels[code]).join(', ') || '확인된 위험 요소 없음'}</span>
            <span className={`family-record-status${(item.box === 'received' && !item.reply) || (item.box === 'sent' && item.reply) ? ' highlight' : ''}`}>
              {statusText(item)}
            </span>
          </button>
        </li>)}
      </ul>
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
  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      onReplied(await family.actions.reply(item.id, choice, choice === 'custom' ? text : undefined))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setPending(false)
    }
  }
  return <>
    <p className="family-request-head panel">
      <strong>{item.name} 님이 확인을 요청했어요.</strong>
      <small>{formatTime(item.created_at)}{item.auto ? ' · 위험 결과 자동 알림' : ''}</small>
    </p>
    <section className={`result-card ${item.risk_level} family-result`} aria-labelledby="family-result-title">
      <div className="family-result-banner">
        <h2 id="family-result-title"><RiskChip level={item.risk_level} /></h2>
        <p>PtoS가 이 문자를 이렇게 분석했어요. 사기 여부를 확정하거나 안전을 보장하지 않아요.</p>
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
        <Icon name="share" />의견 보내기
      </button>
    </form>}
  </>
}
