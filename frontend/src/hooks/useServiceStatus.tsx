import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { requestServiceStatus } from '../api/client'

// 'unknown'은 아직 확인 중이거나 확인에 실패한 상태다. 켜져 있을 수 있으므로 화면은 안내를 보인다.
export type ServiceFlag = 'live' | 'off' | 'unknown'
export type UrlReputationStatus = ServiceFlag

type ServiceStatus = { urlReputation: ServiceFlag; llmReview: ServiceFlag }
const UNKNOWN: ServiceStatus = { urlReputation: 'unknown', llmReview: 'unknown' }

const StatusContext = createContext<ServiceStatus>(UNKNOWN)

export function useUrlReputationStatus(): UrlReputationStatus {
  return useContext(StatusContext).urlReputation
}

// 조건부 추가 검토(가린 문장의 외부 전송)가 켜져 있는지.
export function useLlmReviewStatus(): ServiceFlag {
  return useContext(StatusContext).llmReview
}

// 페이지를 열 때 한 번만 확인한다. 결과를 브라우저 저장소에 남기지 않는다.
export function ServiceStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ServiceStatus>(UNKNOWN)
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 5_000)
    requestServiceStatus(controller.signal)
      .then(ready => {
        if (!controller.signal.aborted) setStatus({ urlReputation: ready.url_reputation, llmReview: ready.llm_review })
      })
      .catch(() => { if (!controller.signal.aborted) setStatus(UNKNOWN) })
      .finally(() => window.clearTimeout(timer))
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [])
  return <StatusContext.Provider value={status}>{children}</StatusContext.Provider>
}
