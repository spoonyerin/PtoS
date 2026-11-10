import { expect, test } from 'vitest'
import { selectKoreanVoice } from './speechVoice'
const voice = (name: string, localService = true, lang = 'ko-KR') => ({ name, localService, lang }) as SpeechSynthesisVoice

test.each(['natural', 'neural', 'online', 'wavenet', 'premium', 'enhanced', 'siri'])('%s 이름에 가산점을 주고 영어 음성은 제외한다', name => {
  const preferred = voice(`Korean ${name.toUpperCase()}`)
  expect(selectKoreanVoice([voice('Heami'), voice('English Neural', false, 'en-US'), preferred])).toBe(preferred)
})
test('이름·온라인·ko-KR 점수를 합산한다', () => {
  const preferred = voice('Korean Neural', false)
  expect(selectKoreanVoice([voice('Heami'), voice('Korean Neural'), voice('Korean', false), preferred])).toBe(preferred)
  expect(selectKoreanVoice([voice('Korean'), voice('Korean', false)])?.localService).toBe(false)
})
test('지역이 없는 한국어도 지원하고 같은 점수에서는 순서를 유지한다', () => {
  const first = voice('First', true, 'ko')
  expect(selectKoreanVoice([first, voice('Second', true, 'ko')])).toBe(first)
  expect(selectKoreanVoice([first, voice('Korean')])?.lang).toBe('ko-KR')
  expect(selectKoreanVoice([])).toBeUndefined()
})
