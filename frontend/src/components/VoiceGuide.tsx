import { useEffect, useRef, useState } from 'react'
import type { AnalysisResponse } from '../api/types'
import { buildSpeechSections } from '../speechScript'
import { selectKoreanVoice } from '../speechVoice'

export function VoiceGuide({ result }: { result: AnalysisResponse }) {
  const [state, setState] = useState<'idle' | 'starting' | 'playing'>('idle')
  const [message, setMessage] = useState('')
  const session = useRef(0)
  const active = useRef(false)
  const utterance = useRef<SpeechSynthesisUtterance | null>(null)

  const available =
    typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && 'SpeechSynthesisUtterance' in window

  function stop() {
    session.current++

    if (active.current && available) {
      window.speechSynthesis.cancel()
    }

    active.current = false
    utterance.current = null
    setState('idle')
  }

  useEffect(() => {
    const synth = available ? window.speechSynthesis : null

    // 음성 목록을 준비하되 자동으로 재생하지 않습니다.
    synth?.getVoices()

    const hide = () => {
      if (document.hidden) stop()
    }

    document.addEventListener('visibilitychange', hide)

    return () => {
      session.current++

      if (active.current) synth?.cancel()

      active.current = false
      utterance.current = null
      document.removeEventListener('visibilitychange', hide)
    }
  }, [available])

  function start() {
    if (active.current) {
      stop()
      return
    }

    setMessage('')

    if (!available) {
      setMessage(
        '이 브라우저에서는 음성안내를 지원하지 않아요. 화면의 안내를 확인해 주세요.',
      )
      return
    }

    const synth = window.speechSynthesis

    // 재생할 때 최신 목록을 평가합니다. 온라인 음성도 후보에 포함합니다.
    const voice = selectKoreanVoice(synth.getVoices())

    if (!voice) {
      setMessage(
        '기기의 한국어 음성이 준비되지 않았어요. 한국어 음성을 설치하거나 잠시 후 다시 눌러 주세요.',
      )
      return
    }

    const id = ++session.current
    const sections = buildSpeechSections(result)

    active.current = true
    setState('starting')

    function speak(index: number) {
      if (id !== session.current) return

      if (index >= sections.length) {
        active.current = false
        utterance.current = null
        setState('idle')
        return
      }

      const item = new SpeechSynthesisUtterance(sections[index])
      item.voice = voice!
      item.lang = 'ko-KR'
      item.rate = 1.05

      item.onstart = () => {
        if (id === session.current) setState('playing')
      }

      item.onend = () => speak(index + 1)

      item.onerror = () => {
        if (id !== session.current) return

        stop()
        setMessage('음성안내를 재생하지 못했어요. 다시 눌러 주세요.')
      }

      utterance.current = item

      try {
        synth.speak(item)
      } catch {
        if (id !== session.current) return

        stop()
        setMessage('음성안내를 재생하지 못했어요. 다시 눌러 주세요.')
      }
    }

    speak(0)
  }

  const playing = state === 'playing'
  const busy = state !== 'idle'

  return (
    <>
      <button
        type="button"
        className={`voice-control${playing ? ' is-playing' : ''}`}
        aria-label={busy ? '음성안내 멈춤' : '음성안내 듣기'}
        aria-pressed={busy}
        onClick={start}
      >
        <span className="voice-disc" aria-hidden="true">
          <span
            className={`voice-glyph ${busy ? 'voice-stop' : 'voice-ear'}`}
          />
        </span>
        <span>{busy ? '멈춤' : '듣기'}</span>
      </button>

      {message && (
        <p className="voice-feedback" role="status">
          {message}
        </p>
      )}
    </>
  )
}
