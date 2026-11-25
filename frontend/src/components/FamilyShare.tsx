import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { AnalysisResponse } from '../api/types'
import { useFamily } from '../hooks/useFamily'
import { buildShareText } from '../shareResult'
import { FamilySendSheet, factorCodes } from './family/FamilySendSheet'
import { Icon } from './Icons'

export function FamilyShare({ result, large, go }: { result: AnalysisResponse; large: boolean; go: (hash: string) => void }) {
  const family = useFamily()
  const [open, setOpen] = useState<false | 'family' | 'share'>(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)
  // 가족 보호(시연용 프리미엄)로 연결한 가족이 있으면 앱 안에서 보내고, 아니면 공유 앱·복사로 보낸다.
  const inApp = family.available && !!family.summary?.premium && family.summary.links.some(link => link.role === 'guardian')
  useEffect(() => {
    // Restore after the modal is removed; focusing outside an open modal is blocked.
    if (!open && wasOpen.current) trigger.current?.focus()
    wasOpen.current = !!open
  }, [open])
  function close() {
    setOpen(false)
  }
  return <>
    <button className="primary-button" ref={trigger} onClick={() => setOpen(inApp ? 'family' : 'share')}>
      <Icon name="share" />가족에게 공유
    </button>
    {open === 'family' && createPortal(
      <FamilySendSheet key={result.request_id} result={result} large={large} onClose={close} go={go}
        onOtherShare={() => setOpen('share')} />,
      document.body,
    )}
    {open === 'share' && createPortal(
      <ShareSheet key={result.request_id} text={buildShareText(result)} large={large} onClose={close} />,
      document.body,
    )}
  </>
}

// 같은 결과를 두 번 자동으로 보내지 않도록 이번 화면에서 보낸 결과만 메모리에 기억한다(저장하지 않음).
const autoSent = new Set<string>()

// 사용자가 동의해 켠 경우에만, '위험' 결과를 고른 가족에게 자동으로 보낸다. 위험 단계와 위험 요소 코드만 보낸다.
export function FamilyAutoAlert({ result }: { result: AnalysisResponse }) {
  const family = useFamily()
  const [message, setMessage] = useState('')
  const auto = family.summary?.auto_alert
  const target = family.summary?.links.find(link => link.id === auto?.link_id)
  useEffect(() => {
    if (!family.available || !family.summary?.premium || !auto?.enabled || !auto.link_id || !target) return
    if (result.risk_level !== 'dangerous' || autoSent.has(result.request_id)) return
    autoSent.add(result.request_id)
    family.actions.sendRequests({ link_ids: [auto.link_id], risk_level: result.risk_level, factor_codes: factorCodes(result), auto: true })
      .then(() => setMessage(`자동 알림이 켜져 있어 ${target.name} 님에게 위험 단계와 위험 요소를 보냈어요. 원문과 링크 주소는 보내지 않았어요.`))
      .catch(() => setMessage('자동 알림을 보내지 못했어요. "가족에게 공유"로 직접 보내 주세요.'))
  }, [family.available, family.summary?.premium, auto?.enabled, auto?.link_id, target, result, family.actions])
  if (!message) return null
  return <p className="family-auto-notice" role="status">{message}</p>
}

function ShareSheet({ text, large, onClose }: { text: string; large: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const preview = useRef<HTMLTextAreaElement>(null)
  const busy = useRef(false)
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState('')
  const shareData = { title: 'PtoS 분석 결과', text }
  const canShare = window.isSecureContext && typeof navigator.share === 'function'
  useEffect(() => {
    const node = dialog.current!
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    node.showModal()
    return () => {
      node.close()
      document.body.style.overflow = overflow
    }
  }, [])
  async function share() {
    if (busy.current) return
    busy.current = true
    setPending(true)
    setNotice('')
    try {
      if (navigator.canShare && !navigator.canShare(shareData)) {
        setNotice('이 환경에서는 공유 창을 열 수 없어요. 복사하기를 이용해 주세요.')
        return
      }
      // Call directly from a click, preserving the browser's user activation.
      await navigator.share(shareData)
    } catch (error) {
      setNotice(error instanceof Error && error.name === 'AbortError'
        ? '공유를 취소했어요. 다시 공유하거나 내용을 복사할 수 있어요.'
        : '공유 창을 열지 못했어요. 복사하기를 이용해 주세요.')
    } finally {
      busy.current = false
      setPending(false)
    }
  }
  async function copy() {
    if (busy.current) return
    busy.current = true
    setPending(true)
    setNotice('')
    try {
      if (!window.isSecureContext || !navigator.clipboard?.writeText) throw new Error('unavailable')
      await navigator.clipboard.writeText(text)
      setNotice('내용을 복사했어요. 카카오톡이나 문자에 붙여넣어 보내세요.')
    } catch {
      preview.current?.focus()
      preview.current?.select()
      setNotice('자동 복사를 할 수 없어요. 선택된 내용을 길게 누르거나 Ctrl+C로 복사해 주세요.')
    } finally {
      busy.current = false
      setPending(false)
    }
  }
  return <dialog ref={dialog} className={`share-sheet${large ? ' share-sheet-large' : ''}`}
    aria-labelledby="share-title" aria-describedby="share-description"
    onCancel={event => { event.preventDefault(); onClose() }}
    onClick={event => { if (event.target === event.currentTarget) onClose() }}
    onKeyDown={event => {
      if (event.key !== 'Tab') return
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), textarea'))
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }}>
    <div className="share-sheet-content">
      <header className="share-sheet-header">
        <h2 id="share-title">가족에게 공유하기</h2>
        <button type="button" className="icon-button" aria-label="공유 창 닫기" onClick={onClose}>
          <Icon name="close" />
        </button>
      </header>
      <p id="share-description">보낼 내용을 먼저 확인하세요.</p>
      <textarea ref={preview} className="share-preview" aria-label="공유할 내용" readOnly value={text} spellCheck={false} />
      {!canShare && <p className="share-help">이 브라우저에서는 앱 선택 공유를 지원하지 않아요. 내용을 복사해 보내세요.</p>}
      <div className="share-sheet-actions">
        <button type="button" className="primary-button" disabled={!canShare || pending} onClick={share}>
          <Icon name="share" />공유할 앱 선택
        </button>
        <button type="button" className="primary-button" disabled={pending} onClick={copy}>
          <Icon name="copy" />복사하기
        </button>
      </div>
      <p role="status" className="share-feedback" aria-atomic="true">{pending ? '처리 중이에요.' : notice}</p>
    </div>
  </dialog>
}
