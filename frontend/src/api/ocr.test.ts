import { requestOcr } from './ocr'

test.each([['OCR_NO_TEXT', '문자를 찾지 못했어요'], ['OCR_FAILED', 'OCR 처리에 실패'], ['OCR_TIMEOUT', '시간이 초과'], ['OCR_UNAVAILABLE', 'OCR 설치'], ['IMAGE_TOO_LARGE', '2,000만 화소']])('%s를 구분하고 서버 원문 대신 고정 안내만 표시한다', async (code, message) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code, message: 'SECRET RAW OCR' } }), { status: 422 })))
  const error = await requestOcr(new File(['x'], 'sample.png'), new AbortController().signal).catch(error => error)
  expect(error).toBeInstanceOf(Error)
  expect(error.message).toContain(message)
  expect(error.message).not.toContain('SECRET')
})

test('오염된 OCR 응답 계약을 거부한다', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ text: 'secret', risk_level: 'normal' }))))
  await expect(requestOcr(new File(['x'], 'sample.png'), new AbortController().signal)).rejects.toThrow('결과 형식')
})
