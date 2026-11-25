import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ServiceStatusProvider } from './hooks/useServiceStatus'
import { FamilyProvider } from './hooks/useFamily'
import { registerServiceWorker } from './family/push'
import './styles.css'
import './family.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ServiceStatusProvider><FamilyProvider><App /></FamilyProvider></ServiceStatusProvider></React.StrictMode>,
)

// 가족 보호 알림용 서비스 워커. 요청·결과를 캐시하지 않는다.
registerServiceWorker()
