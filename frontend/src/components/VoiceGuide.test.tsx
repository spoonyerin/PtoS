import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { VoiceGuide } from './VoiceGuide'
import { buildSpeechSections } from '../speechScript'
const result = { risk_level: 'insufficient_information', risk_factors: [], evidence: [], urls: [], action_guidance: ['별도 확인하세요.', '별도 확인하세요.'], explanation: '비공개 원문' } as unknown as AnalysisResponse
let spoken: SpeechSynthesisUtterance[]
const cancel = vi.fn()
const getVoices = vi.fn()
beforeEach(() => {
  spoken = []
  cancel.mockClear()
  getVoices.mockReturnValue([{ lang: 'ko-KR', localService: true }])
  vi.stubGlobal('speechSynthesis', { getVoices, cancel, speak: (item: SpeechSynthesisUtterance) => spoken.push(item) })
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(public text: string) {} })
})
afterEach(() => vi.unstubAllGlobals())
test('대본은 정보 부족의 한계를 알리고 원문과 URL을 제외하며 대응을 중복 제거한다', () => {
  const sections = buildSpeechSections(result)
  expect(sections[0]).toContain('안전하다는 뜻은 아니에요')
  expect(sections.join(' ')).not.toContain('비공개 원문')
  expect(sections.filter(t => t.includes('별도 확인'))).toHaveLength(1)
  expect(buildSpeechSections({ ...result, action_guidance: ['https://example.invalid/private 를 열지 마세요.'] }).join(' ')).not.toContain('example.invalid')
})
test('수동 시작·실제 재생 이벤트·멈춤·처음부터 재시작과 이전 이벤트 무시', () => {
  render(<VoiceGuide result={result} />)
  expect(spoken).toHaveLength(0)
  fireEvent.click(screen.getByRole('button'))
  expect(screen.getByRole('button')).not.toHaveClass('is-playing')
  act(() => spoken[0].onstart?.({} as SpeechSynthesisEvent))
  expect(screen.getByRole('button')).toHaveClass('is-playing')
  fireEvent.click(screen.getByRole('button'))
  expect(cancel).toHaveBeenCalledOnce()
  act(() => spoken[0].onend?.({} as SpeechSynthesisEvent))
  expect(spoken).toHaveLength(1)
  fireEvent.click(screen.getByRole('button'))
  expect(spoken[1].text).toBe(spoken[0].text)
})
test('온라인 한국어 음성도 선택하고 변경한 속도로 읽는다', () => {
  getVoices.mockReturnValue([{ lang: 'ko-KR', localService: false }])
  render(<VoiceGuide result={result} />)
  fireEvent.click(screen.getByRole('button'))
  expect(spoken).toHaveLength(1)
  expect(spoken[0].voice?.localService).toBe(false)
  expect(spoken[0].rate).toBe(1.05)
})
test('순차 재생 완료와 오류를 처리한다', () => {
  render(<VoiceGuide result={result} />)
  fireEvent.click(screen.getByRole('button'))
  for (let i = 0; i < buildSpeechSections(result).length; i++) act(() => spoken[i].onend?.({} as SpeechSynthesisEvent))
  expect(screen.getByRole('button')).toHaveAccessibleName('음성안내 듣기')
  fireEvent.click(screen.getByRole('button'))
  act(() => spoken.at(-1)!.onerror?.({} as SpeechSynthesisErrorEvent))
  expect(screen.getByRole('status')).toHaveTextContent('재생하지 못했어요')
})
test('화면 숨김과 언마운트 시 취소한다', () => {
  const { unmount } = render(<VoiceGuide result={result} />)
  fireEvent.click(screen.getByRole('button'))
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  fireEvent(document, new Event('visibilitychange'))
  expect(cancel).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button'))
  unmount()
  expect(cancel).toHaveBeenCalledTimes(2)
  hidden.mockRestore()
})

test('위험 요소는 근거 구절 대신 요약을 읽고 결과 다음에 대응을 안내한다', () => {
  const sections = buildSpeechSections({ ...result, risk_level: 'dangerous', risk_factors: ['인증번호·개인정보 요구'], evidence: [{ factor_code: 'CREDENTIAL_REQUEST', label: '인증번호·개인정보 요구', snippet: '개인 비밀 원문' }] as AnalysisResponse['evidence'] })
  expect(sections[0]).toContain('위험 단계')
  expect(sections.join(' ')).not.toContain('개인 비밀 원문')
  expect(sections[1]).toContain('어떤 위험 신호가 있는지 살펴볼게요. 인증번호·개인정보 요구.')
  expect(sections[1]).toContain('인증번호나 개인정보를 전달·입력하라는 요구가 있어요.')
  expect(sections[2]).toContain('이제 어떻게 대응하면 좋을지 알려드릴게요. 별도 확인하세요.')
})

test('지원하지 않는 브라우저에서는 안내만 표시한다', () => {
  vi.stubGlobal('speechSynthesis', undefined)
  // 미지원 브라우저는 속성 자체가 없다.
  Reflect.deleteProperty(window, 'speechSynthesis')
  render(<VoiceGuide result={result} />)
  fireEvent.click(screen.getByRole('button'))
  expect(screen.getByRole('status')).toHaveTextContent('지원하지 않아요')
})


test('결과 설명과 각 대응을 한 덩어리로 묶고 순서를 말로 안내한다', () => {
  const sections = buildSpeechSections({ ...result, action_guidance: ['송금하지 마세요.', '공식 연락처로 확인하세요.'] })
  expect(sections).toHaveLength(5)
  expect(sections[2]).toBe('이제 어떻게 대응하면 좋을지 알려드릴게요. 첫 번째로, 송금하지 마세요.')
  expect(sections[3]).toBe('두 번째로, 공식 연락처로 확인하세요.')
})

test('정상 결과도 안전을 보장하지 않고 대응이 없으면 별도 확인을 안내한다', () => {
  const sections = buildSpeechSections({ ...result, risk_level: 'normal', action_guidance: [] })
  expect(sections[0]).toContain('안전을 보장하는 것은 아니니')
  expect(sections[1]).toContain('요청 출처를 별도로 확인해 주세요.')
})


test('한국어 음성이 없으면 다른 언어로 재생하지 않고 재시도 때 목록을 다시 확인한다', () => {
  getVoices.mockReturnValue([{ name: 'English Neural', lang: 'en-US', localService: false }])
  render(<VoiceGuide result={result} />)
  fireEvent.click(screen.getByRole('button'))
  expect(spoken).toHaveLength(0)
  expect(screen.getByRole('status')).toHaveTextContent('한국어 음성이 준비되지')
  getVoices.mockReturnValue([{ name: 'Korean', lang: 'ko-KR', localService: true }])
  fireEvent.click(screen.getByRole('button'))
  expect(spoken).toHaveLength(1)
})
