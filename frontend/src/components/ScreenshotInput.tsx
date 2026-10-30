import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from './Icons'
import { useOcr, useOcrReview } from '../hooks/useOcr'
import { characterCount } from '../input'

type Props = {
  loading: boolean
  analysisError: string | null
  onChange: () => void
  onSubmit: (text: string) => void
}
const MAX_BYTES = 10 * 1024 * 1024
const MAX_PIXELS = 20_000_000

export function ScreenshotInput(props: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const selection = useRef(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const ocr = useOcr()
  const review = useOcrReview(text, !!ocr.result)
  useEffect(() => {
    if (ocr.result) {
      setText(ocr.result.text)
      setConfirmed(false)
    }
  }, [ocr.result])
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview)
    },
    [preview],
  )
  useEffect(
    () => () => {
      selection.current++
    },
    [],
  )

  function clear(resetInput = true) {
    if (resetInput && fileInput.current) fileInput.current.value = ''
    selection.current++
    setFile(null)
    setPreview(null)
    setFileError(null)
    setText('')
    setConfirmed(false)
    ocr.reset()
    props.onChange()
  }
  async function select(value: File | undefined) {
    clear(false)
    if (!value) return
    const id = selection.current
    if (!/\.(?:jpe?g|png)$/i.test(value.name)) {
      setFileError('JPG·PNG 파일을 선택해주세요.')
      return
    }
    if (!value.size || value.size > MAX_BYTES) {
      setFileError(
        '빈 파일은 사용할 수 없어요. 10 MiB 이하 JPG·PNG를 선택해주세요.',
      )
      return
    }
    try {
      const signature = new Uint8Array(await value.slice(0, 8).arrayBuffer())
      if (id !== selection.current) return
      const png = [137, 80, 78, 71, 13, 10, 26, 10].every(
        (v, i) => signature[i] === v,
      )
      const jpg =
        signature[0] === 255 && signature[1] === 216 && signature[2] === 255
      if (!png && !jpg)
        throw new Error(
          '실제 JPG·PNG 형식이 아니에요. 다른 이미지를 올리거나 문자로 직접 입력해주세요.',
        )
      setFile(value)
      setPreview(URL.createObjectURL(value))
    } catch (error) {
      if (id === selection.current)
        setFileError(
          error instanceof Error ? error.message : '이미지를 읽지 못했어요.',
        )
    }
  }
  function analyze(event: FormEvent) {
    event.preventDefault()
    if (!confirmed || !review.ready || !text.trim() || props.loading) return
    props.onSubmit(text)
  }
  return (
    <div>
      <div className={`upload-panel${preview ? ' has-preview' : ''}`}>
        <div className="upload-inner">
          {!preview && (
            <>
              <span className="upload-icon">
                <Icon name="photo" />
                <span>+</span>
              </span>
              <h2>사진을 선택해주세요.</h2>
              <p>(사진, 스크린샷 등)</p>
            </>
          )}
          <label className="upload-button" htmlFor="screenshot">
            사진 선택하기
          </label>
          <input
            ref={fileInput}
            id="screenshot"
            type="file"
            accept=".jpg,.jpeg,.png,image/jpeg,image/png"
            className="sr-only"
            aria-label="스크린샷 선택"
            disabled={props.loading}
            onChange={(event) => {
              void select(event.target.files?.[0])
            }}
          />
          {preview && (
            <div>
              <img
                src={preview}
                alt="선택한 스크린샷 미리보기"
                style={{
                  maxWidth: '100%',
                  maxHeight: 400,
                  objectFit: 'contain',
                }}
                onLoad={(event) => {
                  if (
                    event.currentTarget.naturalWidth *
                      event.currentTarget.naturalHeight >
                    MAX_PIXELS
                  ) {
                    clear()
                    setFileError(
                      '2,000만 화소 이하로 줄여주세요. 또는 문자로 직접 입력해주세요.',
                    )
                  }
                }}
                onError={() => {
                  clear()
                  setFileError(
                    '이미지를 읽지 못했어요. 다시 저장해 올리거나 문자로 직접 입력해주세요.',
                  )
                }}
              />
              <button
                type="button"
                disabled={props.loading}
                onClick={() => clear()}
              >
                이미지 지우기 / 취소
              </button>
            </div>
          )}
        </div>
      </div>
      <p className="hint">
        JPG·PNG 한 장, 10 MiB·2,000만 화소 이하 (개발 제안값). 개인정보 없는
        연습용 이미지를 사용해주세요.
      </p>
      <p className="hint">
        이미지를 현재 앱의 백엔드 서버로 전송해 OCR을 처리해요. PC 실행은
        PC에서, 클라우드 실행은 해당 클라우드에서 처리하며 별도 OCR 서비스로
        보내지 않아요.
      </p>
      {fileError && (
        <p role="alert" className="error-message">
          {fileError}
        </p>
      )}
      {
        <button
          type="button"
          className="primary-button"
          aria-label={
            ocr.loading ? '글자 읽는 중…' : '이미지에서 글자 읽기 (OCR)'
          }
          disabled={!file || ocr.loading || props.loading}
          onClick={() => {
            if (!file) return
            props.onChange()
            setText('')
            setConfirmed(false)
            void ocr.submit(file)
          }}
        >
          <Icon name="search" />
          {ocr.loading ? '글자 읽는 중…' : '분석 시작하기'}
        </button>
      }
      <p className="submission-note">
        먼저 사진의 글자를 읽어요. 원본과 비교·확인한 뒤 위험 분석을 진행합니다.
      </p>
      {ocr.loading && (
        <p role="status">글자를 읽고 있어요. 위험 분석은 아직 하지 않아요.</p>
      )}
      {ocr.error && (
        <p role="alert" className="error-message">
          {ocr.error}
        </p>
      )}
      {ocr.result && (
        <form onSubmit={analyze} noValidate>
          <h3>추출 내용 확인·수정</h3>
          {ocr.result.warnings.map((warning) => (
            <p className="hint" key={warning}>
              {warning}
            </p>
          ))}
          <label className="field-label" htmlFor="ocr-text">
            추출한 문자와 URL (수정 가능)
          </label>
          <textarea
            id="ocr-text"
            rows={8}
            value={text}
            disabled={props.loading}
            onChange={(event) => {
              setText(event.target.value)
              setConfirmed(false)
              props.onChange()
            }}
          />
          <p>{characterCount(text).toLocaleString()} / 10,000자</p>
          <section aria-labelledby="ocr-urls">
            <h3 id="ocr-urls">수정한 내용의 URL 후보</h3>
            <p>
              주소를 열거나 평판을 조회하지 않았어요. 주소가 끊기거나 틀렸다면
              위 텍스트에서 원본을 보고 직접 수정해주세요.
            </p>
            {review.loading ? (
              <p role="status">URL 후보를 갱신하고 있어요.</p>
            ) : review.error ? (
              <>
                <p role="alert">{review.error}</p>
                <button type="button" onClick={review.retry}>
                  URL 후보 다시 확인
                </button>
              </>
            ) : review.urls.length ? (
              <ul>
                {review.urls.map((url, i) => (
                  <li key={i} style={{ overflowWrap: 'anywhere' }}>
                    {url.original_url} ·{' '}
                    {url.validation_status === 'valid'
                      ? '형식 확인'
                      : '형식 확인 필요'}{' '}
                    · 조회 안 함
                    {url.warnings.map((w) => (
                      <p key={w}>{w}</p>
                    ))}
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                현재 텍스트에서 URL 후보를 찾지 못했어요. 원본에 URL이 있는지
                직접 확인해주세요.
              </p>
            )}
          </section>
          <p>
            읽을 수 없는 글자나 URL은 추측하지 마세요. 확인할 수 없다면 이미지를
            다시 올리거나 문자 직접 입력으로 바꿔주세요.
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!review.ready || props.loading || !text.trim()}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            추출한 문자와 URL을 원본과 비교해 확인했습니다.
          </label>
          {props.analysisError && (
            <p role="alert" className="error-message">
              {props.analysisError}
            </p>
          )}
          <button
            className="primary-button"
            type="submit"
            disabled={
              !confirmed || !review.ready || props.loading || !text.trim()
            }
          >
            {props.loading ? '분석 요청 중…' : '확인한 내용으로 분석하기'}
          </button>
        </form>
      )}
      <p className="submission-note">
        OCR만으로 위험 분석하지 않아요. 이미지는 서버의 파일이나 분석 이력으로
        저장하지 않아요.
      </p>
    </div>
  )
}
