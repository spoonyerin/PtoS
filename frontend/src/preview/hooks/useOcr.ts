import { useCallback, useEffect, useRef, useState } from 'react'
import { requestOcr, reviewOcr } from '../api/ocr'
import type { OcrResponse, UrlPreview } from '../api/types'
import { characterCount, MAX_CONTENT_LENGTH } from '../input'

export function useOcr() {
  const [state, setState] = useState<{ loading: boolean; result: OcrResponse | null; error: string | null }>({ loading: false, result: null, error: null })
  const active = useRef<AbortController | null>(null)
  const reset = useCallback(() => {
    active.current?.abort(); active.current = null
    setState({ loading: false, result: null, error: null })
  }, [])
  useEffect(() => () => { active.current?.abort(); active.current = null }, [])
  const submit = useCallback(async (file: File) => {
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setState({ loading: true, result: null, error: null })
    const timer = window.setTimeout(() => controller.abort(), 25_000)
    try {
      const result = await requestOcr(file, controller.signal)
      if (active.current === controller) setState({ loading: false, result, error: null })
    } catch (error) {
      if (active.current === controller) setState({ loading: false, result: null, error: controller.signal.aborted ? 'OCR 응답 대기 시간이 초과됐어요. 더 작은 이미지를 다시 올리거나 문자로 직접 입력해주세요.' : error instanceof Error ? error.message : 'OCR 처리에 실패했어요. 다시 올리거나 문자로 직접 입력해주세요.' })
    } finally {
      window.clearTimeout(timer)
      if (active.current === controller) active.current = null
    }
  }, [])
  return { ...state, submit, reset }
}

export function useOcrReview(content: string, enabled: boolean) {
  const [state, setState] = useState<{ content: string | null; urls: UrlPreview[]; error: string | null }>({ content: null, urls: [], error: null })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!enabled) return
    if (characterCount(content) > MAX_CONTENT_LENGTH) {
      setState({ content, urls: [], error: '10,000자 이하로 수정해주세요.' })
      return
    }
    const controller = new AbortController()
    let current = true
    const timer = window.setTimeout(() => {
      const timeout = window.setTimeout(() => controller.abort(), 10_000)
      void reviewOcr(content, controller.signal).then(result => {
        if (current) setState({ content, urls: result.urls, error: null })
      }).catch(error => {
        if (current) setState({ content, urls: [], error: controller.signal.aborted ? 'URL 후보 확인 시간이 초과됐어요. 다시 확인해주세요.' : error instanceof Error ? error.message : 'URL 후보를 다시 확인해주세요.' })
      }).finally(() => window.clearTimeout(timeout))
    }, 300)
    return () => { current = false; window.clearTimeout(timer); controller.abort() }
  }, [content, enabled, retry])
  const loading = enabled && state.content !== content
  return { urls: loading ? [] : state.urls, error: loading ? null : state.error, loading,
    ready: enabled && !loading && !state.error, retry: () => { setState({ content: null, urls: [], error: null }); setRetry(n => n + 1) } }
}
