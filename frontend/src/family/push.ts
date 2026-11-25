// 웹 푸시 구독 도우미. 서버 호출은 하지 않는다(요청은 hooks/useFamily.tsx가 api/family.ts로 보낸다).

export type PushSupport = 'supported' | 'ios-install' | 'unsupported' | 'insecure'

export function pushSupport(): PushSupport {
  if (!window.isSecureContext) return 'insecure'
  const ok = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  if (ok) return 'supported'
  // iPhone·iPad는 홈 화면에 추가한(설치한) 앱에서만 웹 푸시를 쓸 수 있다(iOS 16.4 이상).
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  return ios ? 'ios-install' : 'unsupported'
}

export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return
  // sw.js는 알림만 처리하고 요청·결과를 캐시하지 않는다.
  navigator.serviceWorker.register('/sw.js').catch(() => undefined)
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes
}

export class PushSetupError extends Error {}

// 반드시 버튼 클릭 안에서 부른다(브라우저가 사용자 동작 없이 권한을 묻지 못하게 한다).
export async function createPushSubscription(publicKey: string) {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new PushSetupError('알림 권한이 허용되지 않았어요. 휴대폰이나 브라우저 설정에서 PtoS 알림을 허용해 주세요.')
  }
  const registration = await navigator.serviceWorker.ready
  const existing = await registration.pushManager.getSubscription()
  const subscription = existing ?? await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(publicKey),
  })
  const json = subscription.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) throw new PushSetupError('알림을 켜지 못했어요. 다시 시도해 주세요.')
  return { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } }
}

export async function removePushSubscription(): Promise<string | null> {
  if (!('serviceWorker' in navigator)) return null
  const registration = await navigator.serviceWorker.getRegistration()
  const subscription = await registration?.pushManager.getSubscription()
  if (!subscription) return null
  const endpoint = subscription.endpoint
  await subscription.unsubscribe().catch(() => undefined)
  return endpoint
}
