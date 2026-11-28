import { expect, test } from '@playwright/test'

test('공유 링크로 보호자 요청 화면 → 선택/직접 의견 → 중복 방지, 기록 연결', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const writes: string[] = []
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()) })
  await page.goto('/#family/share/preview')
  await expect(page.getByRole('heading', { name: '가족 보호 요청', exact: true })).toBeFocused()
  await expect(page.getByRole('radio', { name: '위험해 보여요.', exact: true })).toBeChecked()
  for (const image of await page.locator('.guardian-risk-icon img, .guardian-factors .factor-symbol img').all()) {
    await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true)
    const glyph = await image.boundingBox()
    const disc = await image.locator('..').boundingBox()
    expect(Math.abs(glyph!.x + glyph!.width / 2 - disc!.x - disc!.width / 2)).toBeLessThan(1)
    expect(Math.abs(glyph!.y + glyph!.height / 2 - disc!.y - disc!.height / 2)).toBeLessThan(1)
  }
  await page.screenshot({ path: 'test-results/guardian-request.png', fullPage: true, style: '.family-dev-panel { display:none !important; }' })
  await page.getByRole('radio', { name: '문제 없어 보여요.', exact: true }).check()
  await expect(page.getByRole('heading', { name: '위험 단계', exact: true })).toBeVisible()
  await page.getByRole('radio', { name: '직접 입력하기', exact: true }).check()
  await expect(page.getByRole('textbox', { name: '보낼 확인 메시지' })).toBeFocused()
  await expect(page.getByRole('button', { name: '의견 보내기', exact: true })).toBeDisabled()
  await page.getByRole('textbox', { name: '보낼 확인 메시지' }).fill('링크를 누르지 말고 평소 사용하는 택배 앱으로 확인해요.')
  await page.screenshot({ path: 'test-results/guardian-custom.png', fullPage: true, style: '.family-dev-panel { display:none !important; }' })
  await page.getByRole('button', { name: '의견 보내기', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '의견 보내기' })).toBeVisible()
  await page.screenshot({ path: 'test-results/guardian-confirmation.png', fullPage: false })
  await page.getByRole('button', { name: '확인', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('링크를 누르지 말고')
  await expect(page.getByRole('button', { name: '의견 보냄', exact: true })).toBeDisabled()
  await page.screenshot({ path: 'test-results/guardian-sent.png', fullPage: true, style: '.family-dev-panel { display:none !important; }' })
  await page.getByRole('button', { name: '가족 보호 기록 보기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '가족 보호 기록', exact: true })).toBeVisible()
  expect(writes).toEqual([])
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
})

test('개발 패널 진입, 직접 링크·알 수 없는 링크 구분, 뒤로 가기', async ({ page }) => {
  await page.goto('/')
  await page.getByText('개발용 미리보기', { exact: true }).click()
  await page.getByRole('button', { name: '보호자 공유 화면 보기' }).click()
  await expect(page).toHaveURL(/#family\/share\/preview$/)
  await expect(page.getByText('원문 요약', { exact: true })).toBeVisible()
  await page.evaluate(() => { location.hash = '#family/share/unknown-link' })
  await expect(page.getByText('공유 내용을 확인할 수 없어요.', { exact: true })).toBeVisible()
  await expect(page.getByText('010-****-0000', { exact: false })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByText('원문 요약', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '홈으로 돌아가기', exact: true }).click()
  await expect(page.getByRole('button', { name: '문자 확인하기', exact: true })).toBeVisible()
})

test('320px 큰 글씨에서 긴 의견 입력·라디오·버튼이 넘치지 않는다', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 })
  await page.goto('/#family/share/preview')
  await page.locator('.app-shell').evaluate(el => el.classList.add('large-text'))
  await page.getByRole('radio', { name: '직접 입력하기', exact: true }).check()
  await page.getByRole('textbox', { name: '보낼 확인 메시지' }).fill('가'.repeat(500))
  expect(await page.getByRole('textbox', { name: '보낼 확인 메시지' }).inputValue()).toHaveLength(500)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  for (const card of await page.locator('.guardian-requester, .guardian-analysis, .guardian-submit').all()) {
    expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
  }
})
