import { requestAnalysis } from './client'

const body = { input_type: 'text', content: '문자' } as const

test.each([
  [200, 'not json', '서버 응답을 읽지 못했어요'],
  [200, JSON.stringify({ risk_level: 'unknown' }), '결과 형식을 확인하지 못했어요'],
  [422, '{}', '입력 내용을 확인해주세요'],
  [429, '{}', '요청이 많아요'],
  [504, '{}', '서버에서 분석을 완료하지 못했어요'],
])('HTTP %s 응답을 안전한 안내로 바꾼다', async (status, content, message) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(content, { status })))
  await expect(requestAnalysis(body, new AbortController().signal)).rejects.toThrow(message)
})

test('연결 실패를 처리한다', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  await expect(requestAnalysis(body, new AbortController().signal)).rejects.toThrow('서버에 연결하지 못했어요')
})

test.each([
  ['INVALID_URL', 'http:// 또는 https://'],
  ['TOO_MANY_URLS', '10개 이하'],
])('URL 검증 오류 %s를 안내하고 공급자 원문을 노출하지 않는다', async (code, message) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code, message: 'private response' } }), { status: 422 })))
  await expect(requestAnalysis(body, new AbortController().signal)).rejects.toThrow(message)
})
