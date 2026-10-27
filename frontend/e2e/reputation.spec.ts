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
})

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
    await expect(urls.locator('a, img, iframe')).toHaveCount(0)
    if (status === 'malicious') {
      await expect(page.locator('q').filter({ hasText: 'https://example.invalid/test' })).toBeVisible()
    }
    expect(external).toEqual([])
  })
}
