import { useEffect, useRef, useState } from 'react'
import type { AnalysisResponse } from '../api/types'
import { buildSpeechSections } from '../speechScript'
import { selectKoreanVoice } from '../speechVoice'

type Playback = 'idle' | 'starting' | 'playing' | 'paused'
const failure = '음성 안내를 재생하지 못했어요. 화면의 안내를 확인해 주세요.'
export function VoiceGuide({ result, canRecheck = true }: { result: AnalysisResponse; canRecheck?: boolean }) {
  const [state, setState] = useState<Playback>('idle')
  const [message, setMessage] = useState('')
  const session = useRef(0)
  const active = useRef(false)
  const paused = useRef(false)
  const started = useRef(false)
  const utterance = useRef<SpeechSynthesisUtterance | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pending = useRef<(() => void) | null>(null)
  const available = typeof window !== 'undefined' && !!window.speechSynthesis && typeof window.SpeechSynthesisUtterance === 'function'

  function clearTimer() { clearTimeout(timer.current); timer.current = undefined }
  function release() {
    session.current++
    clearTimer()
    pending.current = null
    if (active.current && available) {
      window.speechSynthesis.cancel()
      // cancel()만으로 pause 상태를 해제하지 않는 브라우저도 있습니다.
      if (paused.current) window.speechSynthesis.resume()
    }
    active.current = false
    paused.current = false
    started.current = false
    utterance.current = null
  }
  function stop() { release(); setState('idle'); setMessage('') }
  function fail() { release(); setState('idle'); setMessage(failure) }

  useEffect(() => {
    if (available) window.speechSynthesis.getVoices()
    setState('idle')
    setMessage('')
    const hide = () => { if (document.hidden) stop() }
    document.addEventListener('visibilitychange', hide)
    return () => { release(); document.removeEventListener('visibilitychange', hide) }
  }, [available, result, canRecheck])

  function start() {
    setMessage('')
    if (!available) { setMessage(failure); return }
    const synth = window.speechSynthesis
    const voice = selectKoreanVoice(synth.getVoices())
    if (!voice) { setMessage(failure); return }
    const id = ++session.current
    const sections = buildSpeechSections(result, { canRecheck })
    active.current = true
    paused.current = false
    setState('starting')

    function speak(index: number) {
      if (id !== session.current) return
      pending.current = null
      if (index >= sections.length) {
        active.current = false
        utterance.current = null
        setState('idle')
        return
      }
      started.current = false
      const item = new SpeechSynthesisUtterance(sections[index])
      item.voice = voice!
      item.lang = 'ko-KR'
      // 브라우저 기본 속도이며, 고령자 최적 속도로 단정하지 않습니다. 실청 평가 후 조정합니다.
      item.rate = 1
      const current = () => id === session.current && utterance.current === item
      item.onstart = () => {
        if (!current()) return
        clearTimer()
        started.current = true
        if (paused.current) synth.pause()
        else setState('playing')
      }
      item.onend = () => {
        if (!current()) return
        clearTimer()
        utterance.current = null
        const next = () => speak(index + 1)
        pending.current = next
        if (!paused.current) timer.current = setTimeout(next, 350)
      }
      item.onerror = () => { if (current()) fail() }
      utterance.current = item
      timer.current = setTimeout(() => { if (current() && !paused.current) fail() }, 10000)
      try { synth.speak(item) } catch { if (current()) fail() }
    }
    speak(0)
  }

  function toggle() {
    if (!active.current) { start(); return }
    const synth = window.speechSynthesis
    try {
      if (!paused.current) {
        paused.current = true
        clearTimer()
        synth.pause()
        setState('paused')
      } else {
        paused.current = false
        synth.resume()
        if (pending.current) { const next = pending.current; pending.current = null; next() }
        else {
          if (!started.current) {
            const id = session.current
            timer.current = setTimeout(() => { if (id === session.current && !paused.current) fail() }, 10000)
          }
        }
        if (active.current) setState(started.current ? 'playing' : 'starting')
      }
    } catch { fail() }
  }

  const playing = state === 'playing'
  const busy = state !== 'idle'
  const label = state === 'paused' ? '계속 듣기' : busy ? '일시정지' : '듣기'
  return <>
    <div className="voice-controls" role="group" aria-label="음성 안내 재생 조절">
      <button type="button" className={`voice-control${playing ? ' is-playing' : ''}`}
        aria-label={busy ? `음성 안내 ${label}` : '분석 결과와 대처 방법 듣기'} aria-pressed={busy} onClick={toggle}>
        <span className="voice-disc" aria-hidden="true"><span className={`voice-glyph ${busy && state !== 'paused' ? 'voice-pause' : 'voice-ear'}`} /></span>
        <span>{label}</span>
      </button>
    </div>
    {message && <p className="voice-feedback" role="status">{message}</p>}
  </>
}
