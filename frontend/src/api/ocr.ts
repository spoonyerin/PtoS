import { z } from 'zod'
import type { OcrResponse, OcrReviewResponse } from './types'

const urlPreview = z.object({
  original_url: z.string(), normalized_url: z.string().nullable(), ascii_host: z.string().nullable(),
  validation_status: z.enum(['valid', 'invalid']), validation_message: z.string(), warnings: z.array(z.string()),
  occurrences: z.array(z.object({ text: z.string(), start: z.number().int().min(0), end: z.number().int().positive() })),
})
const reviewSchema: z.ZodType<OcrReviewResponse> = z.object({ request_id: z.uuid(), urls: z.array(urlPreview) })
const ocrSchema: z.ZodType<OcrResponse> = z.object({
  request_id: z.uuid(), urls: z.array(urlPreview), text: z.string(), warnings: z.array(z.string()),
  engine: z.literal('tesseract-5'), ocr_confidence: z.null(),
})
const messages: Record<string, string> = {
  IMAGE_TOO_LARGE: '이미지를 10 MiB 이하·2,000만 화소 이하로 줄이거나 문자로 직접 입력해주세요.',
  UNSUPPORTED_MEDIA_TYPE: '실제 JPG·PNG 이미지 한 장을 선택해주세요. 확장자만 바꾸면 사용할 수 없어요.',
  INVALID_IMAGE: '이미지를 읽지 못했어요. 다시 저장한 JPG·PNG를 올리거나 문자로 직접 입력해주세요.',
  OCR_NO_TEXT: '문자를 찾지 못했어요. 선명한 이미지를 다시 올리거나 문자로 직접 입력해주세요.',
  OCR_TIMEOUT: '글자 읽기 시간이 초과됐어요. 더 작은 이미지를 다시 올리거나 문자로 직접 입력해주세요.',
  OCR_UNAVAILABLE: '한국어 OCR 설치를 확인해주세요. 지금은 문자로 직접 입력할 수 있어요.',
  OCR_FAILED: 'OCR 처리에 실패했어요. 다른 이미지를 다시 올리거나 문자로 직접 입력해주세요.',
  OCR_TEXT_TOO_LONG: '추출한 문자가 10,000자를 초과했어요. 이미지 범위를 줄이거나 문자로 직접 입력해주세요.',
  OCR_BUSY: '다른 이미지의 글자를 읽고 있어요. 잠시 후 다시 시도하거나 문자로 직접 입력해주세요.',
  OCR_CANCELLED: '이미지 읽기가 취소됐어요. 다시 올리거나 문자로 직접 입력해주세요.',
  TOO_MANY_URLS: 'URL 후보는 중복을 제외하고 10개 이하로 수정해주세요.',
  INPUT_TOO_LONG: '추출한 문자를 10,000자 이하로 수정해주세요.',
}

async function call(path: string, init: RequestInit, signal: AbortSignal) {
  let response: Response
  try { response = await fetch(path, { ...init, signal, cache: 'no-store' }) }
  catch (error) {
    if (signal.aborted) throw error
    throw new Error('서버에 연결하지 못했어요. 백엔드 실행을 확인하거나 문자로 직접 입력해주세요.')
  }
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = z.object({ error: z.object({ code: z.string() }) }).safeParse(data)
    throw new Error((error.success && messages[error.data.error.code]) || '글자/URL 확인 요청에 실패했어요. 다시 시도하거나 문자로 직접 입력해주세요.')
  }
  return data
}

export async function requestOcr(file: File, signal: AbortSignal): Promise<OcrResponse> {
  const result = ocrSchema.safeParse(await call('/api/v1/ocr', {
    method: 'POST', headers: { 'Content-Type': file.type || (file.name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg') }, body: file,
  }, signal))
  if (!result.success) throw new Error('OCR 결과 형식을 읽지 못했어요. 다시 시도하거나 문자로 직접 입력해주세요.')
  return result.data
}

export async function reviewOcr(content: string, signal: AbortSignal): Promise<OcrReviewResponse> {
  const result = reviewSchema.safeParse(await call('/api/v1/ocr/review', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }),
  }, signal))
  if (!result.success) throw new Error('URL 후보 형식을 읽지 못했어요. 다시 시도하거나 문자로 직접 입력해주세요.')
  return result.data
}
