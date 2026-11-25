// 가족 보호(발표 시연 한정) 예외: 서버가 발급한 무작위 기기 열쇠 하나만 localStorage에 저장한다.
// 원문·결과·URL·이름·확인 요청은 브라우저에 저장하지 않는다(AGENTS.md, docs/FAMILY_SHARE.md).
const KEY = 'ptos.familyDevice'

export function readDeviceToken(): string | null {
  try { return window.localStorage.getItem(KEY) } catch { return null }
}

export function saveDeviceToken(token: string): void {
  try { window.localStorage.setItem(KEY, token) } catch { /* 저장할 수 없으면 이번 화면에서만 쓴다. */ }
}

export function clearDeviceToken(): void {
  try { window.localStorage.removeItem(KEY) } catch { /* 무시 */ }
}
