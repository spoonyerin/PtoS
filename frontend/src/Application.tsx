import { lazy, Suspense, useEffect, useState } from 'react'
import ConnectedApp from './App'
import { ServiceStatusProvider } from './hooks/useServiceStatus'
import { FamilyProvider } from './hooks/useFamily'
import { registerServiceWorker } from './family/push'
import connectedCss from './styles.css?url'
import familyCss from './family.css?url'

// The snapshot and its mock adapters are absent from production bundles.
const Preview = import.meta.env.DEV ? lazy(() => import('./preview/PreviewShell')) : null

function Connected() {
  useEffect(() => { registerServiceWorker() }, [])
  return <>
    <link rel="stylesheet" href={connectedCss} />
    <link rel="stylesheet" href={familyCss} />
    <ServiceStatusProvider>
      <FamilyProvider><ConnectedApp /></FamilyProvider>
    </ServiceStatusProvider>
  </>
}

export default function Application() {
  const [preview] = useState(() => {
    const requested = new URLSearchParams(location.search).get('mode')
    return import.meta.env.DEV && requested !== 'connected'
      && (requested === 'preview' || import.meta.env.VITE_UI_PREVIEW_DEFAULT === 'preview')
  })

  function change(mode: string) {
    const url = new URL(location.href)
    url.searchParams.set('mode', mode)
    url.hash = ''
    // A reload clears both providers and transient data before changing modes.
    location.assign(url.href)
  }

  return <>
    {import.meta.env.DEV && <details className="application-mode" style={{ maxWidth: 480, margin: '0 auto', padding: '10px 20px', background: '#eef0f4', fontFamily: 'sans-serif', fontSize: 14 }}>
      <summary>개발용 화면 모드 · {preview ? 'UI 미리보기' : 'API 연동 화면'}</summary>
      <p>미리보기는 합성 데이터로 동작하며 실제 분석·전송·결제를 하지 않습니다. 모드를 바꾸면 화면 상태가 초기화됩니다.</p>
      <label>화면 모드 <select value={preview ? 'preview' : 'connected'} onChange={event => change(event.target.value)}>
        <option value="preview">dev_week13 UI 미리보기</option>
        <option value="connected">최신 UI · API 연동 화면</option>
      </select></label>
    </details>}
    {preview && Preview
      ? <Suspense fallback={<p>UI를 준비하고 있어요.</p>}><Preview /></Suspense>
      : <Connected />}
  </>
}
