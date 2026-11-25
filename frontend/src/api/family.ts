import { z } from 'zod'
import type { components } from './generated'
import { clearDeviceToken, readDeviceToken } from '../family/deviceToken'

// 가족 보호(발표 시연 한정) API. 원문·URL·보낸 번호는 보내지 않는다. 확인 요청은 위험 단계와 위험 요소 코드만 담는다.
export type FamilySummary = components['schemas']['FamilySummary']
export type FamilyLink = components['schemas']['FamilyLink']
export type FamilyRequestItem = components['schemas']['FamilyRequestItem']
export type FamilyRelation = FamilyLink['relation'] & string
export type FamilyReplyChoice = components['schemas']['FamilyReplyRequest']['choice']
export type FactorCode = FamilyRequestItem['factor_codes'][number]

const riskLevel = z.enum(['normal', 'suspicious', 'dangerous', 'insufficient_information'])
const factorCode = z.enum(['IMPERSONATION', 'MONEY_REQUEST', 'CREDENTIAL_REQUEST', 'LINK_CLICK', 'APP_INSTALL', 'URGENCY_THREAT',
  'URL_REPUTATION_MATCH', 'CONTACT_REQUEST', 'BENEFIT_LURE', 'SECRECY_REQUEST', 'SENDER_MISMATCH'])
const relation = z.enum(['child', 'spouse', 'sibling', 'other'])

const summarySchema: z.ZodType<FamilySummary> = z.object({
  premium: z.boolean(),
  auto_alert: z.object({ enabled: z.boolean(), link_id: z.string().nullable() }),
  links: z.array(z.object({
    id: z.string(), role: z.enum(['guardian', 'protected']), name: z.string(), relation: relation.nullable(),
    status: z.enum(['pending', 'connected']), invite_expires_at: z.string().nullable(),
  })),
  push_subscribed: z.boolean(),
  waiting_requests: z.number().int(),
  new_replies: z.number().int(),
  server_time: z.string(),
})

const requestSchema: z.ZodType<FamilyRequestItem> = z.object({
  id: z.string(), box: z.enum(['sent', 'received']), name: z.string(), risk_level: riskLevel,
  factor_codes: z.array(factorCode), auto: z.boolean(), created_at: z.string(), expires_at: z.string(),
  viewed_at: z.string().nullable(),
  reply: z.object({ choice: z.enum(['looks_dangerous', 'looks_fine', 'custom']), text: z.string().nullable(), replied_at: z.string() }).nullable(),
})

export class FamilyError extends Error {
  constructor(public code: string, message: string) { super(message) }
}

const MESSAGES: Record<string, string> = {
  FAMILY_OFF: '가족 보호 기능이 이 서버에서 꺼져 있어요.',
  DEVICE_REQUIRED: '이 기기 정보를 찾지 못했어요. 가족 보호 화면을 다시 열어 주세요.',
  PREMIUM_REQUIRED: '가족 보호 프리미엄(시연용)을 먼저 시작해 주세요.',
  NOT_FOUND: '내용을 찾지 못했어요. 이미 지워졌거나 보관 기간이 지났을 수 있어요.',
  INVITE_NOT_FOUND: '초대를 찾지 못했어요. 이미 사용했거나 기한이 지났을 수 있어요. 초대한 가족에게 새 초대 링크를 받아 주세요.',
  INVITE_USED: '이미 사용한 초대예요. 초대한 가족에게 새 초대 링크를 받아 주세요.',
  INVITE_EXPIRED: '초대 기한(24시간)이 지났어요. 초대한 가족에게 새 초대 링크를 받아 주세요.',
  INVITE_SELF: '내가 만든 초대는 이 기기에서 수락할 수 없어요. 가족의 휴대폰에서 열어 주세요.',
  ALREADY_LINKED: '이미 연결된 가족이에요.',
  ALREADY_REPLIED: '이미 의견을 보냈어요.',
  AUTO_ALERT_OFF: '자동 알림이 꺼져 있어요.',
  FAMILY_LIMIT: '가족 보호 사용 한도에 이르렀어요. 잠시 후 다시 시도해 주세요.',
  INVALID_NAME: '부르는 이름은 1~20자로 입력해 주세요.',
  INVALID_RELATION: '관계를 골라 주세요.',
  INVALID_REPLY: '보낼 의견을 고르거나 100자 이하로 입력해 주세요.',
  INVALID_INPUT: '입력 내용을 확인해 주세요.',
  PUSH_OFF: '이 서버에서는 알림을 보낼 수 없어요.',
  INVALID_PUSH: '이 브라우저의 알림 주소를 쓸 수 없어요. 다른 브라우저로 알림을 켜 주세요.',
}
const FALLBACK = '가족 보호 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'

async function call<T>(method: string, path: string, schema: z.ZodType<T> | null, body?: unknown, auth = true): Promise<T> {
  const headers: Record<string, string> = {}
  const token = readDeviceToken()
  if (auth && token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch(`/api/v1/family${path}`, {
      method, headers, cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new FamilyError('NETWORK', '서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const code: string = typeof data?.error?.code === 'string' ? data.error.code : response.status === 422 ? 'INVALID_INPUT' : 'UNKNOWN'
    // 서버가 이 기기를 모르면(초기화·삭제) 저장한 열쇠를 지운다.
    if (code === 'DEVICE_REQUIRED') clearDeviceToken()
    throw new FamilyError(code, MESSAGES[code] ?? FALLBACK)
  }
  if (schema === null) return undefined as T
  const parsed = schema.safeParse(await response.json().catch(() => null))
  if (!parsed.success) throw new FamilyError('INVALID_RESPONSE', FALLBACK)
  return parsed.data
}

export const familyApi = {
  registerDevice: () => call('POST', '/devices', z.object({ device_token: z.string().min(16) }), undefined, false),
  deleteDevice: () => call('DELETE', '/devices/me', null),
  summary: () => call('GET', '/me', summarySchema),
  setPremium: (active: boolean) => call('PUT', '/premium', summarySchema, { active }),
  createInvite: (name: string, relation: FamilyRelation) =>
    call('POST', '/invites', z.object({ link_id: z.string(), invite_token: z.string(), expires_at: z.string() }), { name, relation }),
  previewInvite: (token: string) =>
    call('POST', '/invites/preview', z.object({ guardian_name: z.string(), relation, expires_at: z.string() }), { token }),
  acceptInvite: (token: string, name: string) => call('POST', '/invites/accept', summarySchema, { token, name }),
  removeLink: (id: string) => call('DELETE', `/links/${encodeURIComponent(id)}`, summarySchema),
  setAutoAlert: (linkId: string | null) => call('PUT', '/auto-alert', summarySchema, { link_id: linkId }),
  sendRequests: (body: { link_ids: string[]; risk_level: FamilyRequestItem['risk_level']; factor_codes: FactorCode[]; auto?: boolean }) =>
    call('POST', '/requests', z.object({ request_ids: z.array(z.string()) }), body),
  listRequests: (box: 'sent' | 'received') =>
    call('GET', `/requests?box=${box}`, z.object({ items: z.array(requestSchema) })),
  getRequest: (id: string) => call('GET', `/requests/${encodeURIComponent(id)}`, requestSchema),
  reply: (id: string, choice: FamilyReplyChoice, text?: string) =>
    call('POST', `/requests/${encodeURIComponent(id)}/reply`, requestSchema, choice === 'custom' ? { choice, text } : { choice }),
  pushKey: () => call('GET', '/push/key', z.object({ public_key: z.string().nullable() }), undefined, false),
  subscribePush: (subscription: { endpoint: string; keys: { p256dh: string; auth: string } }) =>
    call('PUT', '/push', summarySchema, subscription),
  removePush: (endpoint: string | null) => call('POST', '/push/remove', summarySchema, { endpoint }),
}
