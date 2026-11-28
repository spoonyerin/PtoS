import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { requestServiceStatus } from '../api/client'

// 'unknown'은 아직 확인 중이거나 확인에 실패한 상태다. 켜져 있을 수 있으므로 화면은 안내를 보인다.
export type UrlReputationStatus = 'live' | 'off' | 'unknown'

const StatusContext = createContext<UrlReputationStatus>('unknown')

export function useUrlReputationStatus(): UrlReputationStatus {
  return useContext(StatusContext)
}

// 페이지를 열 때 한 번만 확인한다. 결과를 브라우저 저장소에 남기지 않는다.
export function ServiceStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<UrlReputationStatus>('unknown')
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 5_000)
    requestServiceStatus(controller.signal)
      .then(ready => { if (!controller.signal.aborted) setStatus(ready.url_reputation) })
      .catch(() => { if (!controller.signal.aborted) setStatus('unknown') })
      .finally(() => window.clearTimeout(timer))
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [])
  return <StatusContext.Provider value={status}>{children}</StatusContext.Provider>
}
