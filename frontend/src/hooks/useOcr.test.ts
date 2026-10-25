import { act, renderHook } from '@testing-library/react'
import { useOcr, useOcrReview } from './useOcr'

const file = new File(['image'], 'sample.png', { type: 'image/png' })
const body = { request_id: '8c224149-d5c4-4f9a-a77b-55a058cb8c71', text: '추출 문자', urls: [], warnings: [], engine: 'tesseract-5', ocr_confidence: null }

test('가짜 OCR 요청 중 중복 제출 차단과 초기화 후 늦은 응답 무시', async () => {
  let resolve!: (response: Response) => void
  const fetch = vi.fn().mockImplementation(() => new Promise<Response>(r => { resolve = r }))
  vi.stubGlobal('fetch', fetch)
  const { result } = renderHook(useOcr)
  let pending!: Promise<void>
  act(() => { pending = result.current.submit(file); void result.current.submit(file) })
  expect(fetch).toHaveBeenCalledTimes(1)
  act(() => result.current.reset())
  await act(async () => { resolve(new Response(JSON.stringify(body))); await pending })
  expect(result.current.result).toBeNull()
  expect(result.current.error).toBeNull()
  expect(result.current.loading).toBe(false)
})

test('25초 브라우저 OCR 제한은 실패 안내 후 다시 제출 가능', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockImplementation((_, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })))
  const { result } = renderHook(useOcr)
  act(() => { void result.current.submit(file) })
  await act(async () => { await vi.advanceTimersByTimeAsync(25_000) })
  expect(result.current.error).toContain('대기 시간이 초과')
  expect(result.current.loading).toBe(false)
  act(() => { void result.current.submit(file) })
  expect(result.current.loading).toBe(true)
})

test('수정 전 URL 후보 응답이 늦게 도착해도 새 텍스트에 적용되지 않는다', async () => {
  vi.useFakeTimers()
  const replies: ((response: Response) => void)[] = []
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(resolve => replies.push(resolve))))
  const { result, rerender } = renderHook(({ text }) => useOcrReview(text, true), { initialProps: { text: '이전 문자' } })
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  rerender({ text: '수정한 문자' })
  expect(result.current.ready).toBe(false)
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  await act(async () => { replies[1](new Response(JSON.stringify({ request_id: body.request_id, urls: [] }))) })
  expect(result.current.ready).toBe(true)
  await act(async () => { replies[0](new Response('SECRET malformed response')) })
  expect(result.current.ready).toBe(true)
  expect(result.current.error).toBeNull()
})
