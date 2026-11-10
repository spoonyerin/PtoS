import { useState } from 'react'

// Presentation prototype only. No synthesis provider or audio is invoked here.
export function VoiceGuidePreview() {
  const [playing, setPlaying] = useState(false)
  return <>
    <button type="button" className={`voice-control${playing ? ' is-playing' : ''}`}
      aria-label={playing ? '음성안내 멈춤' : '음성안내 듣기'} aria-pressed={playing}
      onClick={() => setPlaying(value => !value)}>
      <span className="voice-disc" aria-hidden="true">
        <span className={`voice-glyph ${playing ? 'voice-stop' : 'voice-ear'}`} />
      </span>
      <span>{playing ? '멈춤' : '듣기'}</span>
    </button>
  </>
}
