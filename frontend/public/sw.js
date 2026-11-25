// PtoS 서비스 워커: 가족 보호 알림만 처리한다.
// fetch 이벤트를 다루지 않으므로 요청·분석 결과·이미지를 캐시하지 않는다.
// 알림 내용은 서버가 보낸 고정 문장뿐이고, 결과는 앱을 열어야 보인다.

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = {} }
  const title = typeof data.title === 'string' ? data.title : 'PtoS 가족 보호'
  const body = typeof data.body === 'string' ? data.body : '가족 보호 알림이 도착했어요.'
  const url = typeof data.url === 'string' && data.url.startsWith('/#family') ? data.url : '/#family'
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/assets/pwa-192.png',
    badge: '/assets/pwa-192.png',
    data: { url },
    lang: 'ko',
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL(event.notification.data?.url || '/#family', self.location.origin).href
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus()
        if ('navigate' in client) return client.navigate(url)
        return undefined
      }
    }
    return self.clients.openWindow(url)
  })())
})
