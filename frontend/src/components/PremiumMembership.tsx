import { useEffect, useRef } from 'react'
import { Icon } from './Icons'

const features = [
  { name: '가족에게 도움 요청', description: '버튼 하나로 분석 결과를 가족에게 전송해요.', icon: 'icon-sent.svg' },
  { name: '위험 메시지 자동 알림', description: '‘위험’이 나오면 가족에게 자동으로 알려요.', icon: null },
  { name: '가족 보호 기록', description: '가족과 함께 확인한 내용을 모아봐요.', icon: 'icon-timer.svg' },
  { name: '공식 확인 가이드', description: '기관 및 은행의 공식 대응 방법을 확인해요.', icon: 'icon-user_check.svg' },
]

export function PremiumMembership({ active, onBack, onActivate, onConnect, pending = false }: {
  pending?: boolean
  active: boolean
  onBack: () => void
  onActivate: () => void
  onConnect: () => void
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus(); window.scrollTo(0, 0) }, [active])

  return <>
    <header className="page-header premium-header">
      <button type="button" className="icon-button" aria-label="홈으로 돌아가기" onClick={onBack}><Icon name="back" /></button>
      <h1>가족 보호 프리미엄</h1>
    </header>
    <main id="main" tabIndex={-1} className={`premium-main${active ? ' is-active' : ''}`}>
      <section className="premium-intro" aria-labelledby="premium-title">
        <span className={`premium-emblem${active ? ' is-active' : ''}`} aria-hidden="true">
          {active ? <span className="premium-check-weight"><span className="premium-asset" style={{ maskImage: "url('/assets/icon-check.svg')", WebkitMaskImage: "url('/assets/icon-check.svg')" }} /></span>
            : <span className="premium-asset" style={{ maskImage: "url('/assets/icon-user_shield.svg')", WebkitMaskImage: "url('/assets/icon-user_shield.svg')" }} />}
        </span>
        <h2 id="premium-title" ref={heading} tabIndex={-1}>{active ? '프리미엄이 시작됐어요!' : '가족과 함께 사기를 막아요!'}</h2>
        <p>{active ? <>바로 가족을 연결해보세요. 위험한 문자를<br className="premium-copy-break" /> 함께 확인하고 방지할 수 있어요.</> : <>위험한 문자가 오면 가족에게 바로 물어보고,<br className="premium-copy-break" /> 가족의 의견을 받아볼 수 있어요.</>}</p>
      </section>

      <section className="premium-features" aria-labelledby="premium-features-title">
        <h2 id="premium-features-title">{active ? '지금부터 사용할 수 있어요!' : '프리미엄 한정 기능'}</h2>
        <ul>
          {features.map(feature => <li key={feature.name}>
            <span className="premium-feature-icon" aria-hidden="true">
              {feature.icon ? <span className={`premium-asset${feature.icon === 'icon-sent.svg' ? ' premium-send-asset' : ''}`} style={{ maskImage: `url('/assets/${feature.icon}')`, WebkitMaskImage: `url('/assets/${feature.icon}')` }} /> : <Icon name="bell" />}
            </span>
            <div><h3>{feature.name}</h3>{!active && <p>{feature.description}</p>}</div>
          </li>)}
        </ul>
      </section>

      {!active && <div className="premium-price"><strong>이용 금액</strong><span>시연용 · 실제 결제 없음</span></div>}
      <div className="premium-actions">
        {!active && <p id="premium-payment-note" className="premium-payment-note">시연용 가입 상태를 서버에 저장합니다. 실제 결제는 발생하지 않습니다.</p>}
        <button type="button" className="primary-button premium-primary" disabled={pending} aria-label={!active ? '프리미엄 시작하기 (시연용)' : undefined}
          aria-describedby={!active ? 'premium-payment-note' : undefined} onClick={active ? onConnect : onActivate}>
          {active ? '지금 가족 연결하기' : '프리미엄 가입하기'}
        </button>
      </div>
    </main>
  </>
}
