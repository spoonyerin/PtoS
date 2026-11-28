import { useEffect, useRef, useState } from 'react'
import { AnalysisForm } from './components/AnalysisForm'
import { AnalysisResult } from './components/AnalysisResult'
import { FamilyAutoAlert, FamilyShare } from './components/FamilyShare'
import { FamilyPages, parseFamilyRoute } from './components/family/FamilyPages'
import { FamilyHomeTile, FamilyNews } from './components/family/FamilyHomeTile'
import { Icon } from './components/Icons'
import { useAnalysis } from './hooks/useAnalysis'
import type { InputType } from './api/types'
import {
  DevelopmentNote,
  developmentNoteText,
} from './components/DevelopmentNote'
import { useUrlReputationStatus } from './hooks/useServiceStatus'
type Page = 'home' | InputType | 'family'
const readPage = (): Page =>
  ['text', 'url', 'ocr_text'].includes(location.hash.slice(1))
    ? (location.hash.slice(1) as InputType)
    : parseFamilyRoute(location.hash)
      ? 'family'
      : 'home'
export default function App() {
  const [page, setPage] = useState<Page>(readPage)
  const [hash, setHash] = useState(location.hash)
  const [content, setContent] = useState('')
  const [senderNumber, setSenderNumber] = useState('')
  const [panel, setPanel] = useState<'guide' | 'settings' | 'notice' | null>(
    null,
  )
  const [large, setLarge] = useState(false)
  const analysis = useAnalysis()
  const urlReputation = useUrlReputationStatus()
  const dialog = useRef<HTMLDialogElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    const change = () => {
      setPage(readPage())
      setHash(location.hash)
      analysis.reset()
      // 뒤로/앞으로 이동으로 다른 확인 화면에 원문이 넘어가지 않게 지운다.
      setContent('')
      setSenderNumber('')
    }
    window.addEventListener('hashchange', change)
    window.addEventListener('popstate', change)
    return () => {
      window.removeEventListener('hashchange', change)
      window.removeEventListener('popstate', change)
    }
  }, [analysis.reset])
  useEffect(() => {
    if (panel) dialog.current?.showModal()
    else if (dialog.current?.open) dialog.current.close()
  }, [panel])
  useEffect(() => {
    title.current?.focus()
    window.scrollTo(0, 0)
  }, [page, !!analysis.result])
  function navigate(next: Page) {
    analysis.reset()
    setContent('')
    setSenderNumber('')
    history.pushState(
      null,
      '',
      next === 'home' ? location.pathname + location.search : '#' + next,
    )
    setPage(next)
    setHash(location.hash)
  }
  // 가족 보호 화면 이동. hash가 비어 있으면 홈으로 간다.
  function go(next: string, replace = false) {
    analysis.reset()
    setContent('')
    setSenderNumber('')
    const url = next ? '#' + next : location.pathname + location.search
    if (replace) history.replaceState(null, '', url)
    else history.pushState(null, '', url)
    setPage(readPage())
    setHash(location.hash)
  }
  const titles = {
    text: '문자 확인하기',
    url: '링크 확인하기',
    ocr_text: '사진으로 확인하기',
    home: '',
    family: '',
  }
  return (
    <div className={`app-shell${large ? ' large-text' : ''}`}>
      <a
        href="#main"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault()
          document.getElementById('main')?.focus()
        }}
      >
        본문 바로가기
      </a>
      {page === 'family' ? (
        <FamilyPages route={parseFamilyRoute(hash) ?? { name: 'protect' }} go={go} />
      ) : page === 'home' ? (
        <>
          <header className="home-header">
            <div className="brand" aria-label="PtoS">
              {/* Crop the exported PNG's transparent padding without altering the original. */}
              <svg
                className="brand-image"
                viewBox="408 113 1463 513"
                role="img"
                aria-label="PtoS"
              >
                <image
                  href="/assets/PtoS_logo_rm.png"
                  width="2271"
                  height="755"
                />
              </svg>
            </div>
            <div className="header-tools">
              <button
                className="icon-button"
                aria-label="알림"
                onClick={() => setPanel('notice')}
              >
                <img
                  className="header-asset-icon"
                  src="/assets/icon_notification_rm.png"
                  width="36"
                  height="36"
                  alt=""
                />
              </button>
              <button
                className="icon-button"
                aria-label="설정"
                onClick={() => setPanel('settings')}
              >
                <img
                  className="header-asset-icon"
                  src="/assets/icon_setting_rm.png"
                  width="36"
                  height="36"
                  alt=""
                />
              </button>
            </div>
          </header>
          <main id="main" tabIndex={-1} className="home-main">
            <section className="hero">
              <div className="hero-copy">
                <p>스미는 사기, 미리 막는 습관</p>
                <h1 ref={title} tabIndex={-1}>
                  쉽게 확인하고
                  <br />
                  <em>안전하게</em> 대응하세요.
                </h1>
                <p>
                  문자, 사진, 링크 속 위험을
                  <br />
                  PtoS가 알려드립니다.
                </p>
              </div>
              <img
                className="hero-art"
                src="/assets/logo_main.png"
                width="1254"
                height="1254"
                alt=""
                fetchPriority="high"
              />
            </section>
            <FamilyNews go={go} />
            <nav className="home-menu" aria-label="확인 방법 선택">
              <div className="home-feature-cards">
                <FamilyHomeTile go={go} />
                <button className="guide-button" onClick={() => setPanel('guide')}>
                  <span className="family-card-top" aria-hidden="true"><span className="menu-symbol help-symbol"><img src="/assets/icon_questionmark.png" width="22" height="36" alt="" /></span><Icon name="chevron" /></span>
                  <strong>이용 방법</strong>
                  <small>방법을 상세하게 안내해 드립니다.</small>
                </button>
              </div>
              {(['text', 'ocr_text', 'url'] as InputType[]).map((mode) => (
                <button
                  className="menu-button"
                  key={mode}
                  onClick={() => navigate(mode)}
                >
                  <span className="menu-symbol">
                    <img
                      className="menu-asset-icon"
                      src={`/assets/${mode === 'text' ? 'icon_message_rm.png' : mode === 'url' ? 'icon_link_rm.png' : 'icon_image_rm.png'}`}
                      width="46"
                      height="46"
                      alt=""
                    />
                  </span>
                  <strong>{titles[mode]}</strong>
                  <Icon name="chevron" />
                </button>
              ))}
            </nav>
            <DevelopmentNote />
          </main>
        </>
      ) : (
        <>
          <header
            className={`page-header${analysis.result ? ' result-header' : ''}`}
          >
            <button
              className="icon-button"
              aria-label={analysis.result ? '다시 확인하기' : '홈으로 돌아가기'}
              onClick={() =>
                analysis.result ? analysis.reset() : navigate('home')
              }
            >
              <Icon name="back" />
            </button>
            <h1 ref={title} tabIndex={-1}>
              {analysis.result ? '분석 결과' : titles[page]}
            </h1>
          </header>
          <main id="main" tabIndex={-1} className="flow-main">
            {analysis.result && (
              <>
                <AnalysisResult result={analysis.result}>
                  <div className="result-buttons">
                    <FamilyShare
                      result={analysis.result}
                      large={large}
                      go={go}
                    />
                    <button
                      className="primary-button"
                      onClick={() => navigate('home')}
                    >
                      <Icon name="home" />
                      홈으로
                    </button>
                  </div>
                  <FamilyAutoAlert result={analysis.result} />
                </AnalysisResult>
              </>
            )}
            <div hidden={!!analysis.result}>
              <AnalysisForm
                content={content}
                inputType={page}
                loading={analysis.status === 'loading'}
                error={analysis.error}
                onContentChange={(value) => {
                  setContent(value)
                  analysis.reset()
                }}
                senderNumber={senderNumber}
                onSenderNumberChange={(value) => {
                  setSenderNumber(value)
                  analysis.reset()
                }}
                onReset={analysis.reset}
                onOcrSubmit={(text) => {
                  void analysis.submit({
                    input_type: 'ocr_text',
                    content: text,
                    ocr_confirmed: true,
                  })
                }}
                onSubmit={() => {
                  const sender = senderNumber.trim()
                  void analysis.submit(
                    page === 'text' && sender
                      ? { input_type: page, content, sender_number: sender }
                      : { input_type: page, content },
                  )
                }}
              />
            </div>
          </main>
        </>
      )}
      <dialog
        ref={dialog}
        aria-labelledby="dialog-title"
        onCancel={() => setPanel(null)}
        onClose={() => setPanel(null)}
      >
        {panel && (
          <>
            <div className="dialog-heading">
              <h2 id="dialog-title">
                {panel === 'guide'
                  ? '이용하는 방법'
                  : panel === 'settings'
                    ? '화면 설정'
                    : '알림'}
              </h2>
              <button
                className="icon-button"
                aria-label="닫기"
                onClick={() => setPanel(null)}
              >
                <Icon name="close" />
              </button>
            </div>
            {panel === 'guide' ? (
              <ol className="guide-list">
                <li>문자, 사진, 링크 중 확인할 방법을 선택하세요.</li>
                <li>
                  개인정보를 가린 내용을 입력하세요. 사진은 읽어낸 글자를 원본과
                  비교하고 확인해주세요.
                </li>
                <li>
                  분석 결과의 위험 신호와 다음 행동을 살펴보세요. 결과가 안전을
                  보장하지는 않아요.
                </li>
              </ol>
            ) : panel === 'settings' ? (
              <label className="font-setting">
                <input
                  type="checkbox"
                  checked={large}
                  onChange={(e) => setLarge(e.target.checked)}
                />
                글씨 크게 보기
              </label>
            ) : (
              <p>
                규칙 기반 개발 버전입니다. {developmentNoteText(urlReputation)}
              </p>
            )}
          </>
        )}
      </dialog>
    </div>
  )
}
