import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Icon } from './Icons'
import type { FamilyModel, FamilyMember } from '../familyModel'

type Screen = 'overview' | 'auto' | 'connect' | 'history' | 'emergency'
type Dialog = 'contacts' | 'recipient' | null
export function FamilyProtectionFlow({ model, setModel, onHome }: {
  model: FamilyModel; setModel: Dispatch<SetStateAction<FamilyModel>>; onHome: () => void
}) {
  const [screen, setScreen] = useState<Screen>('overview')
  const [editing, setEditing] = useState(false)
  const [relation, setRelation] = useState('자식')
  const [phone, setPhone] = useState('')
  const [contact, setContact] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [modal, setModal] = useState<Dialog>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const phoneInput = useRef<HTMLInputElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const approved = model.members.filter(member => member.status === 'connected')
  const recipient = approved.find(member => member.id === model.recipientId)
  const titles = { overview: '가족 보호', auto: '위험 메시지 자동 알림', connect: '가족 연결하기', history: '가족 보호 기록', emergency: '긴급 연락' }
  useEffect(() => { heading.current?.focus(); window.scrollTo(0, 0) }, [screen])
  useEffect(() => {
    if (modal) dialog.current?.showModal()
    else if (dialog.current?.open) { dialog.current.close(); opener.current?.focus() }
  }, [modal])
  function openModal(next: Dialog) { opener.current = document.activeElement as HTMLElement; setModal(next) }
  function go(next: Screen) { setScreen(next); setNotice(''); setError(''); setEditing(false) }
  function remove(member: FamilyMember) {
    setModel(previous => ({ ...previous,
      members: previous.members.filter(item => item.id !== member.id),
      recipientId: previous.recipientId === member.id ? null : previous.recipientId,
      autoAlert: previous.recipientId === member.id ? false : previous.autoAlert,
    }))
    setNotice('미리보기에서 가족을 삭제했어요. 실제 연결에는 영향을 주지 않습니다.')
  }
  return <>
    <header className="page-header family-flow-header">
      <button className="icon-button" aria-label={screen === 'overview' ? '홈으로 돌아가기' : '가족 보호로 돌아가기'} onClick={() => screen === 'overview' ? onHome() : go('overview')}><Icon name="back" /></button>
      <h1 ref={heading} tabIndex={-1}>{titles[screen]}</h1>
      {screen === 'auto' && <span className={`auto-state${model.autoAlert ? ' is-on' : ''}`}>{model.autoAlert ? 'ON' : 'OFF'}</span>}
    </header>
    <main id="main" tabIndex={-1} className="family-flow-main">
      {screen === 'overview' && <>
        <div className="family-section-heading"><h2>연결된 가족</h2><button className="family-edit" aria-pressed={editing} onClick={() => setEditing(value => !value)}><span className="family-edit-icon" aria-hidden="true" />{editing ? '수정 완료' : '수정하기'}</button></div>
        <section className="family-list-panel" aria-label="연결된 가족 목록">
          {!model.members.length && <p className="family-empty">아직 연결된 가족이 없어요. 가족을 초대해 주세요.</p>}
          {model.members.map(member => <div className="family-member" key={member.id}>
            <span className={`family-avatar${member.relation === '형제' ? ' gold' : ''}`} aria-hidden="true">{Array.from(member.name)[0]}</span>
            <div className="family-member-name"><strong>{member.name}</strong><small>{member.relation}</small></div>
            <span className={`family-connection-badge ${member.status}`}>{member.status === 'connected' ? '연결 완료' : '수락 대기'}</span>
            {editing && <div className="family-edit-actions">
              {member.status === 'pending' && <button onClick={() => { setModel(previous => ({ ...previous, members: previous.members.map(item => item.id === member.id ? { ...item, status: 'connected' } : item) })); setNotice('초대 수락 상태를 모의로 변경했어요.') }}>모의 수락</button>}
              <button aria-label={`${member.name} 삭제`} onClick={() => remove(member)}>삭제</button>
            </div>}
          </div>)}
          <button className="primary-button family-add" onClick={() => { setPhone(''); setContact(false); go('connect') }}>＋ 가족 더 연결하기</button>
        </section>
        <h2 className="family-functions-title">가족 보호 기능</h2>
        <nav className="family-functions" aria-label="가족 보호 기능">
          <button onClick={() => go('auto')}><span><strong>위험 메시지 자동 알림</strong><small>‘위험’이 나오면 가족에게 자동으로 알립니다.</small></span><b>{model.autoAlert ? 'ON' : 'OFF'}</b><Icon name="chevron" /></button>
          <button onClick={() => go('history')}><span><strong>가족 보호 기록</strong><small>가족과 함께 확인한 내용을 모아 볼 수 있습니다.</small></span><Icon name="chevron" /></button>
          <button onClick={() => go('emergency')}><span><strong>긴급 연락</strong><small>버튼 하나로 가족에게 바로 전화할 수 있습니다.</small></span><Icon name="chevron" /></button>
        </nav>
      </>}
      {screen === 'auto' && <>
        <section className="family-alert-intro"><h2>위험한 결과로 나오면 가족에게 자동으로 알릴까요?</h2><p>분석 결과가 ‘위험’이면 공유 버튼을 누르지 않아도 연결된 가족에게 바로 알려요.</p></section>
        <section className="family-disclosure">
          <div><h2>가족에게 보내는 내용</h2><ul>{['위험 단계와 분석 결과', '발견된 위험 요소', '원문 요약'].map(text => <li key={text}><span className="family-disclosure-check" aria-hidden="true"><img src="/assets/icon-check.svg" alt="" /></span>{text}</li>)}</ul></div>
          <div><h2>보내지 않는 내용</h2><ul>{['다른 문자와 사진', '내 위치', '내 연락처 목록'].map(text => <li key={text}><span className="family-disclosure-no" aria-hidden="true"><Icon name="close" /></span>{text}</li>)}</ul></div>
        </section>
        <div className="family-recipient"><span className="family-avatar" aria-hidden="true">{recipient ? Array.from(recipient.name)[0] : '?'}</span><div><strong>받는 가족</strong><p>{recipient ? `${recipient.name}(${recipient.relation})` : '받을 가족을 선택해 주세요.'}</p></div><button className="family-outline-small" onClick={() => openModal('recipient')}>바꾸기</button></div>
        <button type="button" className="family-outline-button family-add-recipient" onClick={() => { setPhone(''); setContact(false); go('connect') }}>＋ 가족 추가하기</button>
        {!recipient && <p className="family-help">수락을 완료한 가족을 선택해야 알림을 켤 수 있어요.</p>}
        <button className={model.autoAlert ? 'family-outline-button' : 'primary-button family-primary'} disabled={!recipient} onClick={() => {
          if (!recipient) return
          setModel(previous => ({ ...previous, autoAlert: !previous.autoAlert }))
          setNotice(model.autoAlert ? '자동 알림을 껐어요. 실제 알림은 전송되지 않았습니다.' : '자동 알림 ON 상태를 미리보고 있어요. 실제 알림은 전송되지 않습니다.')
        }}>{model.autoAlert ? <><span className="family-notification-off" aria-hidden="true" />알림 해제하기</> : '동의하고 자동 알림 켜기'}</button>
      </>}
      {screen === 'connect' && <form className="family-connect-form" noValidate onSubmit={event => {
        event.preventDefault()
        const digits = phone.replace(/[\s()-]/g, '')
        if (!/^01[016789]\d{7,8}$/.test(digits)) { setError('휴대전화 번호를 확인해 주세요.'); phoneInput.current?.focus(); return }
        setModel(previous => ({ ...previous, members: [...previous.members, { id: crypto.randomUUID(), name: contact ? '우리 아들♥' : '초대한 가족', relation, status: 'pending' }] }))
        setPhone(''); setContact(false); go('overview'); setNotice('초대를 모의로 만들었어요. 실제 메시지는 보내지 않았으며 수락 대기로 표시됩니다.')
      }}>
        <p className="family-invite-intro">카카오톡이나 문자로 초대 링크를 보내요. 상대방이 수락하면 연결이 완료됩니다.</p>
        <fieldset className="family-relations"><legend>누구를 연결할까요?</legend>{['자식', '배우자', '형제', '기타'].map(value => <label key={value} className={relation === value ? 'is-selected' : ''}><input type="radio" name="family-relation" value={value} checked={relation === value} onChange={() => setRelation(value)} />{relation === value && <span className="family-relation-check" aria-hidden="true" />}{value}</label>)}</fieldset>
        <label className="family-contact-label" htmlFor="family-phone">연락처</label>
        {contact ? <div className="family-picked-contact"><span className="family-avatar blue" aria-hidden="true">우</span><div><strong>우리 아들♥</strong><small>010 0000 0000</small></div></div> : <input ref={phoneInput} id="family-phone" className="family-phone" type="tel" inputMode="tel" autoComplete="off" placeholder="전화번호 직접 입력하기" value={phone} maxLength={20} onChange={event => { setPhone(event.target.value); setError('') }} aria-invalid={!!error} aria-describedby={error ? 'family-phone-error' : undefined} />}
        <button type="button" className="family-outline-button" onClick={() => openModal('contacts')}><Icon name="people" />{contact ? '다시 고르기' : '연락처에서 고르기'}</button>
        {error && <p id="family-phone-error" role="alert" className="error-message">{error}</p>}
        <button className="primary-button family-primary family-send" type="submit"><img className="family-send-icon" src="/assets/icon-sent.svg" width="28" height="28" alt="" />초대 보내기</button>
      </form>}
      {screen === 'history' && <section className="family-alert-intro"><h2>아직 보호 기록이 없어요.</h2><p>기록 화면은 준비 중입니다. 분석 결과나 원문을 저장하지 않습니다.</p></section>}
      {screen === 'emergency' && <section className="family-functions"><h2>연락할 가족</h2>{approved.map(member => <button key={member.id} onClick={() => setNotice(`${member.name}에게 연락하는 모의 동작입니다. 실제 전화는 걸리지 않습니다.`)}><span><strong>{member.name}</strong><small>모의 전화 연결</small></span><Icon name="chevron" /></button>)}{!approved.length && <p>연결이 완료된 가족이 없어요.</p>}</section>}
      {notice && <p role="status" className="family-flow-notice">{notice}</p>}
    </main>
    <dialog ref={dialog} aria-labelledby="family-choice-title" onCancel={() => setModal(null)} onClose={() => setModal(null)}>
      <div className="dialog-heading"><h2 id="family-choice-title">{modal === 'contacts' ? '연락처 선택' : '받는 가족 선택'}</h2><button className="icon-button" aria-label="선택 창 닫기" onClick={() => setModal(null)}><Icon name="close" /></button></div>
      {modal === 'contacts' ? <><p>실제 연락처에는 접근하지 않아요. 예시 연락처를 선택해 주세요.</p><button className="family-choice" onClick={() => { setContact(true); setPhone('01000000000'); setError(''); setModal(null) }}><strong>우리 아들♥</strong><small>010 0000 0000 · 예시</small></button><button className="family-outline-button" onClick={() => { setContact(false); setPhone(''); setModal(null) }}>전화번호 직접 입력</button></> : <>
        {model.members.map(member => <button key={member.id} className="family-choice" disabled={member.status !== 'connected'} onClick={() => {
          const changed = member.id !== model.recipientId
          setModel(previous => ({ ...previous, recipientId: member.id, autoAlert: changed ? false : previous.autoAlert }))
          setModal(null)
          if (changed) setNotice('받는 가족을 변경했어요. 자동 알림은 다시 동의한 뒤 켜 주세요.')
        }}><strong>{member.name}</strong><small>{member.status === 'connected' ? member.relation : '수락 대기 · 선택할 수 없어요'}</small></button>)}
        {!approved.length && <p>먼저 가족 연결을 완료해 주세요.</p>}
        <button className="family-outline-button" onClick={() => { setModal(null); setPhone(''); setContact(false); go('connect') }}>＋ 가족 추가하기</button>
      </>}
    </dialog>
  </>
}
