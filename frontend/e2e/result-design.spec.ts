import { expect, test } from '@playwright/test'

// UI-only fake risk levels; the live rules do not return normal.
for (const [level, label] of [
  ['dangerous', '위험'], ['suspicious', '의심'],
  ['normal', '정상'], ['insufficient_information', '정보 부족'],
]) {
  test(`가짜 ${label} 응답: 시안 배너·카드·버튼 및 상세 근거`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.route('**/api/v1/analyses', async route => {
      const response = await route.fetch()
      const body = await response.json()
      body.risk_level = level
      if (level === 'normal') { body.risk_factors = []; body.evidence = [] }
      await route.fulfill({ response, json: body })
    })
    await page.goto('/#text')
    await page.getByRole('textbox').fill('은행 담당자입니다. 인증번호를 알려주세요. https://example.invalid/ 에 접속하세요.')
    await page.getByRole('button', { name: '분석하기', exact: true }).click()
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible()
    // 결과 이름은 계약의 네 결과 용어 그대로이고 "단계" 같은 접미사를 붙이지 않는다 (정보 부족은 중간 위험도가 아니다).
    await expect(page.locator('.result-banner h2')).toHaveText(label)
    await expect(page.locator('.result-buttons button')).toHaveCount(2)
    await expect(page.getByRole('button', { name: '가족에게 공유' })).toBeVisible()
    await expect(page.getByRole('button', { name: '홈으로', exact: true })).toBeVisible()
    await expect(page.locator('.result-details')).not.toHaveAttribute('open', '')
    await expect(page.getByText('공식 사이트와 다른 주소가 발견됐어요.', { exact: true })).toHaveCount(0)
    if (level === 'normal') await expect(page.getByText('뚜렷한 위험 신호가 없어요.', { exact: true })).toBeVisible()
    await page.screenshot({ path: `test-results/result-${level}.png`, fullPage: true })
    await page.setViewportSize({ width: 320, height: 740 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.locator('.result-details > summary').click()
    await expect(page.getByRole('region', { name: 'URL 형식 및 평판' })).toContainText('평판 조회 미연결')
    if (level !== 'normal') await expect(page.locator('q').filter({ hasText: '인증번호를 알려주세요' })).toBeVisible()
  })
}
