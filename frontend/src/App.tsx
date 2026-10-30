import { useState } from 'react'
import { AnalysisForm } from './components/AnalysisForm'
import { AnalysisResult } from './components/AnalysisResult'
import { useAnalysis } from './hooks/useAnalysis'
import type { InputType } from './api/types'
import { useUrlReputationStatus, type UrlReputationStatus } from './hooks/useServiceStatus'

const reputationNote: Record<UrlReputationStatus, string> = {
  live: 'URL 평판 조회(Google Safe Browsing)는 켜져 있지만',
  off: 'URL 평판 조회는 꺼져 있으며',
  unknown: 'URL 평판 조회가 켜져 있는지 확인하지 못했으며',
}

export default function App() {
  const [content, setContent] = useState('')
  const [inputType, setInputType] = useState<InputType>('text')
  const analysis = useAnalysis()
  const urlReputation = useUrlReputationStatus()
  return (
    <>
      <a href="#main" className="skip-link">본문 바로가기</a>
      <header className="site-header">
        <div className="brand"><span className="brand-symbol" aria-hidden="true">P</span><span>PtoS<span className="brand-caption">문자 확인 연습</span></span></div>
        <span className="header-note">함께 만드는 안전한 일상</span>
      </header>
      <main id="main">
        <div className="intro">
          <p className="eyebrow">문자 속 걱정을 덜어드리는 첫걸음</p>
          <h1>의심스러운 문자,<br />함께 확인해요.</h1>
          <p>문자·URL을 입력하거나 스크린샷에서 글자를 확인한 뒤 분석해보세요.</p>
        </div>
        <aside className="demo-notice" aria-label="개발용 안내">
          <span className="notice-symbol" aria-hidden="true">i</span>
          <div><strong>규칙 기반 개발 버전</strong><p>입력의 위험 신호와 URL 형식을 확인해요. 일부 분석 단계는 꺼져 있을 수 있고 {reputationNote[urlReputation]}, 결과는 안전을 보장하지 않아요.</p></div>
        </aside>
        <div className="workspace">
          <AnalysisForm content={content} inputType={inputType} loading={analysis.status === 'loading'} error={analysis.error}
            onInputTypeChange={value => { setInputType(value); analysis.reset() }}
            onContentChange={value => { setContent(value); analysis.reset() }}
            onReset={analysis.reset}
            onOcrSubmit={text => { void analysis.submit({ input_type: 'ocr_text', content: text, ocr_confirmed: true }) }}
            onSubmit={() => { void analysis.submit({ input_type: inputType, content }) }} />
          <div className="result-column" aria-busy={analysis.status === 'loading'}>
            <p className="sr-only" role="status">{analysis.status === 'loading' ? '서버에서 문자 표현을 확인하고 있어요.' : ''}</p>
            {analysis.result ? <AnalysisResult result={analysis.result} /> : <section className="card guide-card" aria-labelledby="guide-title">
              <div className="section-kicker">02 · 결과 확인</div>
              <div className="guide-illustration" aria-hidden="true">{analysis.status === 'loading' ? '⋯' : '✓'}</div>
              <h2 id="guide-title">{analysis.status === 'loading' ? '잠시만 기다려주세요' : '차근차근 확인해요'}</h2>
              <p>{analysis.status === 'loading' ? '문자 속 위험 신호를 확인하고 있어요.' : '분석하기를 누르면 이곳에 결과가 나와요.'}</p>
              <ol className="guide-steps"><li>위험도 확인</li><li>이유 살펴보기</li><li>다음 행동 알아보기</li></ol>
            </section>}
          </div>
        </div>
        <footer>규칙이 놓치거나 잘못 해석하는 표현이 있을 수 있어요. 의심스럽다면 요청을 따르기 전에 별도로 확인하세요.</footer>
      </main>
    </>
  )
}
