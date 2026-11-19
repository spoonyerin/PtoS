import { expect, test, type Page } from '@playwright/test'

async function selectState(page: Page, state: string) {
  const panel = page.locator('.family-dev-panel')
  await panel.locator('summary').click()
  await page.getByLabel('가족 보호 이용 상태').selectOption(state)
  await panel.locator('summary').click()
}

async function openMembership(page: Page) {
  await page.getByRole('button', { name: '설정', exact: true }).click()
  await page.getByRole('button', { name: '가족 보호 프리미엄', exact: true }).click()
}

test('무료 가입 안내 → 모의 활성화 → 완료 → 가족 연결 폼', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const writes: string[] = []
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()) })
  await page.goto('/')
  await selectState(page, 'free')
  await page.getByRole('button', { name: '가족 보호', exact: true }).click()
  await expect(page.getByRole('heading', { name: '가족과 함께 사기를 막아요!' })).toBeFocused()
  await expect(page.locator('.premium-features li')).toHaveCount(4)
  await expect(page.locator('.premium-price')).toContainText('월 0000 원(₩)')
  await page.screenshot({ path: 'test-results/premium-before.png', fullPage: true, style: '.family-dev-panel { display: none !important; }' })
  await page.getByRole('button', { name: '프리미엄 가입하기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '프리미엄이 시작됐어요!' })).toBeFocused()
  await expect(page.getByRole('button', { name: '프리미엄 가입하기', exact: true })).toHaveCount(0)
  await expect(page.locator('.premium-price')).toHaveCount(0)
  await expect(page.locator('.premium-features li p')).toHaveCount(0)
  await expect(page.getByLabel('가족 보호 이용 상태')).toHaveValue('paid-unlinked')
  await page.screenshot({ path: 'test-results/premium-active.png', fullPage: true, style: '.family-dev-panel { display: none !important; }' })
  await page.getByRole('button', { name: '지금 가족 연결하기' }).click()
  await expect(page.getByRole('heading', { name: '가족 연결하기', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '가족 보호로 돌아가기' }).click()
  await expect(page.getByText('연결된 가족이 없어요.')).toBeVisible()
  expect(writes).toEqual([])
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
})

test('이미 활성화한 상태는 완료 화면으로 열리고 기존 가족이 유지된다', async ({ page }) => {
  await page.goto('/')
  await openMembership(page)
  await expect(page.getByRole('heading', { name: '프리미엄이 시작됐어요!' })).toBeVisible()
  await page.getByRole('button', { name: '홈으로 돌아가기' }).click()
  await expect(page.getByRole('button', { name: '가족 보호', exact: true })).toContainText('우리딸♥ 님과 연결 완료')
  await page.goto('/#premium')
  await expect(page.getByRole('heading', { name: '프리미엄이 시작됐어요!' })).toBeVisible()
  await selectState(page, 'free')
  await expect(page.getByRole('button', { name: '프리미엄 가입하기', exact: true })).toBeVisible()
  await selectState(page, 'paid-unlinked')
  await expect(page.getByRole('button', { name: '지금 가족 연결하기' })).toBeVisible()
})

test('320px 큰 글씨에서 가입 전후 화면과 버튼이 넘치지 않는다', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 })
  await page.goto('/')
  await page.getByRole('button', { name: '설정', exact: true }).click()
  await page.getByRole('checkbox', { name: '글씨 크게 보기' }).check()
  await page.getByRole('button', { name: '가족 보호 프리미엄', exact: true }).click()
  for (const state of ['free', 'paid-connected']) {
    await selectState(page, state)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    for (const element of await page.locator('.premium-features, .premium-price, .premium-primary').all()) {
      expect(await element.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
  }
})
