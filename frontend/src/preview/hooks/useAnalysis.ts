import { useCallback, useEffect, useRef, useState } from 'react'
import { AnalysisError, requestAnalysis } from '../api/client'
import type { AnalysisRequest, AnalysisResponse } from '../api/types'
import { characterCount, MAX_CONTENT_LENGTH } from '../input'

type State = {
  status: 'idle' | 'loading' | 'success' | 'error'
  result: AnalysisResponse | null
  error: string | null
}
const idle: State = { status: 'idle', result: null, error: null }

export function useAnalysis() {
  const [state, setState] = useState<State>(idle)
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => { active.current?.abort(); active.current = null }, [])

  const reset = useCallback(() => {
    active.current?.abort()
    active.current = null
    setState(idle)
  }, [])

  const submit = useCallback(async (body: AnalysisRequest) => {
    if (active.current) return // 같은 렌더링 프레임 안의 중복 제출도 차단한다.
    if (!body.content.trim() || characterCount(body.content) > MAX_CONTENT_LENGTH) {
      setState({ status: 'error', result: null, error: !body.content.trim() ? (body.input_type === 'url' ? 'URL 주소를 입력해주세요.' : '문자 내용을 입력해주세요.') : '메시지는 10,000자 이하로 입력해주세요.' })
      return
    }
    const controller = new AbortController()
    active.current = controller
    setState({ status: 'loading', result: null, error: null })
    const timer = window.setTimeout(() => controller.abort(), 10_000)
    try {
      const result = await requestAnalysis(body, controller.signal)
      if (active.current === controller) setState({ status: 'success', result, error: null })
    } catch (error) {
      if (active.current !== controller) return
      setState({
        status: 'error', result: null,
        error: controller.signal.aborted ? '응답을 기다리는 시간이 길어졌어요. 잠시 후 다시 시도해주세요.' : error instanceof AnalysisError ? error.message : '분석 중 문제가 생겼어요. 다시 시도해주세요.',
      })
    } finally {
      window.clearTimeout(timer)
      if (active.current === controller) active.current = null
    }
  }, [])

  return { ...state, submit, reset }
}
