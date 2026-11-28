import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { VoiceGuide } from './VoiceGuide'
import { buildSpeechSections } from '../speechScript'
import { shareFixture } from '../test/shareFixture'
const result = shareFixture()
let spoken: SpeechSynthesisUtterance[]
const cancel = vi.fn(), pause = vi.fn(), resume = vi.fn(), getVoices = vi.fn()
const listen = () => screen.getByRole('button', { name: '분석 결과와 대처 방법 듣기' })
const toggle = () => screen.getByRole('button', { name: /음성 안내 (일시정지|계속 듣기)/ })
function event(item: SpeechSynthesisUtterance, name: 'onstart' | 'onend' | 'onerror') {
  act(() => (item[name] as ((event: Event) => void) | null)?.(new Event('speech')))
}
beforeEach(() => {
  vi.useFakeTimers()
  spoken = []
  vi.clearAllMocks()
  getVoices.mockReturnValue([{ lang: 'ko-KR', localService: true }])
  vi.stubGlobal('speechSynthesis', { getVoices, cancel, pause, resume, speak: (item: SpeechSynthesisUtterance) => spoken.push(item) })
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(public text: string) {} })
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

test('자동 재생 없이 시작하고 일시정지·계속 듣기는 현재 발화 위치를 유지한다', () => {
  render(<VoiceGuide result={result} />)
  expect(spoken).toHaveLength(0)
  expect(screen.getAllByRole('button')).toHaveLength(1)
  fireEvent.click(listen())
  expect(toggle()).not.toHaveClass('is-playing')
  event(spoken[0], 'onstart')
  expect(toggle()).toHaveClass('is-playing')
  fireEvent.click(toggle())
  expect(pause).toHaveBeenCalledOnce()
  expect(toggle()).toHaveAccessibleName('음성 안내 계속 듣기')
  expect(screen.getAllByRole('button')).toHaveLength(1)
  expect(toggle()).not.toHaveClass('is-playing')
  act(() => vi.advanceTimersByTime(15000))
  fireEvent.click(toggle())
  expect(resume).toHaveBeenCalledOnce()
  expect(spoken).toHaveLength(1)
  expect(toggle()).toHaveClass('is-playing')
})

test('연속 누름은 중복 재생하지 않고 결과 변경 후 이전 이벤트를 무시한다', () => {
  const { rerender } = render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  for (let i = 0; i < 6; i++) fireEvent.click(toggle())
  expect(spoken).toHaveLength(1)
  rerender(<VoiceGuide result={{ ...result }} />)
  expect(cancel).toHaveBeenCalledOnce()
  event(spoken[0], 'onend')
  event(spoken[0], 'onerror')
  act(() => vi.advanceTimersByTime(12000))
  expect(spoken).toHaveLength(1)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  fireEvent.click(listen())
  expect(spoken[1].text).toBe(spoken[0].text)
})

test('문단 사이의 쉼·일시정지·완료와 처음부터 재생을 처리한다', () => {
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  event(spoken[0], 'onstart')
  event(spoken[0], 'onend')
  act(() => vi.advanceTimersByTime(200))
  expect(spoken).toHaveLength(1)
  fireEvent.click(toggle())
  act(() => vi.advanceTimersByTime(2000))
  expect(spoken).toHaveLength(1)
  fireEvent.click(toggle())
  expect(spoken).toHaveLength(2)
  expect(resume).toHaveBeenCalledOnce()
  const count = buildSpeechSections(result).length
  for (let i = 1; i < count; i++) {
    event(spoken[i], 'onstart')
    event(spoken[i], 'onend')
    act(() => vi.advanceTimersByTime(350))
  }
  expect(listen()).toBeVisible()
  expect(screen.queryByRole('button', { name: '음성 안내 종료' })).not.toBeInTheDocument()
  fireEvent.click(listen())
  expect(spoken[count].text).toBe(spoken[0].text)
})

test('마지막 문단 종료와 쉼 사이에 일시정지해도 계속 듣기 후 정상 종료한다', () => {
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  const count = buildSpeechSections(result).length
  for (let i = 0; i < count; i++) {
    event(spoken[i], 'onstart')
    event(spoken[i], 'onend')
    if (i < count - 1) act(() => vi.advanceTimersByTime(350))
  }
  fireEvent.click(toggle())
  fireEvent.click(toggle())
  expect(listen()).toBeVisible()
})

test('새 결과가 같은 request_id로 전달되어도 이전 안내와 대기 문단을 취소한다', () => {
  const { rerender, unmount } = render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  event(spoken[0], 'onend')
  rerender(<VoiceGuide result={{ ...result, risk_level: 'dangerous' }} />)
  expect(cancel).toHaveBeenCalledOnce()
  act(() => vi.advanceTimersByTime(1000))
  expect(spoken).toHaveLength(1)
  fireEvent.click(listen())
  expect(spoken[1].text).toContain('위험 단계입니다')
  unmount()
  expect(cancel).toHaveBeenCalledTimes(2)
})

test('화면 숨김 시 일시정지된 음성도 취소하고 다시 누르면 처음부터 시작한다', () => {
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  fireEvent.click(toggle())
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  fireEvent(document, new Event('visibilitychange'))
  expect(cancel).toHaveBeenCalledOnce()
  expect(listen()).toBeVisible()
  hidden.mockRestore()
})

test.each(['error', 'throw', 'timeout'])('음성 실패(%s)는 화면 안내를 권하며 재시도할 수 있다', mode => {
  if (mode === 'throw') vi.stubGlobal('speechSynthesis', { getVoices, cancel, pause, resume, speak: () => { throw new Error('blocked') } })
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  if (mode === 'error') event(spoken[0], 'onerror')
  if (mode === 'timeout') act(() => vi.advanceTimersByTime(10000))
  expect(screen.getByRole('status')).toHaveTextContent('음성 안내를 재생하지 못했어요. 화면의 안내를 확인해 주세요.')
  expect(listen()).toBeEnabled()
})

test('한국어 음성이 없으면 재생하지 않으며 재시도 때 목록을 다시 확인한다', () => {
  getVoices.mockReturnValue([{ lang: 'en-US' }])
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  expect(spoken).toHaveLength(0)
  expect(screen.getByRole('status')).toHaveTextContent('화면의 안내를 확인해 주세요')
  getVoices.mockReturnValue([{ lang: 'ko-KR', localService: false }])
  fireEvent.click(listen())
  expect(spoken[0].voice?.localService).toBe(false)
  expect(spoken[0].rate).toBe(1)
})

test('지원하지 않는 브라우저에서는 안내만 표시한다', () => {
  vi.stubGlobal('speechSynthesis', undefined)
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  expect(screen.getByRole('status')).toHaveTextContent('음성 안내를 재생하지 못했어요')
})

test('일시정지 후 화면을 숨겨도 브라우저 pause 상태가 남지 않고 다음 재생을 시작한다', () => {
  render(<VoiceGuide result={result} />)
  fireEvent.click(listen())
  event(spoken[0], 'onstart')
  fireEvent.click(toggle())
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  fireEvent(document, new Event('visibilitychange'))
  hidden.mockRestore()
  expect(cancel).toHaveBeenCalledOnce()
  expect(resume).toHaveBeenCalledOnce()
  fireEvent.click(listen())
  event(spoken[1], 'onstart')
  expect(toggle()).toHaveClass('is-playing')
})
