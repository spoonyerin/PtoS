import { expect, test } from '@playwright/test'

// e2e가 쓰는 실제 백엔드가 평판 조회를 켜지 않았음을 확인한다. 이미 떠 있던 서버를 재사용해
// playwright.config.ts의 PTOS_SAFE_BROWSING_MODE='' 가 적용되지 않은 경우도 여기서 실패한다.
test('e2e 백엔드는 URL 평판 외부 조회를 하지 않는다', async ({ request }) => {
  const response = await request.post('/api/v1/analyses', { data: { input_type: 'url', content: 'https://example.invalid/e2e-guard' } })
  expect(response.status()).toBe(200)
  const body = await response.json()
  expect(body.urls[0].reputation.status).toBe('not_connected')
  expect(['key_missing', 'policy_pending']).toContain(body.urls[0].reputation.reason)
  expect(body.urls[0].reputation.provider).toBeNull()
  expect(body.analysis_stages[2]).toEqual({ name: 'url_reputation', status: 'not_connected' })
  const ready = await request.get('/api/v1/health/ready')
  expect(await ready.json()).toEqual({ status: 'ready', mode: 'rules', url_reputation: 'off' })
})

const NOTICE = '주소에서 만든 일부 정보(해시)만 Google로 전송돼요.'
const ADVISORY = 'https://developers.google.com/safe-browsing/v4/advisory'

test('실제 백엔드(꺼짐)에서는 전송 안내를 숨긴다', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText(/URL 평판 조회는 꺼져 있으며/)).toBeVisible()
  await expect(page.getByText(NOTICE)).toHaveCount(0)
})

for (const [name, handler] of [
  ['켜짐', (route: import('@playwright/test').Route) => route.fulfill({ json: { status: 'ready', mode: 'rules', url_reputation: 'live' } })],
  ['상태 확인 실패', (route: import('@playwright/test').Route) => route.abort()],
] as const) {
  test(`가짜 준비 상태 ${name}이면 문자·URL 입력에 전송 안내를 보이고 스크린샷 업로드에는 없다`, async ({ page }) => {
    await page.route('**/api/v1/health/ready', handler)
    await page.goto('/')
    const notice = page.getByRole('note')
    await expect(notice).toContainText(NOTICE)
    await expect(notice).toContainText('주소를 그대로 보내지 않고')
    await page.getByRole('radio', { name: 'URL 직접 입력' }).check()
    await expect(page.getByRole('note')).toContainText(NOTICE)
    await page.getByRole('radio', { name: '스크린샷' }).check()
    await expect(page.getByRole('note')).toHaveCount(0)
  })
}

// These are explicitly FAKE reputation response UI checks, never Google calls.
for (const [status, label] of [
  ['unknown', '안전 판정 아님'], ['auth_error', '인증 오류'],
  ['rate_limited', '호출 제한'], ['timeout', '시간 초과'],
  ['malicious', '전체 SHA-256 해시 일치'],
]) {
  test(`가짜 평판 ${status} 표시와 원문 근거·비링크를 브라우저로 확인한다`, async ({ page }) => {
    const external: string[] = []
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== 'http://127.0.0.1:5173') {
        external.push(route.request().url())
        return route.abort()
      }
      return route.continue()
    })
    await page.route('**/api/v1/analyses', async route => {
      const response = await route.fetch()
      const body = await response.json()
      const url = body.urls[0]
      url.reputation = {
        status, provider: 'google_safe_browsing_v5', checked_at: '2026-10-22T00:00:00Z',
        full_hash_verified: status === 'malicious', cache_hit: true,
        threat_types: status === 'malicious' ? ['SOCIAL_ENGINEERING'] : [],
      }
      if (status === 'malicious') {
        const occurrence = url.occurrences[0]
        body.risk_factors.push('URL 위협 목록의 전체 해시 일치')
        body.evidence.push({ factor_code: 'URL_REPUTATION_MATCH', label: 'URL 위협 목록의 전체 해시 일치',
          source: 'url_reputation', rule_id: 'fake-browser-match', snippet: occurrence.text, start: occurrence.start, end: occurrence.end })
      }
      await route.fulfill({ response, json: body })
    })
    await page.goto('/')
    await page.getByRole('textbox').fill('은행입니다. 인증번호를 알려주세요. https://example.invalid/test')
    await page.getByRole('button', { name: '분석하기' }).click()
    await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
    await expect(page.locator('q').filter({ hasText: '인증번호를 알려주세요' })).toBeVisible()
    const urls = page.getByRole('region', { name: 'URL 형식 및 평판' })
    await expect(urls).toContainText(label)
    await expect(urls).toContainText('Google Safe Browsing')
    await expect(urls).toContainText('안전한 사이트를 위험으로 잘못 표시할 수 있어요')
    // 사용자 URL은 링크가 아니다. 화면의 링크는 Google 경고에 붙는 고정 Advisory 주소뿐이다.
    await expect(urls.locator('img, iframe')).toHaveCount(0)
    await expect(page.locator('a[href*="example.invalid"]')).toHaveCount(0)
    if (status === 'malicious') {
      await expect(urls).toContainText('위험한 사이트일 수 있다는 보고가 있어요')
      const urlEvidence = page.locator('li').filter({ has: page.locator('q', { hasText: 'https://example.invalid/test' }) })
      await expect(urlEvidence.getByRole('link', { name: 'Advisory provided by Google' })).toHaveAttribute('href', ADVISORY)
      const ruleEvidence = page.locator('li').filter({ has: page.locator('q', { hasText: '인증번호를 알려주세요' }) })
      await expect(ruleEvidence.getByRole('link')).toHaveCount(0)
      await expect(urls.locator('a')).toHaveCount(1)
      await expect(urls.locator('a')).toHaveAttribute('href', ADVISORY)
      const hrefs = await page.locator('a[href]').evaluateAll(links => links.map(a => a.getAttribute('href')))
      expect(hrefs.length).toBeGreaterThan(0)
      expect(hrefs.every(href => href === ADVISORY || href === '#main')).toBe(true)
    } else {
      await expect(urls.locator('a')).toHaveCount(0)
      await expect(page.getByText('Advisory provided by Google')).toHaveCount(0)
    }
    expect(external).toEqual([])
  })
}
