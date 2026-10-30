import { useRef, type FormEvent } from 'react'
import { characterCount, MAX_CONTENT_LENGTH } from '../input'
import type { InputType } from '../api/types'
import { ScreenshotInput } from './ScreenshotInput'
import { Icon } from './Icons'
type Props = {
  content: string
  inputType: InputType
  loading: boolean
  error: string | null
  onContentChange: (value: string) => void
  onSubmit: () => void
  onOcrSubmit: (text: string) => void
  onReset: () => void
}
export function AnalysisForm(props: Props) {
  const textArea = useRef<HTMLTextAreaElement>(null)
  const count = characterCount(props.content)
  const url = props.inputType === 'url'
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!props.content.trim() || count > MAX_CONTENT_LENGTH)
      textArea.current?.focus()
    props.onSubmit()
  }
  return (
    <section className={`input-screen ${url ? 'url-screen' : ''}`}>
      <p className="instruction-panel">
        {props.inputType === 'ocr_text'
          ? '의심스러운 문자 및 카카오톡 화면을 찍거나 캡처해주세요. ‘사진 선택하기’를 눌러 사진을 올려주세요.'
          : url
            ? '수상한 인터넷 주소가 있나요? 주소를 열지 마시고 ‘링크 붙여넣기’에 붙여넣어 확인해 보세요.'
            : '문자나 카카오톡 등 확인할 문자 내용을 복사한 후 아래 입력창에 붙여 넣어 주세요.'}
      </p>
      {props.inputType === 'ocr_text' ? (
        <ScreenshotInput
          loading={props.loading}
          analysisError={props.error}
          onChange={props.onReset}
          onSubmit={props.onOcrSubmit}
        />
      ) : (
        <form className="analysis-form" onSubmit={submit} noValidate>
          <label className="field-label" htmlFor="message">
            {url ? '링크 붙여넣기' : '문자 내용'}
          </label>
          <div className="text-field">
            <textarea
              ref={textArea}
              id="message"
              aria-label={url ? 'URL 주소' : '문자 내용'}
              rows={url ? 1 : 10}
              value={props.content}
              disabled={props.loading}
              placeholder={
                url
                  ? '링크를 복사·붙여넣기 해주세요.'
                  : '문자 내용을 복사·붙여넣기 해주세요.'
              }
              onChange={(event) => props.onContentChange(event.target.value)}
              aria-describedby={`privacy-help message-count${props.error ? ' analysis-error' : ''}`}
              aria-invalid={!!props.error}
            />
            {props.content && !props.loading && (
              <button
                className="clear-text"
                type="button"
                aria-label="입력 내용 지우기"
                onClick={() => {
                  props.onContentChange('')
                  textArea.current?.focus()
                }}
              >
                <Icon name="close" />
              </button>
            )}
          </div>
          <div className="input-meta">
            <p className="privacy-hint" id="privacy-help">
              실제 개인정보는 가리고 입력해주세요.
            </p>
            <p
              id="message-count"
              className={count > MAX_CONTENT_LENGTH ? 'over-limit' : ''}
            >
              {count.toLocaleString()} / 10,000자
            </p>
          </div>
          {url && (
            <section className="link-tips">
              <h2>TIP 이런 링크는 조심하세요!</h2>
              <ul>
                <li>지금 바로 확인하라는 링크</li>
                <li>상품이나 당첨금을 준다는 링크</li>
                <li>비밀번호나 인증번호를 요구하는 링크</li>
              </ul>
            </section>
          )}
          {props.error && (
            <p className="error-message" id="analysis-error" role="alert">
              {props.error}
            </p>
          )}
          <button
            className="primary-button analyze-button"
            type="submit"
            aria-label={props.loading ? '분석 요청 중…' : '분석하기'}
            disabled={props.loading}
          >
            <Icon name="search" />
            {props.loading ? '분석 요청 중…' : '분석 시작하기'}
          </button>
        </form>
      )}
      <p className="development-note">
        규칙 기반 개발 버전 · URL 평판 조회는 미연결이며 결과는 안전을 보장하지
        않아요.
      </p>
    </section>
  )
}
