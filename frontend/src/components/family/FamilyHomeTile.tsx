import { useFamily } from '../../hooks/useFamily'
import { readDeviceToken } from '../../family/deviceToken'
import { Icon } from '../Icons'

export function FamilyHomeTile({ go }: { go: (hash: string) => void }) {
  const family = useFamily()
  const summary = family.summary
  const premium = !!summary?.premium
  const connected = summary?.links.filter(link => link.role === 'guardian' && link.status === 'connected') ?? []
  const protecting = summary?.links.some(link => link.role === 'protected') ?? false
  const active = premium || protecting
  const unconfirmed = family.available && !summary && !!readDeviceToken()
  const detail = !family.available ? '가족과 함께 의심되는 문자를 확인해요.'
    : family.loading && !summary ? '가족 보호 정보를 확인하고 있어요.'
    : unconfirmed ? '이용 상태를 다시 확인해 주세요.'
    : !active ? '프리미엄 이용권으로 사용할 수 있어요.'
    : connected.length ? `✓ ${connected[0].name} 님${connected.length > 1 ? ` 외 ${connected.length - 1}명` : ''}과 연결 완료`
      : protecting ? '✓ 가족을 지켜 주고 있어요' : '가족을 연결해 보세요.'
  return <button className={`family-protection-card family-tile${active ? ' active' : ''}`} onClick={() => go(!family.available || unconfirmed || active ? 'family' : 'family/premium')}>
    <span className="family-card-top" aria-hidden="true"><span className="family-card-icon"><span className="family-people-glyph" />{family.available && !unconfirmed && !active && <span className="family-card-lock">🔒</span>}</span><Icon name="chevron" /></span>
    <strong>가족 보호</strong>
    <small>{detail}</small>
  </button>
}

// 가족이 보낸 확인 요청이나 의견이 있으면 홈 위쪽에 알려 준다.
export function FamilyNews({ go }: { go: (hash: string) => void }) {
  const { summary } = useFamily()
  if (!summary) return null
  const items = [
    summary.waiting_requests > 0 && { key: 'received', text: `가족이 문자 확인을 요청했어요 (${summary.waiting_requests}건)`, hash: 'family/records/received' },
    summary.new_replies > 0 && { key: 'sent', text: `가족 의견이 도착했어요 (${summary.new_replies}건)`, hash: 'family/records/sent' },
  ].filter(Boolean) as { key: string; text: string; hash: string }[]
  if (!items.length) return null
  return <div className="family-news" role="status">
    {items.map(item => <button key={item.key} className="family-news-item" onClick={() => go(item.hash)}>
      <Icon name="bell" />{item.text}<Icon name="chevron" />
    </button>)}
  </div>
}
