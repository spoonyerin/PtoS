import { useState, type ReactNode, type Ref } from 'react'
import type { FactorCode, FamilyRequestItem } from '../../api/family'
import type { RiskLevel } from '../../api/types'
import { useFamily } from '../../hooks/useFamily'
import { useFamilyStatus } from '../../hooks/useServiceStatus'
import { pushSupport } from '../../family/push'
import { factorLabels, formatTime, initial, replyText } from '../../family/labels'
import { factorDisplay } from '../../resultPresentation'
import { riskLevels } from '../../riskLevels'
import { GoogleAdvisory } from '../GoogleAdvisory'
import { Icon } from '../Icons'

export function FamilyHeader({ title, onBack, titleRef }: { title: string; onBack: () => void; titleRef: Ref<HTMLHeadingElement> }) {
  return <header className="page-header">
    <button className="icon-button" aria-label="뒤로 가기" onClick={onBack}><Icon name="back" /></button>
    <h1 ref={titleRef} tabIndex={-1}>{title}</h1>
  </header>
}

export function Avatar({ name }: { name: string }) {
  return <span className="family-avatar" aria-hidden="true">{initial(name)}</span>
}

// 색만으로 구분하지 않도록 기호와 글자를 함께 보인다.
export function RiskChip({ level }: { level: RiskLevel }) {
  const display = riskLevels[level]
  return <span className={`family-risk-chip ${level}`}>
    <span aria-hidden="true">{display.symbol}</span> {display.label}{level === 'insufficient_information' ? '' : ' 단계'}
  </span>
}

export function FactorList({ codes, level }: { codes: FactorCode[]; level: RiskLevel }) {
  if (!codes.length) {
    return <p className="family-empty">
      {level === 'normal' ? '뚜렷한 위험 신호가 없었어요. 안전을 보장한다는 뜻은 아니에요.' : '확인된 위험 신호가 없어요. 정상이라는 뜻은 아니에요.'}
    </p>
  }
  return <ul className={`evidence-list family-factors result-card ${level}`}>
    {codes.map(code => <li className="evidence-item" key={code}>
      <h4 className="evidence-title">
        <span className="factor-symbol"><img src={`/assets/${factorDisplay[code]?.icon ?? 'risk-people'}.svg`} alt="" /></span>
        {factorLabels[code]}
      </h4>
      <p>{factorDisplay[code]?.description}</p>
      {code === 'URL_REPUTATION_MATCH' && <GoogleAdvisory />}
    </li>)}
  </ul>
}

function Step({ state, title, detail }: { state: 'done' | 'current' | 'waiting'; title: ReactNode; detail: ReactNode }) {
  const label = { done: '완료', current: '진행 중', waiting: '대기' }[state]
  return <li className={`family-step ${state}`}>
    <span className="family-step-mark" aria-hidden="true">{state === 'done' ? '✓' : state === 'current' ? '●' : ''}</span>
    <span>
      <strong><span className="visually-hidden">{label}: </span>{title}</strong>
      <small>{detail}</small>
    </span>
  </li>
}

// 보낸 사람이 보는 진행 상태. 공유 창이 닫힌 것과 달리, 서버가 기록한 확인·의견만 표시한다.
export function RequestTimeline({ item, pushOn }: { item: FamilyRequestItem; pushOn: boolean }) {
  return <ol className="family-timeline">
    <Step state="done" title={item.auto ? '자동 알림으로 가족에게 보냈어요.' : '가족에게 보냈어요.'} detail={formatTime(item.created_at)} />
    <Step state={item.viewed_at ? 'done' : 'current'}
      title={item.viewed_at ? `${item.name} 님이 확인했어요.` : `${item.name} 님이 확인하는 중`}
      detail={item.viewed_at ? formatTime(item.viewed_at) : '아직 확인 전이에요.'} />
    <Step state={item.reply ? 'done' : 'waiting'} title="의견 도착"
      detail={item.reply ? formatTime(item.reply.replied_at)
        : pushOn ? '의견이 도착하면 바로 알려드릴게요.' : '의견이 도착하면 가족 보호 기록에서 볼 수 있어요.'} />
  </ol>
}

export function ReplyCard({ item }: { item: FamilyRequestItem }) {
  if (!item.reply) return null
  return <section className="family-reply" aria-labelledby={`reply-${item.id}`}>
    <h3 id={`reply-${item.id}`}>{item.name} 님의 의견</h3>
    <p className="family-reply-text">{replyText(item.reply)}</p>
    <p className="hint">가족이 보낸 의견이에요. PtoS 분석 결과가 아니고 안전을 보장하지 않아요.</p>
  </section>
}

export function WaitWarning() {
  return <p className="family-warning" role="note">
    <span aria-hidden="true">⚠</span> 답이 올 때까지 문자 속 지시를 따르거나 링크를 누르지 마세요.
  </p>
}

export function PushToggle() {
  const family = useFamily()
  const { push } = useFamilyStatus()
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const support = pushSupport()
  const on = !!family.summary?.push_subscribed
  async function toggle() {
    setPending(true)
    setMessage('')
    try {
      if (on) {
        await family.disablePush()
        setMessage('이 휴대폰의 알림을 껐어요.')
      } else {
        await family.enablePush()
        setMessage('이 휴대폰에서 알림을 받을 수 있어요.')
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '알림 설정을 바꾸지 못했어요.')
    } finally {
      setPending(false)
    }
  }
  const unavailable = push !== 'live' ? '이 서버에서는 알림을 보낼 수 없어요. 가족 보호 기록에서 확인해 주세요.'
    : support === 'ios-install' ? 'iPhone은 Safari 공유 버튼 → "홈 화면에 추가"로 설치한 뒤 그 앱에서 알림을 켤 수 있어요.'
      : support === 'insecure' ? '알림은 https 주소에서만 켤 수 있어요.'
        : support === 'unsupported' ? '이 브라우저는 알림을 지원하지 않아요. 가족 보호 기록에서 확인해 주세요.' : ''
  return <div className="family-row">
    <span>
      <strong>이 휴대폰에서 알림 받기</strong>
      <small>{unavailable || '가족의 요청과 의견이 오면 알림으로 알려드려요. 알림에는 결과 내용을 넣지 않아요.'}</small>
    </span>
    {!unavailable && <button type="button" className={`family-switch${on ? ' on' : ''}`} aria-pressed={on}
      disabled={pending} onClick={toggle}>{on ? '켜짐' : '꺼짐'}</button>}
    <p className="family-feedback" role="status">{message}</p>
  </div>
}
