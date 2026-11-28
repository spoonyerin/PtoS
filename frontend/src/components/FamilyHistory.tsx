import { useEffect, useRef, useState } from 'react'
import { GuardianShare } from './GuardianShare'
import { guardianPreview } from '../guardianPreview'
import { Icon } from './Icons'
export type HistoryBox = 'sent' | 'received'
export const initialHistoryReplies: Record<string, string> = { card: '엄마 내가 곧 전화할게', return: '문제 없어 보여요.' }
const examples = [
  { id: 'delivery', date: '2026년 11월 24일', time: '오전 10:01', kind: '문자', level: 'dangerous', label: '위험 단계', title: '택배 주소 재입력 요청' },
  { id: 'card', date: '2026년 11월 19일', time: '오후 8:47', kind: '사진', level: 'suspicious', label: '의심 단계', title: '카드 결제 승인 안내' },
  { id: 'return', date: '2026년 11월 2일', time: '오후 2:15', kind: '링크', level: 'insufficient_information', label: '정보부족', title: '롯데 택배 반품 요청 링크' },
] as const
export function FamilyHistory({ box, onChangeBox, replies, onReply, onBack }: { box: HistoryBox; onChangeBox: (box: HistoryBox) => void; replies: Record<string, string>; onReply: (id: string, reply: string) => void; onBack: () => void }) {
  const [opened, setOpened] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const detail = useRef<HTMLElement>(null)
  useEffect(() => { if (!opened) { heading.current?.focus(); window.scrollTo(0, 0) } else if (box === 'sent') { detail.current?.focus(); detail.current?.scrollIntoView({ block: 'nearest' }) } }, [box, opened])
  useEffect(() => { setOpened(null) }, [box])
  const record = examples.find(row => row.id === opened)
  if (record && box === 'received') return <GuardianShare request={record.id === 'delivery' ? guardianPreview : { ...guardianPreview, summary: `${record.title}에 대한 가족의 확인 요청입니다.`, requestedAt: `${record.date} ${record.time}`, maskedSender: '확인 정보 없음', linkCount: 0, riskLevel: record.level, factors: [] }} initialReply={replies[record.id]} onReply={reply => onReply(record.id, reply)} onBack={() => setOpened(null)} onHistory={() => setOpened(null)} />
  return <>
    <header className="page-header family-history-header"><button className="icon-button" aria-label="가족 보호로 돌아가기" onClick={onBack}><Icon name="back" /></button><h1 ref={heading} tabIndex={-1}>가족 보호 기록</h1></header>
    <div className="history-tabs" role="tablist" aria-label="가족 보호 기록 관점">{([['received', '받은 요청'], ['sent', '보낸 요청']] as const).map(([value, label]) => <button key={value} role="tab" tabIndex={box === value ? 0 : -1} id={`history-${value}`} aria-controls="history-content" aria-selected={box === value} onClick={() => { setOpened(null); onChangeBox(value) }} onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { const next = value === 'sent' ? 'received' : 'sent'; onChangeBox(next); document.getElementById(`history-${next}`)?.focus() } }}>{label}</button>)}</div>
    <main id="main" tabIndex={-1} className="family-history-main"><div id="history-content" role="tabpanel" aria-labelledby={`history-${box}`}>
      {(import.meta.env.DEV ? examples : []).map(row => <section className="history-date-group" key={row.id}><h2>{row.date}</h2><article className={`history-request${box === 'received' && !replies[row.id] ? ' is-pending' : ''}`}>
        <button className="history-open" aria-label={`${row.title} ${box === 'received' ? '확인하기' : '상태 보기'}`} onClick={() => setOpened(row.id)}><span className="history-meta"><span className={`history-level ${row.level}`}>{row.label}</span><small>{row.time} · {row.kind}</small>{box === 'received' && !replies[row.id] && <b>확인하기</b>}<Icon name="chevron" /></span><span className="history-subject">{box === 'received' ? <><span className="family-avatar history-mom">엄</span><span><small>엄마</small><strong>{row.title}</strong></span></> : <><span className="history-plane" aria-hidden="true" /><strong>{row.title}</strong></>}</span></button>
        <div className="history-responses">{box === 'received' ? <p><span className="history-plane" aria-hidden="true" /><strong>나</strong>{replies[row.id] && <span>{replies[row.id]}</span>}</p> : <>{row.id === 'delivery' && <p><span className="family-avatar blue">우</span><strong>우리 아들</strong><span>위험해 보여요.</span><span className="history-response-check" aria-label="의견 도착" /></p>}<p><span className="family-avatar">우</span><strong>우리 딸♥</strong><span>{replies[row.id]}</span><span className={`history-response-check${!replies[row.id] ? ' is-waiting' : ''}`} aria-label={replies[row.id] ? '의견 도착' : '의견 대기'} /></p></> }</div>
      </article></section>)}
      {!import.meta.env.DEV && <p>아직 보호 기록이 없어요. 기록 조회 기능은 준비 중입니다.</p>}
    </div>{record && box === 'sent' && <section ref={detail} tabIndex={-1} className="history-detail" role="region" aria-label="보낸 요청 상세"><h2>{record.title}</h2><p>{replies[record.id] ?? '가족이 확인하기를 기다리고 있어요.'}</p><p>화면 확인용 기록입니다. 실제 공유 상태는 서버 연동 후 제공됩니다.</p><button className="family-outline-button" onClick={() => setOpened(null)}>상세 닫기</button></section>}</main>
  </>
}
