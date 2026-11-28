import { useEffect, useRef, useState } from 'react'
import type { GuardianRequest } from '../guardianPreview'
import { riskLevels } from '../riskLevels'
import { Icon } from './Icons'

type Opinion = 'danger' | 'okay' | 'custom'
export function GuardianShare({ request, onBack, onHistory, onReply, initialReply = '' }: {
  request: GuardianRequest | null; onBack: () => void; onHistory: () => void; onReply?: (reply: string) => void; initialReply?: string
}) {
  const [opinion, setOpinion] = useState<Opinion>('danger')
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState(initialReply)
  const [confirmation, setConfirmation] = useState(false)
  const confirmationDialog = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const editor = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { heading.current?.focus(); window.scrollTo(0, 0) }, [request])
  useEffect(() => { if (opinion === 'custom') editor.current?.focus() }, [opinion])
  useEffect(() => { if (confirmation) confirmationDialog.current?.showModal(); else confirmationDialog.current?.close() }, [confirmation])
  function closeConfirmation() { confirmationDialog.current?.close(); setConfirmation(false); heading.current?.focus() }
  const reply = opinion === 'custom' ? message.trim() : opinion === 'danger' ? '위험해 보여요.' : '문제 없어 보여요.'
  return <>
    <header className="page-header guardian-header"><button type="button" className="icon-button" aria-label="홈으로 돌아가기" onClick={onBack}><Icon name="back" /></button><h1 ref={heading} tabIndex={-1}>가족 보호 요청</h1></header>
    <main id="main" tabIndex={-1} className={`guardian-main ${request?.riskLevel ?? ''}`}>
      {!request ? <section className="guardian-unavailable"><Icon name="lock" /><h2>공유 내용을 확인할 수 없어요.</h2><p>공유 링크 조회 기능은 준비 중입니다. 실제 서비스에서는 수신 권한과 링크 유효기간을 확인한 뒤 내용을 보여드릴 예정입니다.</p><button className="primary-button" onClick={onBack}>홈으로</button></section> : <>
        <section className="guardian-requester" aria-label="확인을 요청한 가족">
          <span className="family-avatar guardian-avatar" aria-hidden="true">{request.senderName[0]}</span>
          <div><p><strong>{request.senderName}</strong>가 확인을 요청했어요.</p><small>{request.requestedAt}</small></div>
          <button type="button" className="guardian-history" aria-label="가족 보호 기록 보기" onClick={onHistory}><span aria-hidden="true" />기록</button>
        </section>
        <section className="guardian-analysis" aria-label="가족이 공유한 분석 결과">
          <h2>원문 요약</h2><p className="guardian-summary">{request.summary}</p>
          <p className="guardian-metadata">발신자: {request.maskedSender} · 포함된 링크 {request.linkCount}개</p>
          <div className="guardian-risk"><span className="guardian-risk-icon" aria-hidden="true"><img src={`/assets/status-${request.riskLevel === 'dangerous' ? 'danger' : request.riskLevel === 'suspicious' ? 'suspicious' : request.riskLevel === 'normal' ? 'normal' : 'insufficient'}.svg`} alt="" /></span><div><h2>{riskLevels[request.riskLevel].label}{request.riskLevel !== 'insufficient_information' && <small> 단계</small>}</h2><p>{request.riskLevel === 'dangerous' ? '위험해 보이는 메시지로 분석됐어요.' : request.riskLevel === 'suspicious' ? '확인이 필요한 메시지로 분석됐어요.' : request.riskLevel === 'normal' ? '위험 신호를 찾지 못했지만 안전을 보장하지는 않아요.' : '정보가 부족해 판단하기 어려워요.'}</p></div></div>
          <h2 className="guardian-factors-heading">발견된 위험 요소</h2>
          {request.factors.length ? <ul className="guardian-factors">{request.factors.map(factor => <li key={factor.label}><span className="factor-symbol"><img src={`/assets/${factor.icon}.svg`} alt="" /></span><div><h3>{factor.label}</h3><p>{factor.description}</p></div></li>)}</ul> : <p>확인된 위험 요소가 없어요.</p>}
        </section>
        <form className="guardian-opinion" onSubmit={event => { event.preventDefault(); if (reply && !sent && import.meta.env.DEV) { setSent(reply); onReply?.(reply); setConfirmation(true) } }}>
          <fieldset><legend>확인 메시지 보내기</legend>{([['danger', '위험해 보여요.'], ['okay', '문제 없어 보여요.'], ['custom', '직접 입력하기']] as const).map(([value, label]) => <label key={value}><input type="radio" name="guardian-opinion" value={value} checked={opinion === value} onChange={() => { setOpinion(value); setSent('') }} />{label}</label>)}</fieldset>
          {opinion === 'custom' && <div className="guardian-editor"><label htmlFor="guardian-message" className="sr-only">보낼 확인 메시지</label><textarea id="guardian-message" ref={editor} placeholder="메시지 직접 입력하기" value={message} maxLength={500} rows={2} onChange={event => { setMessage(event.target.value); setSent('') }} /><small>{message.length} / 500자</small></div>}
          <p className="guardian-opinion-help">보호자의 의견이며 분석 결과를 변경하지 않습니다.</p>
          <button type="submit" className={`primary-button guardian-submit${sent ? ' is-sent' : ''}`} disabled={!reply || !!sent || !import.meta.env.DEV}><span className="guardian-send-icon" aria-hidden="true" />{sent ? '의견 보냄' : '의견 보내기'}</button>
          {sent && <p role="status" className="guardian-reply-status">{request.senderName} 님에게 의견을 보냈어요.<br />“{sent}”</p>}
        </form>
        {import.meta.env.DEV && <details className="guardian-preview-note"><summary>개발용 화면 안내</summary><p>링크로 접속한 보호자 화면의 합성 예시입니다. 실제 링크 조회·가족 확인 알림·의견 전송·기록 저장은 실행하지 않습니다. 원문 요약과 가린 번호도 고정 예시입니다.</p></details>}
      </>}
    </main>
    <dialog ref={confirmationDialog} className="guardian-confirm" aria-labelledby="guardian-confirm-title" onCancel={event => { event.preventDefault(); closeConfirmation() }}>
      <div><h2 id="guardian-confirm-title"><span className="guardian-send-icon" aria-hidden="true" />의견 보내기</h2><p>의견이 정상적으로 전송됐어요!<br />자세한 내역은 ‘가족 보호 기록’에서<br />확인할 수 있어요.</p></div><button type="button" onClick={closeConfirmation}>확인</button>
    </dialog>
  </>
}
