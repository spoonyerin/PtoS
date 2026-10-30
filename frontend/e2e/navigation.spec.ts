import { expect, test } from '@playwright/test'

test('모바일 홈에서 세 입력 화면으로 이동하고 뒤로 돌아온다', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: /쉽게 확인하고/ }),
  ).toBeVisible()
  await page.screenshot({
    path: 'test-results/home-mobile.png',
    fullPage: true,
  })
  for (const name of ['문자 확인하기', '사진으로 확인하기', '링크 확인하기']) {
    await page.getByRole('button', { name, exact: true }).click()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    await page.screenshot({
      path: `test-results/input-${name === '문자 확인하기' ? 'text' : name === '링크 확인하기' ? 'url' : 'photo'}.png`,
      fullPage: true,
    })
    await page.getByRole('button', { name: '홈으로 돌아가기' }).click()
  }
  await page.getByRole('button', { name: '이용하는 방법' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.getByRole('button', { name: '설정', exact: true }).click()
  await page.getByRole('checkbox', { name: '글씨 크게 보기' }).check()
  await page.getByRole('button', { name: '닫기' }).click()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.getByRole('button', { name: '문자 확인하기', exact: true }).click()
  await page.keyboard.press('Tab')
  await page.locator('.skip-link').focus()
  await page.keyboard.press('Enter')
  await expect(
    page.getByRole('heading', { name: '문자 확인하기', exact: true }),
  ).toBeVisible()
  await page.goBack()
  await expect(
    page.getByRole('button', { name: '사진으로 확인하기' }),
  ).toBeVisible()
})

test('결과 공유는 준비 중 안내만 표시하고 원문을 전달하지 않는다', async ({
  page,
}) => {
  await page.goto('/#text')
  await page.getByRole('textbox').fill('은행입니다. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '위험', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '가족에게 공유' }).click()
  await expect(page.getByRole('status')).toContainText('준비 중')
  await page.getByRole('button', { name: '다시 확인하기' }).click()
  await expect(page.getByRole('textbox')).toHaveValue(
    '은행입니다. 인증번호를 알려주세요.',
  )
})

test('가족에게 공유(준비 중)를 눌러도 네트워크 요청·새 창·클립보드 쓰기가 없다', async ({ page }) => {
  await page.addInitScript(() => {
    // 공유가 원문을 클립보드나 공유 시트로 넘기지 않는지 기록한다. 값은 저장하지 않는다.
    const calls: string[] = []
    ;(window as unknown as { __shareCalls: string[] }).__shareCalls = calls
    if (navigator.clipboard) navigator.clipboard.writeText = async () => { calls.push('clipboard') }
    ;(navigator as Navigator & { share?: unknown }).share = async () => { calls.push('share') }
  })
  await page.goto('/#text')
  await page.getByRole('textbox').fill('은행입니다. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  const requests: string[] = []
  page.on('request', request => requests.push(request.url()))
  const popups: unknown[] = []
  page.on('popup', popup => popups.push(popup))
  await page.getByRole('button', { name: '가족에게 공유 (준비 중)', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('준비 중')
  await expect(page.getByRole('status')).toContainText('공유되지 않았어요')
  await page.waitForTimeout(500)
  expect(requests).toEqual([])
  expect(popups).toEqual([])
  expect(await page.evaluate(() => (window as unknown as { __shareCalls: string[] }).__shareCalls)).toEqual([])
})
