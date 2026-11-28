import type { OcrResponse, OcrReviewResponse } from './types'
export async function requestOcr(_file: File, signal: AbortSignal): Promise<OcrResponse> {
  if (signal.aborted) throw new DOMException('cancelled', 'AbortError')
  return { request_id: crypto.randomUUID(), text: '[화면 확인용 예시] 은행 담당자입니다. 개인정보를 입력해 주세요.', urls: [], warnings: ['실제 OCR이 아닙니다. 사진을 서버로 보내지 않고 고정 예시를 표시합니다.'], engine: 'tesseract-5', ocr_confidence: null }
}
export async function reviewOcr(_content: string, signal: AbortSignal): Promise<OcrReviewResponse> {
  if (signal.aborted) throw new DOMException('cancelled', 'AbortError')
  return { request_id: crypto.randomUUID(), urls: [] }
}
