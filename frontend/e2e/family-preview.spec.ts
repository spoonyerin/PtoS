import { expect, test, type Page } from '@playwright/test'
async function selectState(page: Page, state: string) {
  await page.getByText('개발용 미리보기', { exact: true }).click()
  await page.getByLabel('가족 보호 이용 상태').selectOption(state)
  await page.getByText('개발용 미리보기', { exact: true }).click()
}

test('유료 연결 완료 기본값과 미연결·무료 홈, 안내 진입', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const card = page.getByRole('button', { name: '가족 보호', exact: true })
  await expect(card).toContainText('우리딸♥ 님과 연결 완료')
  await page.screenshot({ path: 'test-results/family-home-paid-connected.png', fullPage: true })
  await selectState(page, 'paid-unlinked')
  await expect(card).toContainText('가족 및 보호자를 연결해')
  await page.screenshot({ path: 'test-results/family-home-paid-unlinked.png', fullPage: true })
  await selectState(page, 'free')
  await expect(card).toContainText('프리미엄 이용권')
  await page.screenshot({ path: 'test-results/family-home-free.png', fullPage: true })
  await card.click()
  await expect(page.getByRole('heading', { name: '가족 보호 프리미엄', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '프리미엄 가입하기', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '홈으로 돌아가기', exact: true }).click()
  await page.getByRole('button', { name: '이용하는 방법', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveAccessibleName('이용하는 방법')
})

test('무료 결과 공유 잠금과 유료 미리보기, 상태 유지·초기화', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await selectState(page, 'free')
  await page.getByRole('button', { name: '문자 확인하기', exact: true }).click()
  await page.getByRole('textbox', { name: '문자 내용' }).fill('은행입니다. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  const share = page.getByRole('button', { name: '가족에게 공유', exact: true })
  await expect(share).toBeDisabled()
  await expect(share).toHaveAccessibleDescription('프리미엄 이용권 활성화 후 사용할 수 있습니다.')
  await page.screenshot({ path: 'test-results/family-result-free.png', fullPage: true })
  await selectState(page, 'paid-connected')
  await expect(share).toBeEnabled()
  await share.click()
  await expect(page.getByRole('dialog', { name: '가족에게 공유하기' })).toBeVisible()
  await page.keyboard.press('Escape')
  await selectState(page, 'free')
  await expect(share).toBeDisabled()
  await page.getByRole('button', { name: '홈으로', exact: true }).click()
  await expect(page.getByRole('button', { name: '가족 보호', exact: true })).toContainText('프리미엄')
  await page.reload()
  await expect(page.getByRole('button', { name: '가족 보호', exact: true })).toContainText('연결 완료')
})

test('320px 큰 글씨에서도 상태별 홈 카드에 가로 넘침이 없다', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 })
  await page.goto('/')
  await page.getByRole('button', { name: '설정', exact: true }).click()
  await page.getByRole('checkbox', { name: '글씨 크게 보기' }).check()
  await page.getByRole('button', { name: '닫기', exact: true }).click()
  for (const state of ['paid-connected', 'paid-unlinked', 'free']) {
    await selectState(page, state)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    for (const card of await page.locator('.home-feature-cards button').all()) {
      expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
  }
  await page.screenshot({ path: 'test-results/family-home-free-large.png', fullPage: true })
})
