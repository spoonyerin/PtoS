import { z } from 'zod'
import type { AnalysisRequest, AnalysisResponse } from './types'

const resultSchema: z.ZodType<AnalysisResponse> = z.object({
  request_id: z.uuid(),
  risk_level: z.enum(['normal', 'suspicious', 'dangerous', 'insufficient_information']),
  confidence: z.null(),
  risk_factors: z.array(z.string()),
  explanation: z.string(),
  action_guidance: z.array(z.string()),
  limitations: z.array(z.string()),
  analysis_version: z.string(),
  is_demo: z.literal(false),
  analysis_mode: z.literal('rules'),
  evidence: z.array(z.object({
    factor_code: z.enum(['IMPERSONATION', 'MONEY_REQUEST', 'CREDENTIAL_REQUEST', 'LINK_CLICK', 'APP_INSTALL', 'URGENCY_THREAT', 'URL_REPUTATION_MATCH']),
    label: z.string(), source: z.enum(['rule', 'url_reputation']), rule_id: z.string(), snippet: z.string(),
    start: z.number().int().min(0), end: z.number().int().positive(),
  })),
  input_assessment: z.object({
    status: z.enum(['action_identified', 'sentence_present', 'fragment', 'url_only']), reasons: z.array(z.string()),
  }),
  analysis_stages: z.array(z.object({
    name: z.enum(['rules', 'lightweight_model', 'url_reputation']),
    status: z.enum(['completed', 'not_implemented', 'not_connected', 'not_applicable', 'unavailable']),
  })),
  policy_reason: z.string(),
  urls: z.array(z.object({
    original_url: z.string(), normalized_url: z.string().nullable(), ascii_host: z.string().nullable(),
    validation_status: z.enum(['valid', 'invalid']), validation_message: z.string(), warnings: z.array(z.string()),
    occurrences: z.array(z.object({ text: z.string(), start: z.number().int().min(0), end: z.number().int().positive() })),
    reputation: z.object({
      status: z.enum(['not_connected', 'not_requested', 'malicious', 'benign', 'unknown', 'unavailable', 'timeout', 'auth_error', 'rate_limited']),
      provider: z.string().nullable(), checked_at: z.string().nullable(),
      reason: z.string().nullable().optional(), full_hash_verified: z.boolean().default(false),
      threat_types: z.array(z.enum(['MALWARE', 'SOCIAL_ENGINEERING', 'UNWANTED_SOFTWARE', 'POTENTIALLY_HARMFUL_APPLICATION'])).optional(),
      cache_expires_at: z.string().nullable().optional(), cache_hit: z.boolean().default(false),
    }),
  })),
})

export class AnalysisError extends Error {}

export async function requestAnalysis(body: AnalysisRequest, signal: AbortSignal): Promise<AnalysisResponse> {
  let response: Response
  try {
    response = await fetch('/api/v1/analyses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
      cache: 'no-store',
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new AnalysisError('서버에 연결하지 못했어요. 인터넷 연결과 백엔드 실행 상태를 확인한 뒤 다시 시도해주세요.')
  }
  if (!response.ok) {
    // 공급자의 원문/스택 대신 사용자에게 필요한 안내만 표시한다.
    if (response.status === 422) {
      const data = await response.json().catch(() => null)
      if (data?.error?.code === 'OCR_CONFIRMATION_REQUIRED') throw new AnalysisError('추출한 문자와 URL을 확인한 뒤 분석해주세요.')
      if (data?.error?.code === 'INVALID_URL') throw new AnalysisError('http:// 또는 https://로 시작하는 URL 한 개를 입력해주세요. 주소 형식을 확인해주세요.')
      if (data?.error?.code === 'TOO_MANY_URLS') throw new AnalysisError('URL 후보는 중복을 제외하고 10개 이하로 입력해주세요.')
      throw new AnalysisError('입력 내용을 확인해주세요. 메시지는 1자 이상, 10,000자 이하로 입력해주세요.')
    }
    if (response.status === 429) throw new AnalysisError('요청이 많아요. 잠시 기다린 뒤 다시 시도해주세요.')
    throw new AnalysisError('서버에서 분석을 완료하지 못했어요. 잠시 후 분석하기를 다시 눌러주세요.')
  }
  let data: unknown
  try { data = await response.json() } catch { throw new AnalysisError('서버 응답을 읽지 못했어요. 다시 시도해주세요.') }
  const result = resultSchema.safeParse(data)
  if (!result.success) throw new AnalysisError('결과 형식을 확인하지 못했어요. 다시 시도해주세요.')
  return result.data
}
