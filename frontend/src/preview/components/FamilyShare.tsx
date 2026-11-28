import { useEffect, useRef, useState } from 'react'
import type { AnalysisResponse } from '../api/types'
import type { FamilyMember } from '../familyModel'
import { riskLevels } from '../riskLevels'
import { factorDisplay } from '../resultPresentation'
import { Icon } from './Icons'

type Receipt = 'mock' | 'handoff' | 'copied'
export function FamilyShare({ result, members, onBack, onHome, onConnect, shareUrl, mock = false }: {
  result: AnalysisResponse; members: FamilyMember[]; onBack: () => void; onHome: () => void; onConnect: () => void; shareUrl?: string; mock?: boolean
}) {
  const [selected, setSelected] = useState<string[]>(() => members.filter(m => m.status === 'connected').slice(0, 1).map(m => m.id))
  const [sheet, setSheet] = useState(false)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [mockStage, setMockStage] = useState(1)
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState('')
  const [time, setTime] = useState('')
  const wasSheet = useRef(false)
  const busy = useRef(false)
  const alive = useRef(true)
  const heading = useRef<HTMLHeadingElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const recipients = members.filter(m => m.status === 'connected' && selected.includes(m.id))
  const names = recipients.map(m => m.name).join(', ')
  const codes = [...new Set(result.evidence.filter(e => result.risk_factors.includes(e.label)).map(e => e.factor_code))]
  const summary = codes.map(code => factorDisplay[code]?.description.split('. ')[0]).filter(Boolean).slice(0, 2).join('. ')
    || (result.risk_level === 'normal' ? '이번 검사에서는 뚜렷한 위험 신호를 찾지 못했어요. 안전을 보장하지는 않습니다.' : '현재 정보만으로 구체적인 위험 요소를 확인하기 어려워요.')
  // 결과 페이지 링크는 서버에서 발급한 뒤 전달합니다. 입력 URL을 대신 사용하지 않습니다.
  const link = shareUrl && /^https?:\/\//u.test(shareUrl) ? shareUrl : null
  const supported = window.isSecureContext && typeof navigator.share === 'function'
  const mockSharing = import.meta.env.DEV && mock
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { if (receipt) dialog.current?.close(); heading.current?.focus(); window.scrollTo(0, 0) }, [receipt])
  useEffect(() => {
    if (sheet) { dialog.current?.showModal(); window.scrollTo(0, 0) }
    else { dialog.current?.close(); if (wasSheet.current && !receipt) trigger.current?.focus() }
    wasSheet.current = sheet
  }, [sheet, receipt])
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !sheet) onBack() }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [sheet, onBack])
  function finish(kind: Receipt) {
    setTime(new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: 'numeric', minute: '2-digit' }).format(new Date()))
    setReceipt(kind); setSheet(false); setNotice('')
  }
  async function send(copy = false) {
    if (busy.current || !recipients.length) return
    if (mockSharing) { finish('mock'); return }
    if (!link) return
    busy.current = true; setPending(true); setNotice('')
    try {
      if (copy) {
        if (!navigator.clipboard?.writeText) throw new Error('copy')
        await navigator.clipboard.writeText(link)
      } else {
        const data = { title: 'PtoS 분석 결과', url: link }
        if (!supported || (navigator.canShare && !navigator.canShare(data))) throw new Error('share')
        await navigator.share(data)
      }
      if (alive.current) finish(copy ? 'copied' : 'handoff')
    } catch (error) {
      if (alive.current) {
        setNotice(error instanceof Error && error.name === 'AbortError' ? '공유를 취소했어요. 다시 선택할 수 있어요.'
          : copy ? '자동 복사를 할 수 없어요. 잠시 후 링크 복사를 다시 시도해 주세요.' : '공유 창을 열지 못했어요. 복사하기를 이용해 주세요.')
      }
    } finally { busy.current = false; if (alive.current) setPending(false) }
  }
  return <>
    <header className="page-header family-share-header"><button className="icon-button" aria-label="분석 결과로 돌아가기" onClick={onBack}><Icon name="back" /></button><h1 ref={heading} tabIndex={-1}>가족에게 공유하기</h1></header>
    <main id="main" tabIndex={-1} className={`family-share-main ${result.risk_level}`}>
      {!receipt ? <>
        <h2>가족에게 이렇게 보내요.</h2><p className="family-share-subtitle">보낼 내용을 먼저 확인해 주세요.</p>
        <section className="family-share-preview" aria-label="보낼 분석 결과">
          <div className="family-share-preview-title"><h2>PtoS 분석 결과</h2><span className="family-share-level">{riskLevels[result.risk_level].label}{result.risk_level !== 'insufficient_information' && ' 단계'}</span></div>
          <><h3>발견된 위험 요소</h3>{result.risk_factors.length ? <ul className="family-share-factors">{result.risk_factors.map(label => {
            const evidence = result.evidence.find(e => e.label === label)
            return <li key={label}><span className="factor-symbol"><img src={`/assets/${factorDisplay[evidence?.factor_code ?? '']?.icon ?? 'risk-people'}.svg`} alt="" /></span><strong>{label}</strong></li>
          })}</ul> : <p>{result.risk_level === 'normal' ? '뚜렷한 위험 신호가 없어요.' : '확인된 위험 신호가 없어요. 정상이라는 뜻은 아니에요.'}</p>}</>
          <h3>내용 요약</h3><p>{summary}</p>
        </section>
        <fieldset className="family-share-recipients"><legend>누구에게 보낼까요?</legend><div className="family-share-recipient-list">{members.map(member => <label key={member.id} className={`family-share-recipient${selected.includes(member.id) && member.status === 'connected' ? ' is-selected' : ''}${member.status !== 'connected' ? ' is-disabled' : ''}`}>
          <input type="checkbox" aria-label={`${member.name}에게 공유`} disabled={pending || member.status !== 'connected'} checked={member.status === 'connected' && selected.includes(member.id)} onChange={e => setSelected(e.target.checked ? [...selected, member.id] : selected.filter(id => id !== member.id))} />
          <span className="family-share-tick" aria-hidden="true" /><span className={`family-avatar${member.relation === '형제' ? ' gold' : ''}`}>{member.name[0]}</span><span><strong>{member.name}</strong> <small>({member.relation})</small>{member.status !== 'connected' && <small className="family-share-pending">초대 수락 전이라 공유할 수 없어요.</small>}</span>
        </label>)}</div>{!members.some(m => m.status === 'connected') && <p>먼저 가족 연결을 완료해 주세요.</p>}</fieldset>
        {!members.some(m => m.status === 'connected') && <button className="family-outline-button" onClick={onConnect}>＋ 가족 연결하기</button>}
        <button ref={trigger} className="primary-button family-share-submit" disabled={pending || !recipients.length} onClick={() => { setNotice(''); setSheet(true) }}><Icon name="share" />공유하기</button>
      </> : <>
        <section className="family-share-status-intro"><span className="family-share-clock" aria-hidden="true" /><h2>{receipt === 'mock' ? <>{names} 님에게<br />결과를 공유했어요</> : receipt === 'copied' ? '공유 링크를 복사했어요' : '공유 상태를 확인해 주세요'}</h2><p>{receipt === 'mock' ? '가족이 확인하면 알림으로 알려드릴게요.' : '실제 전송 여부는 선택한 앱에서 확인해 주세요.'}</p></section>
        <ol className="family-share-timeline"><li className="is-done"><span className="family-share-step-check" aria-hidden="true" /><strong>{receipt === 'mock' ? '가족에게 보냈어요.' : receipt === 'copied' ? '공유 링크를 복사했어요.' : '공유 앱에 내용을 전달했어요.'}</strong><p>오늘 {time}</p></li><li className={receipt === 'mock' ? mockStage > 1 ? 'is-done' : 'is-current' : ''}><span className="family-share-step-check" aria-hidden="true" /><strong>{receipt !== 'mock' ? '가족 확인 여부는 알 수 없어요' : mockStage > 1 ? `${names} 님이 확인했어요` : `${names} 님이 확인하는 중`}</strong><p>{receipt !== 'mock' ? '확인 상태 연동은 준비 중입니다.' : mockStage > 1 ? '가족 확인 완료' : '아직 확인 전이에요.'}</p></li><li className={receipt === 'mock' && mockStage === 3 ? 'is-done' : ''}><span className="family-share-step-check" aria-hidden="true" /><strong>의견 도착</strong><p>{receipt === 'mock' && mockStage === 3 ? '“링크를 누르지 말고 먼저 확인해요.”' : '의견 알림 연동은 준비 중입니다.'}</p></li></ol>
        <aside className="family-share-warning"><Icon name="warning" /><strong>답이 올 때까지 문자 속 지시사항을 따르거나 링크 등을 클릭하지 마세요.</strong></aside>
        <button className="primary-button family-share-submit" onClick={onHome}><Icon name="home" />홈으로</button>
        {import.meta.env.DEV && receipt === 'mock' && <details className="family-share-options"><summary>공유 상태 미리보기</summary><button onClick={() => setMockStage(2)}>가족 확인 상태 보기</button><button onClick={() => setMockStage(3)}>의견 도착 상태 보기</button></details>}
      </>}
    </main>
    <dialog ref={dialog} className="family-share-methods" aria-labelledby="family-share-method-title" onCancel={e => { e.preventDefault(); setSheet(false) }}>
      <div className="family-share-method-heading"><Icon name="message" /><div><h2 id="family-share-method-title">PtoS 분석 결과</h2><p>결과 확인 링크 · {names}</p></div><button className="icon-button" aria-label="공유 창 닫기" onClick={() => setSheet(false)}><Icon name="close" /></button></div>
      <p>받는 가족은 공유 앱에서도 직접 선택해 주세요.</p>
      <button className="primary-button" disabled={pending || (!mockSharing && (!link || !supported))} onClick={() => void send()}><Icon name="share" />공유할 앱 선택</button>
      <button className="family-outline-button" disabled={!link || pending} onClick={() => void send(true)}><Icon name="copy" />링크 복사하기</button>
      {!supported && !mockSharing && <p>이 브라우저에서는 앱 공유를 지원하지 않아요. 링크 복사하기를 이용해 주세요.</p>}
      {mockSharing ? <p>미리보기에서는 앱 선택 버튼을 누르면 공유 후 화면으로 이어져요. 실제 앱을 열거나 메시지를 보내지 않습니다.</p> : !link ? <p>공유 링크 연결 준비 중입니다.</p> : <p className="family-share-link">{link}</p>}
      <p role="status">{pending ? '처리 중이에요.' : notice}</p>
      {import.meta.env.DEV && <div className="family-share-demo"><p>개발용 미리보기 · 실제 전송·링크 생성·확인 알림은 실행하지 않습니다.</p><button disabled={pending} onClick={() => finish('mock')}>모의 공유 상태 보기</button></div>}
    </dialog>
  </>
}
