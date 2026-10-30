import { useRef, type FormEvent } from 'react'
import { characterCount, MAX_CONTENT_LENGTH } from '../input'
import type { InputType } from '../api/types'
import { ScreenshotInput } from './ScreenshotInput'
import { UrlCheckNotice } from './UrlCheckNotice'

type Props = {
  content: string
  inputType: InputType
  loading: boolean
  error: string | null
  onContentChange: (value: string) => void
  onInputTypeChange: (value: InputType) => void
  onSubmit: () => void
  onOcrSubmit: (text: string) => void
  onReset: () => void
}

export function AnalysisForm(props: Props) {
  const textArea = useRef<HTMLTextAreaElement>(null)
  const count = characterCount(props.content)
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!props.content.trim() || count > MAX_CONTENT_LENGTH) textArea.current?.focus()
    props.onSubmit()
  }
  return (
    <section className="card input-card" aria-labelledby="input-title" style={{ minWidth: 0 }}>
      <div className="section-kicker">01 · 내용 입력</div>
      <h2 id="input-title">{props.inputType === 'ocr_text' ? '스크린샷에서 글자를 읽어보세요' : props.inputType === 'url' ? '확인할 URL을 입력해주세요' : '어떤 문자를 받으셨나요?'}</h2>
        <fieldset className="scenario-picker" disabled={props.loading}>
          <legend>입력 방식</legend>
          <div className="scenario-options">
            <label className="scenario-option"><input type="radio" name="input-type" checked={props.inputType === 'text'} onChange={() => props.onInputTypeChange('text')} />문자</label>
            <label className="scenario-option"><input type="radio" name="input-type" checked={props.inputType === 'url'} onChange={() => props.onInputTypeChange('url')} />URL 직접 입력</label>
            <label className="scenario-option"><input type="radio" name="input-type" checked={props.inputType === 'ocr_text'} onChange={() => props.onInputTypeChange('ocr_text')} />스크린샷</label>
          </div>
        </fieldset>
      {props.inputType === 'ocr_text' ? <ScreenshotInput loading={props.loading} analysisError={props.error} onChange={props.onReset} onSubmit={props.onOcrSubmit} /> : <form onSubmit={submit} noValidate>
        <label className="field-label" htmlFor="message">{props.inputType === 'url' ? 'URL 주소' : '문자 내용'}</label>
        <p className="hint" id="privacy-help">연습용 문자만 입력해주세요. 이름·계좌번호·인증번호 등 실제 개인정보는 넣지 마세요.</p>
        <textarea ref={textArea} id="message" rows={7} value={props.content} disabled={props.loading} placeholder={props.inputType === 'url' ? 'http:// 또는 https://로 시작하는 주소 한 개를 입력해주세요.' : '이곳에 문자 내용을 입력하거나 붙여넣어주세요.'} onChange={event => props.onContentChange(event.target.value)} aria-describedby={`privacy-help message-count${props.error ? ' analysis-error' : ''}`} aria-invalid={!!props.error} />
        <p id="message-count" className={`counter ${count > MAX_CONTENT_LENGTH ? 'over-limit' : ''}`}>{count.toLocaleString()} / 10,000자</p>
        {props.error && <p className="error-message" id="analysis-error" role="alert">{props.error}</p>}
        <UrlCheckNotice />
        <button className="primary-button" type="submit" disabled={props.loading}>
          {props.loading ? '분석 요청 중…' : '분석하기'} <span aria-hidden="true">→</span>
        </button>
        <p className="submission-note">입력 내용은 분석 이력으로 저장하지 않아요.</p>
      </form>}
    </section>
  )
}
