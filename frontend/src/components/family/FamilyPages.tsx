import { useEffect, useRef, useState, type FormEvent, type Ref } from 'react'
import type { FamilyRelation } from '../../api/family'
import { useFamily } from '../../hooks/useFamily'
import { relationLabels } from '../../family/labels'
import { Icon } from '../Icons'
import { Avatar, FamilyHeader, PushToggle } from './FamilyParts'
import { RecordsPage, RequestPage } from './FamilyRequests'

export type FamilyRoute =
  | { name: 'protect' } | { name: 'premium' } | { name: 'connect' } | { name: 'auto-alert' }
  | { name: 'records'; box: 'sent' | 'received' } | { name: 'request'; id: string } | { name: 'invite'; token: string }

export function parseFamilyRoute(hash: string): FamilyRoute | null {
  const parts = hash.replace(/^#/, '').split('/')
  if (parts[0] !== 'family') return null
  const [, page, value] = parts
  if (!page) return { name: 'protect' }
  if (page === 'premium' || page === 'connect' || page === 'auto-alert') return { name: page }
  if (page === 'records') return { name: 'records', box: value === 'received' ? 'received' : 'sent' }
  if (page === 'request' && value) return { name: 'request', id: decodeURIComponent(value) }
  if (page === 'invite' && value) return { name: 'invite', token: decodeURIComponent(value) }
  return { name: 'protect' }
}

type Go = (hash: string, replace?: boolean) => void

export function FamilyPages({ route, go }: { route: FamilyRoute; go: Go }) {
  const family = useFamily()
  const title = useRef<HTMLHeadingElement>(null)
  const key = JSON.stringify(route)
  useEffect(() => { title.current?.focus(); window.scrollTo(0, 0) }, [key])
  if (!family.available) {
    return <>
      <FamilyHeader title="가족 보호" onBack={() => go('')} titleRef={title} />
      <main id="main" tabIndex={-1} className="flow-main family-main">
        <p className="instruction-panel">가족 보호 기능이 이 서버에서 꺼져 있어요. 결과 화면의 "가족에게 공유"로 내용을 직접 보낼 수 있어요.</p>
        <button className="primary-button" onClick={() => go('')}><Icon name="home" />홈으로</button>
      </main>
    </>
  }
  switch (route.name) {
    case 'premium': return <PremiumPage go={go} titleRef={title} />
    case 'connect': return <ConnectPage go={go} titleRef={title} />
    case 'auto-alert': return <AutoAlertPage go={go} titleRef={title} />
    case 'records': return <RecordsPage box={route.box} go={go} titleRef={title} />
    case 'request': return <RequestPage id={route.id} go={go} titleRef={title} />
    case 'invite': return <InvitePage token={route.token} go={go} titleRef={title} />
    default: return <ProtectPage go={go} titleRef={title} />
  }
}

type PageProps = { go: Go; titleRef: Ref<HTMLHeadingElement> }

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'
}

const features = [
  { title: '가족에게 확인 요청', text: '버튼 하나로 분석 결과를 연결된 가족에게 보내요.' },
  { title: '위험 메시지 자동 알림', text: "'위험'이 나오면 동의한 가족에게 자동으로 알려요." },
  { title: '가족 보호 기록', text: '가족과 함께 확인한 내용을 7일 동안 모아 봐요.' },
]

function PremiumPage({ go, titleRef }: PageProps) {
  const family = useFamily()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const started = !!family.summary?.premium
  async function start() {
    setPending(true)
    setError('')
    try { await family.actions.setPremium(true) } catch (e) { setError(errorText(e)) } finally { setPending(false) }
  }
  return <>
    <FamilyHeader title="가족 보호 프리미엄" onBack={() => go('')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      <div className="family-hero">
        <span className={`family-hero-icon${started ? ' done' : ''}`} aria-hidden="true">{started ? '✓' : <Icon name="people" />}</span>
        <h2>{started ? '프리미엄이 시작됐어요!' : '가족과 함께 사기를 막아요!'}</h2>
        <p>{started ? '바로 가족을 연결해 보세요. 위험한 문자를 함께 확인할 수 있어요.'
          : '위험한 문자가 오면 가족에게 바로 물어보고, 가족의 의견을 받아 볼 수 있어요.'}</p>
      </div>
      <section className="family-panel" aria-labelledby="premium-features">
        <h3 id="premium-features">{started ? '지금부터 사용할 수 있어요' : '프리미엄 기능'}</h3>
        <ul className="family-feature-list">
          {features.map(feature => <li key={feature.title}>
            <span className="family-feature-icon" aria-hidden="true">✓</span>
            <span><strong>{feature.title}</strong>{!started && <small>{feature.text}</small>}</span>
          </li>)}
        </ul>
      </section>
      {!started && <div className="family-price">
        <span>이용 금액</span><strong>시연용 · 실제 결제 없음</strong>
      </div>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {started
        ? <button className="primary-button" onClick={() => go('family/connect')}>지금 가족 연결하기</button>
        : <button className="primary-button" disabled={pending} onClick={start}>프리미엄 시작하기 (시연용)</button>}
      <p className="hint family-note">발표 시연용 기능이에요. 결제 정보를 받지 않고, 가입 여부는 이 서버에만 기록돼요.</p>
    </main>
  </>
}

function ProtectPage({ go, titleRef }: PageProps) {
  const family = useFamily()
  const [editing, setEditing] = useState(false)
  const [message, setMessage] = useState('')
  const summary = family.summary
  useEffect(() => { void family.refresh() }, [family.refresh])
  const guardians = summary?.links.filter(link => link.role === 'guardian') ?? []
  const protectedLinks = summary?.links.filter(link => link.role === 'protected') ?? []
  if (!summary?.premium && protectedLinks.length === 0) {
    if (family.loading && !summary) return <FamilyHeader title="가족 보호" onBack={() => go('')} titleRef={titleRef} />
    return <PremiumPage go={go} titleRef={titleRef} />
  }
  async function remove(id: string, name: string) {
    setMessage('')
    try { await family.actions.removeLink(id); setMessage(`${name} 님과의 연결을 끊었어요.`) } catch (e) { setMessage(errorText(e)) }
  }
  const auto = summary?.auto_alert
  return <>
    <FamilyHeader title="가족 보호" onBack={() => go('')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      {summary?.premium && <section className="family-section" aria-labelledby="guardians-title">
        <div className="family-section-heading">
          <h2 id="guardians-title">나를 지켜 주는 가족</h2>
          {guardians.length > 0 && <button type="button" className="text-button" onClick={() => setEditing(!editing)}>
            {editing ? '완료' : '수정하기'}</button>}
        </div>
        <div className="family-panel">
          {guardians.length === 0 && <p className="family-empty">아직 연결된 가족이 없어요.</p>}
          <ul className="family-link-list">
            {guardians.map(link => <li key={link.id}>
              <Avatar name={link.name} />
              <span className="family-link-name"><strong>{link.name}</strong>{link.relation && <small>{relationLabels[link.relation]}</small>}</span>
              {editing
                ? <button type="button" className="family-chip danger" onClick={() => remove(link.id, link.name)}>연결 끊기</button>
                : <span className={`family-chip ${link.status}`}>{link.status === 'connected' ? '✓ 연결 완료' : '… 수락 대기'}</span>}
            </li>)}
          </ul>
          <button className="primary-button family-add" onClick={() => go('family/connect')}>+ 가족 {guardians.length ? '더 ' : ''}연결하기</button>
        </div>
      </section>}
      {protectedLinks.length > 0 && <section className="family-section" aria-labelledby="protected-title">
        <h2 id="protected-title">내가 지켜 주는 가족</h2>
        <ul className="family-panel family-link-list">
          {protectedLinks.map(link => <li key={link.id}>
            <Avatar name={link.name} />
            <span className="family-link-name"><strong>{link.name}</strong><small>확인 요청을 받아요</small></span>
            {editing
              ? <button type="button" className="family-chip danger" onClick={() => remove(link.id, link.name)}>연결 끊기</button>
              : <span className="family-chip connected">✓ 연결 완료</span>}
          </li>)}
        </ul>
        {!summary?.premium && <button type="button" className="text-button" onClick={() => setEditing(!editing)}>{editing ? '완료' : '연결 관리'}</button>}
      </section>}
      <p className="family-feedback" role="status">{message}</p>
      <section className="family-section" aria-labelledby="features-title">
        <h2 id="features-title">가족 보호 기능</h2>
        <div className="family-panel family-menu">
          {summary?.premium && <button className="family-row" onClick={() => go('family/auto-alert')}>
            <span><strong>위험 메시지 자동 알림</strong><small>'위험'이 나오면 가족에게 자동으로 알려요.</small></span>
            <span className="family-row-state">{auto?.enabled ? 'ON' : 'OFF'}</span><Icon name="chevron" />
          </button>}
          <button className="family-row" onClick={() => go(summary?.waiting_requests ? 'family/records/received' : 'family/records')}>
            <span><strong>가족 보호 기록</strong><small>가족과 함께 확인한 내용을 7일 동안 볼 수 있어요.</small></span>
            {(summary?.waiting_requests ?? 0) + (summary?.new_replies ?? 0) > 0 &&
              <span className="family-badge">새 소식 {(summary?.waiting_requests ?? 0) + (summary?.new_replies ?? 0)}</span>}
            <Icon name="chevron" />
          </button>
          <PushToggle />
        </div>
      </section>
      <details className="result-details">
        <summary>시연용 설정</summary>
        <p className="hint">이 기기의 가족 보호 정보를 서버에서 지우거나 프리미엄(시연용)을 끌 수 있어요.</p>
        <div className="family-actions">
          {summary?.premium && <button type="button" className="secondary-button" onClick={() => family.actions.setPremium(false).catch(e => setMessage(errorText(e)))}>프리미엄 끄기</button>}
          <button type="button" className="secondary-button" onClick={async () => { await family.forgetDevice(); go('') }}>이 기기 정보 지우기</button>
        </div>
      </details>
    </main>
  </>
}

const relations: FamilyRelation[] = ['child', 'spouse', 'sibling', 'other']

function ConnectPage({ go, titleRef }: PageProps) {
  const family = useFamily()
  const [relation, setRelation] = useState<FamilyRelation>('child')
  const [name, setName] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [invite, setInvite] = useState<{ url: string; name: string } | null>(null)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      const created = await family.actions.createInvite(name, relation)
      setInvite({ url: `${location.origin}/#family/invite/${encodeURIComponent(created.invite_token)}`, name: name.trim() })
    } catch (e) {
      setError(errorText(e))
    } finally {
      setPending(false)
    }
  }
  const shareText = invite ? `[PtoS 가족 보호 초대]\n위험한 문자를 함께 확인해 주세요. 아래 링크를 열고 수락해 주세요. (24시간 안에 한 번만 쓸 수 있어요)` : ''
  async function share() {
    if (!invite) return
    setNotice('')
    try {
      await navigator.share({ title: 'PtoS 가족 보호 초대', text: shareText, url: invite.url })
      setNotice('공유 창에 넘겼어요. 가족에게 보내졌는지 확인해 주세요.')
    } catch (e) {
      setNotice(e instanceof Error && e.name === 'AbortError' ? '공유를 취소했어요.' : '공유 창을 열지 못했어요. 링크 복사를 이용해 주세요.')
    }
  }
  async function copy() {
    if (!invite) return
    try {
      await navigator.clipboard.writeText(`${shareText}\n${invite.url}`)
      setNotice('초대 내용을 복사했어요. 카카오톡이나 문자에 붙여넣어 보내세요.')
    } catch {
      setNotice('자동 복사를 할 수 없어요. 링크를 길게 눌러 복사해 주세요.')
    }
  }
  const canShare = typeof navigator.share === 'function' && window.isSecureContext
  return <>
    <FamilyHeader title="가족 연결하기" onBack={() => go('family')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      <p className="instruction-panel">카카오톡이나 문자로 초대 링크를 보내요. 상대방이 수락하면 연결이 완료돼요.</p>
      {!invite ? <form onSubmit={submit}>
        <fieldset className="family-fieldset">
          <legend className="field-label">누구를 연결할까요?</legend>
          <div className="family-choice-grid">
            {relations.map(value => <label key={value} className={`family-choice${relation === value ? ' selected' : ''}`}>
              <input type="radio" name="relation" value={value} checked={relation === value} onChange={() => setRelation(value)} />
              {relation === value && <span aria-hidden="true">✓ </span>}{relationLabels[value]}
            </label>)}
          </div>
        </fieldset>
        <label className="field-label" htmlFor="family-name">부르는 이름</label>
        <input id="family-name" className="family-input" value={name} maxLength={20} required autoComplete="off"
          placeholder="예: 우리 딸" onChange={e => setName(e.target.value)} />
        <p className="hint">이름만 저장해요. 전화번호와 연락처 목록은 받지 않아요.</p>
        {error && <p className="error-message" role="alert">{error}</p>}
        <button className="primary-button family-submit" disabled={pending || !name.trim()}><Icon name="share" />초대 링크 만들기</button>
      </form> : <section className="family-panel" aria-labelledby="invite-ready">
        <h2 id="invite-ready">{invite.name} 님에게 보낼 초대가 준비됐어요</h2>
        <p>아래 버튼으로 카카오톡이나 문자에 보내 주세요. 링크는 24시간 안에 한 번만 쓸 수 있어요.</p>
        <p className="family-invite-url" aria-label="초대 링크">{invite.url}</p>
        <div className="family-actions">
          {canShare && <button type="button" className="primary-button" onClick={share}><Icon name="share" />초대 보내기</button>}
          <button type="button" className={canShare ? 'secondary-button' : 'primary-button'} onClick={copy}><Icon name="copy" />링크 복사</button>
        </div>
        <p className="family-feedback" role="status">{notice}</p>
        <button type="button" className="secondary-button" onClick={() => go('family')}>가족 보호로 돌아가기</button>
      </section>}
    </main>
  </>
}

function InvitePage({ token, go, titleRef }: PageProps & { token: string }) {
  const family = useFamily()
  const [preview, setPreview] = useState<{ guardian_name: string } | null>(null)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [pending, setPending] = useState(false)
  const [done, setDone] = useState(false)
  useEffect(() => {
    let active = true
    family.actions.previewInvite(token)
      .then(result => { if (active) setPreview(result) })
      .catch(e => { if (active) setError(errorText(e)) })
    return () => { active = false }
  }, [token, family.actions])
  async function accept(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      await family.actions.acceptInvite(token, name)
      setDone(true)
      // 쓴 초대 열쇠를 주소창과 방문 기록에서 뺀다.
      history.replaceState(null, '', '#family/invite/used')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setPending(false)
    }
  }
  return <>
    <FamilyHeader title="가족 보호 초대" onBack={() => go('')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      {done ? <>
        <div className="family-hero">
          <span className="family-hero-icon done" aria-hidden="true">✓</span>
          <h2>가족과 연결됐어요</h2>
          <p>가족이 문자 확인을 요청하면 알려드릴게요. 알림을 켜 두면 바로 받을 수 있어요.</p>
        </div>
        <div className="family-panel family-menu"><PushToggle /></div>
        <button className="primary-button" onClick={() => go('family', true)}>가족 보호로 가기</button>
      </> : error && !preview ? <>
        <p className="error-message" role="alert">{error}</p>
        <button className="primary-button" onClick={() => go('')}><Icon name="home" />홈으로</button>
      </> : !preview ? <p role="status">초대를 확인하고 있어요.</p> : <form onSubmit={accept}>
        <div className="family-hero">
          <span className="family-hero-icon" aria-hidden="true"><Icon name="people" /></span>
          <h2>가족 보호 초대가 왔어요</h2>
          <p>가족이 회원님을 "{preview.guardian_name}"(으)로 등록했어요. 수락하면 가족이 보낸 문자 확인 요청을 받고 의견을 보낼 수 있어요.</p>
        </div>
        <label className="field-label" htmlFor="protected-name">초대한 가족을 뭐라고 부를까요?</label>
        <input id="protected-name" className="family-input" value={name} maxLength={20} required autoComplete="off"
          placeholder="예: 엄마" onChange={e => setName(e.target.value)} />
        <p className="hint">받는 내용은 위험 단계와 위험 요소뿐이에요. 가족이 받은 문자 원문과 링크 주소는 오지 않아요.</p>
        {error && <p className="error-message" role="alert">{error}</p>}
        <button className="primary-button family-submit" disabled={pending || !name.trim()}>수락하기</button>
      </form>}
    </main>
  </>
}

function AutoAlertPage({ go, titleRef }: PageProps) {
  const family = useFamily()
  const summary = family.summary
  const guardians = summary?.links.filter(link => link.role === 'guardian' && link.status === 'connected') ?? []
  const enabled = !!summary?.auto_alert.enabled
  const [choice, setChoice] = useState<string>(summary?.auto_alert.link_id ?? guardians[0]?.id ?? '')
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (!choice && guardians[0]) setChoice(guardians[0].id)
  }, [choice, guardians])
  async function save(linkId: string | null) {
    setPending(true)
    setMessage('')
    try {
      await family.actions.setAutoAlert(linkId)
      setMessage(linkId ? '자동 알림을 켰어요.' : '자동 알림을 껐어요.')
    } catch (e) {
      setMessage(errorText(e))
    } finally {
      setPending(false)
    }
  }
  return <>
    <FamilyHeader title="위험 메시지 자동 알림" onBack={() => go('family')} titleRef={titleRef} />
    <main id="main" tabIndex={-1} className="flow-main family-main">
      <p className={`family-chip ${enabled ? 'connected' : 'pending'} family-state`}>{enabled ? '● 켜짐' : '○ 꺼짐'}</p>
      <section className="family-panel">
        <h2>위험한 결과가 나오면 가족에게 자동으로 알릴까요?</h2>
        <p>분석 결과가 '위험'이면 공유 버튼을 누르지 않아도 고른 가족에게 바로 알려요.</p>
      </section>
      <section className="family-panel family-consent" aria-labelledby="send-title">
        <h3 id="send-title">가족에게 보내는 내용</h3>
        <ul><li><span aria-hidden="true">✓</span> 위험 단계</li><li><span aria-hidden="true">✓</span> 발견된 위험 요소의 이름</li></ul>
        <h3>보내지 않는 내용</h3>
        <ul className="not-sent">
          <li><span aria-hidden="true">✕</span> 입력한 문자 원문과 사진</li>
          <li><span aria-hidden="true">✕</span> 링크 주소와 보낸 번호</li>
          <li><span aria-hidden="true">✕</span> 내 위치와 연락처 목록</li>
        </ul>
      </section>
      {guardians.length === 0 ? <>
        <p className="instruction-panel">먼저 가족을 연결하고, 가족이 초대를 수락해야 켤 수 있어요.</p>
        <button className="primary-button" onClick={() => go('family/connect')}>가족 연결하기</button>
      </> : <>
        <fieldset className="family-fieldset">
          <legend className="field-label">받는 가족</legend>
          {guardians.map(link => <label key={link.id} className={`family-option${choice === link.id ? ' selected' : ''}`}>
            <input type="radio" name="auto-target" checked={choice === link.id} onChange={() => setChoice(link.id)} />
            <Avatar name={link.name} /> {link.name}{link.relation && ` (${relationLabels[link.relation]})`}
          </label>)}
        </fieldset>
        {enabled && choice !== summary?.auto_alert.link_id &&
          <button className="secondary-button" disabled={pending} onClick={() => save(choice)}>받는 가족 바꾸기</button>}
        {enabled
          ? <button className="secondary-button family-submit" disabled={pending} onClick={() => save(null)}>자동 알림 끄기</button>
          : <button className="primary-button family-submit" disabled={pending || !choice} onClick={() => save(choice)}>동의하고 자동 알림 켜기</button>}
      </>}
      <p className="family-feedback" role="status">{message}</p>
    </main>
  </>
}

