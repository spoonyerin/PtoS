import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { AnalysisResponse } from '../api/types'
import { buildShareText } from '../shareResult'
import { Icon } from './Icons'

export function FamilyShare({ result, large }: { result: AnalysisResponse; large: boolean }) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)
  useEffect(() => {
    // Restore after the modal is removed; focusing outside an open modal is blocked.
    if (!open && wasOpen.current) trigger.current?.focus()
    wasOpen.current = open
  }, [open])
  function close() {
    setOpen(false)
  }
  return <>
    <button className="primary-button" ref={trigger} onClick={() => setOpen(true)}>
      <Icon name="share" />가족에게 공유
    </button>
    {open && createPortal(
      <ShareSheet key={result.request_id} text={buildShareText(result)} large={large} onClose={close} />,
      document.body,
    )}
  </>
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
      setNotice('공유 창을 닫았어요. 전송 여부는 선택한 앱에서 확인해 주세요.')
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
