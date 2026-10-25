import { act, renderHook } from '@testing-library/react'
import { useAnalysis } from './useAnalysis'

const body = { input_type: 'text', content: '문자' } as const

test('10초 제한 뒤 오류를 표시하고 제출 잠금을 해제한다', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockImplementation((_, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })))
  const { result } = renderHook(useAnalysis)
  act(() => { void result.current.submit(body) })
  expect(result.current.status).toBe('loading')
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
  expect(result.current.status).toBe('error')
  expect(result.current.error).toContain('시간이 길어졌어요')
  act(() => { void result.current.submit(body) })
  expect(result.current.status).toBe('loading')
})

test('초기화한 요청의 늦은 응답은 새 화면에 표시하지 않는다', async () => {
  let resolve!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(r => { resolve = r })))
  const { result } = renderHook(useAnalysis)
  let submission!: Promise<void>
  act(() => { submission = result.current.submit(body) })
  act(() => { result.current.reset() })
  await act(async () => { resolve(new Response('{}')); await submission })
  expect(result.current.status).toBe('idle')
  expect(result.current.result).toBeNull()
  expect(result.current.error).toBeNull()
})
