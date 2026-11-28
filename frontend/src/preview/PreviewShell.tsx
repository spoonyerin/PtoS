import { useState } from 'react'
import App from './App'
import css from './styles.css?url'
import { ServiceStatusProvider } from './hooks/useServiceStatus'
import { setPreviewScenario } from './api/client'
import type { RiskLevel } from './api/types'

export default function PreviewShell() {
  const [scenario, setScenario] = useState<RiskLevel>('dangerous')
  return <>
    <link rel="stylesheet" href={css} />
    <ServiceStatusProvider><App /></ServiceStatusProvider>
    <details className="family-dev-panel preview-scenario">
      <summary>분석 결과 시나리오 · 모의 동작</summary>
      <label htmlFor="preview-scenario">다음 분석 결과</label>
      <select id="preview-scenario" value={scenario} onChange={event => {
        const next = event.target.value as RiskLevel
        setScenario(next)
        setPreviewScenario(next)
      }}>
        <option value="dangerous">위험</option>
        <option value="suspicious">의심</option>
        <option value="normal">정상</option>
        <option value="insufficient_information">정보 부족</option>
      </select>
      <p>입력을 실제로 분석하지 않습니다. 선택 후 문자·링크 분석 또는 사진 확인을 진행하면 선택한 예시 결과를 보여줍니다.</p>
    </details>
  </>
}
