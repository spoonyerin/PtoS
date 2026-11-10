import { expect, test, type Page } from '@playwright/test'
type ShareWindow = Window & { __shared?: ShareData; __copied?: string }
async function analyze(page: Page) {
  await page.goto('/#text')
  await page.getByRole('textbox', { name: '문자 내용' }).fill('은행입니다. 인증번호를 알려주세요. PRIVATE 010-1234-5678 https://private.invalid/?secret=123')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '가족에게 공유', exact: true }).click()
}
async function mockSharing(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true })
    Object.defineProperty(navigator, 'share', { configurable: true, writable: true, value: async (data: ShareData) => {
      ;(window as ShareWindow).__shared = data
    } })
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => {
      ;(window as ShareWindow).__copied = text
    } } })
  })
}

test('미리보기와 공유·복사 문구가 같고 원문·사용자 URL은 빠진다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockSharing(page)
  await analyze(page)
  const text = await page.getByRole('textbox', { name: '공유할 내용' }).inputValue()
  expect(text).toContain('■ 분석 결과\n위험')
  expect(text).toContain('■ 대응 방법\n1.')
  for (const value of ['PRIVATE', '010-1234-5678', 'private.invalid']) expect(text).not.toContain(value)
  await page.screenshot({ path: 'test-results/family-share-preview.png', fullPage: false })
  await page.getByRole('button', { name: '공유할 앱 선택' }).click()
  await expect(page.getByRole('status')).toContainText('전송 여부는 선택한 앱에서 확인')
  expect(await page.evaluate(() => (window as ShareWindow).__shared)).toEqual({ title: 'PtoS 분석 결과', text })
  await page.getByRole('button', { name: '복사하기', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('내용을 복사했어요')
  expect(await page.evaluate(() => (window as ShareWindow).__copied)).toBe(text)
  await page.getByRole('button', { name: '공유 창 닫기' }).click()
  await expect(page.getByRole('button', { name: '가족에게 공유', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '다시 확인하기' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('공유 취소와 실패를 전송 완료로 안내하지 않는다', async ({ page }) => {
  await mockSharing(page)
  await analyze(page)
  await page.evaluate(() => { navigator.share = async () => { throw new DOMException('cancel', 'AbortError') } })
  await page.getByRole('button', { name: '공유할 앱 선택' }).click()
  await expect(page.getByRole('status')).toContainText('공유를 취소했어요')
  await page.evaluate(() => { navigator.share = async () => { throw new DOMException('denied', 'NotAllowedError') } })
  await page.getByRole('button', { name: '공유할 앱 선택' }).click()
  await expect(page.getByRole('status')).toContainText('공유 창을 열지 못했어요')
  await expect(page.getByRole('button', { name: '복사하기', exact: true })).toBeEnabled()
})

test('공유 미지원·복사 거부 시 선택된 텍스트로 수동 복사를 안내한다', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', { configurable: true, writable: true, value: undefined })
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('denied') } } })
  })
  await analyze(page)
  await expect(page.getByRole('button', { name: '공유할 앱 선택' })).toBeDisabled()
  await page.getByRole('button', { name: '복사하기', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('자동 복사를 할 수 없어요')
  const preview = page.getByRole('textbox', { name: '공유할 내용' })
  await expect(preview).toBeFocused()
  expect(await preview.evaluate((el: HTMLTextAreaElement) => el.selectionEnd - el.selectionStart)).toBe((await preview.inputValue()).length)
  await page.screenshot({ path: 'test-results/family-share-fallback.png', fullPage: false })
})

test('320px 큰 글씨·짧은 화면에서 스크롤과 모달 키보드 이동을 지원한다', async ({ page }) => {
  await mockSharing(page)
  await page.setViewportSize({ width: 320, height: 568 })
  await page.goto('/')
  await page.getByRole('button', { name: '설정', exact: true }).click()
  await page.getByRole('checkbox', { name: '글씨 크게 보기' }).check()
  await page.getByRole('button', { name: '닫기', exact: true }).click()
  await page.getByRole('button', { name: '문자 확인하기', exact: true }).click()
  await page.getByRole('textbox', { name: '문자 내용' }).fill('은행입니다. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await page.getByRole('button', { name: '가족에게 공유', exact: true }).click()
  const sheet = page.getByRole('dialog', { name: '가족에게 공유하기' })
  await expect(sheet).toBeVisible()
  const bounds = await sheet.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(568)
  expect(await sheet.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab')
    expect(await sheet.evaluate(el => el.contains(document.activeElement))).toBe(true)
  }
  const preview = page.getByRole('textbox', { name: '공유할 내용' })
  expect(await preview.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
  await page.screenshot({ path: 'test-results/family-share-large.png', fullPage: false })
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
  await expect(page.getByRole('button', { name: '가족에게 공유', exact: true })).toBeFocused()
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
})

test('공유 처리 중 중복 실행을 막고 지원하지 않는 데이터는 복사로 안내한다', async ({ page }) => {
  await mockSharing(page)
  await analyze(page)
  await page.evaluate(() => {
    const win = window as Window & { __finish?: () => void; __calls?: number }
    navigator.share = () => {
      win.__calls = (win.__calls ?? 0) + 1
      return new Promise<void>(resolve => { win.__finish = resolve })
    }
  })
  await page.getByRole('button', { name: '공유할 앱 선택' }).click()
  await expect(page.getByRole('button', { name: '공유할 앱 선택' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '복사하기', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => (window as Window & { __calls?: number }).__calls)).toBe(1)
  await page.evaluate(() => (window as Window & { __finish?: () => void }).__finish!())
  await expect(page.getByRole('button', { name: '공유할 앱 선택' })).toBeEnabled()
  await page.evaluate(() => Object.defineProperty(navigator, 'canShare', { value: () => false }))
  await page.getByRole('button', { name: '공유할 앱 선택' }).click()
  await expect(page.getByRole('status')).toContainText('이 환경에서는 공유 창을 열 수 없어요')
  await expect(page.getByRole('button', { name: '복사하기', exact: true })).toBeEnabled()
})
