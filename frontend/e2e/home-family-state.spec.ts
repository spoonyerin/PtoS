import { expect, test } from '@playwright/test'
for (const state of ['off', 'unknown'] as const) {
  test(`가족 기능 ${state}여도 메인 카드는 유지하고 진입 시 상태를 안내한다`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const calls: string[] = []
    await page.route('**/api/v1/family/**', route => { calls.push(route.request().url()); return route.abort() })
    await page.route('**/api/v1/health/ready', route => state === 'unknown' ? route.abort() : route.fulfill({ json: { status: 'ready', mode: 'rules', url_reputation: 'off', llm_review: 'off', family: 'off', push: 'off' } }))
    await page.goto('/?mode=connected')
    const card = page.getByRole('button', { name: /가족 보호.*가족과 함께/ })
    await expect(card).toBeVisible()
    await expect(page.getByRole('button', { name: /이용 방법/ })).toBeVisible()
    await page.screenshot({ path: `test-results/home-family-${state}.png`, fullPage: true, style: '.application-mode { display:none!important }' })
    await page.setViewportSize({ width: 320, height: 740 })
    await page.locator('.app-shell').evaluate(el => el.classList.add('large-text'))
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await card.click()
    await expect(page.getByText(state === 'off' ? /가족 보호 기능이 이 서버에서 꺼져/ : /서버 연결 상태를 확인하지 못했어요/)).toBeVisible()
    expect(calls).toEqual([])
  })
}
