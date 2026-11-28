import { expect, test, type Page } from '@playwright/test'

// 가족 보호(발표 시연 한정): 실제 FastAPI(메모리 저장소, 웹 푸시 꺼짐)에 두 기기(고령자·보호자)를 연결한다.
const BASE = 'http://127.0.0.1:5173'
const MESSAGE = '은행입니다. 인증번호를 알려주세요. PRIVATE 010-1234-5678 https://private.invalid/?secret=123'
const SECRETS = ['PRIVATE', '010-1234-5678', 'private.invalid', 'secret=123']

async function analyze(page: Page) {
  await page.goto(`${BASE}/#text`)
  await page.getByRole('textbox', { name: '문자 내용' }).fill(MESSAGE)
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
}

async function expectNoSecrets(page: Page) {
  const text = await page.locator('body').innerText()
  for (const secret of SECRETS) expect(text).not.toContain(secret)
}

test('초대 → 수락 → 확인 요청 → 의견 → 자동 알림 흐름', async ({ page, browser }) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 390, height: 844 })
  // 고령자: 시연용 프리미엄 시작, 가족 초대 만들기
  await page.goto(`${BASE}/`)
  await page.getByRole('button', { name: /가족 보호.*프리미엄 이용권/ }).click()
  await page.screenshot({ path: 'test-results/live-premium.png', fullPage: true })
  await page.getByRole('button', { name: '프리미엄 시작하기 (시연용)' }).click()
  await expect(page.getByText('프리미엄이 시작됐어요!')).toBeVisible()
  await page.getByRole('button', { name: '지금 가족 연결하기' }).click()
  await page.getByLabel('자식').check()
  await page.getByRole('textbox', { name: '부르는 이름' }).fill('우리 딸')
  await page.getByRole('button', { name: '초대 링크 만들기' }).click()
  const inviteUrl = (await page.getByLabel('초대 링크').innerText()).trim()
  expect(inviteUrl).toMatch(/\/#family\/invite\/[\w-]+$/)
  await page.screenshot({ path: 'test-results/family-invite.png' })

  // 보호자: 다른 브라우저(기기)에서 초대 수락
  const guardianContext = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const guardian = await guardianContext.newPage()
  await guardian.goto(inviteUrl.replace(/^https?:\/\/[^/]+/, BASE))
  await expect(guardian.getByText('가족 보호 초대가 왔어요')).toBeVisible()
  await guardian.getByRole('textbox', { name: '초대한 가족을 뭐라고 부를까요?' }).fill('엄마')
  await guardian.getByRole('button', { name: '수락하기' }).click()
  await expect(guardian.getByText('가족과 연결됐어요')).toBeVisible()
  await expect(guardian.getByText('이 서버에서는 알림을 보낼 수 없어요', { exact: false })).toBeVisible()

  // 같은 초대는 다시 쓸 수 없다.
  const thirdContext = await browser.newContext()
  const third = await thirdContext.newPage()
  await third.goto(inviteUrl.replace(/^https?:\/\/[^/]+/, BASE))
  await expect(third.getByRole('alert')).toContainText('새 초대 링크')
  await thirdContext.close()

  // 고령자: 가족 보호 화면에 연결 완료로 보인다.
  await page.goto(`${BASE}/#family`)
  await expect(page.getByText('✓ 연결 완료')).toBeVisible()
  await page.screenshot({ path: 'test-results/family-protect.png', fullPage: true })
  await page.goto(`${BASE}/`)
  await expect(page.getByRole('button', { name: /가족 보호.*우리 딸 님과 연결 완료/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/family-home.png' })

  // 고령자: 분석 결과를 앱 안에서 가족에게 보낸다.
  await analyze(page)
  await page.screenshot({ path: 'test-results/live-result.png', fullPage: true })
  await page.getByRole('button', { name: '가족에게 공유', exact: true }).click()
  const sheet = page.getByRole('dialog', { name: '가족에게 공유하기' })
  await expect(sheet.getByRole('checkbox', { name: /우리 딸/ })).toBeChecked()
  await expect(sheet.getByText('인증번호·개인정보 요구')).toBeVisible()
  await expectNoSecrets(page)
  await page.screenshot({ path: 'test-results/family-send-preview.png' })
  await sheet.getByRole('button', { name: '공유하기' }).click()
  await expect(sheet.getByText('우리 딸 님에게 결과를 보냈어요.')).toBeVisible()
  await expect(sheet.getByText('우리 딸 님이 확인하는 중')).toBeVisible()

  // 보호자: 홈 알림 → 받은 요청 → 의견 보내기. 원문·URL·번호는 보이지 않는다.
  await guardian.goto(`${BASE}/`)
  await guardian.getByRole('button', { name: /가족이 문자 확인을 요청했어요 \(1건\)/ }).click()
  await guardian.screenshot({ path: 'test-results/live-records.png', fullPage: true })
  await guardian.getByRole('button', { name: /엄마 님이 요청/ }).click()
  await expect(guardian.getByText('엄마 님이 확인을 요청했어요.')).toBeVisible()
  await expect(guardian.getByText('인증번호·개인정보 요구')).toBeVisible()
  await expectNoSecrets(guardian)
  await guardian.screenshot({ path: 'test-results/family-guardian-request.png', fullPage: true })
  await guardian.getByRole('radio', { name: '위험해 보여요.' }).check()
  await guardian.getByRole('button', { name: '의견 보내기' }).click()
  await expect(guardian.getByText('보낸 의견')).toBeVisible()

  // 고령자: 열려 있는 공유 창이 확인·의견 도착을 다시 확인한다.
  await expect(sheet.getByText('우리 딸 님의 의견')).toBeVisible({ timeout: 15_000 })
  await expect(sheet.getByText('위험해 보여요.')).toBeVisible()
  await page.screenshot({ path: 'test-results/family-reply-arrived.png' })
  await sheet.getByRole('button', { name: '닫기', exact: true }).click()

  await guardian.getByRole('dialog', { name: '의견 보내기' }).getByRole('button', { name: '확인', exact: true }).click()
  await guardian.getByRole('button', { name: '가족 보호 기록 보기', exact: true }).click()
  await expect(guardian.locator('.history-my-reply-text').first()).toHaveText('위험해 보여요.')

  // 고령자: 자동 알림 동의 → '위험' 결과가 나오면 자동으로 보낸다.
  await page.goto(`${BASE}/#family/auto-alert`)
  await expect(page.getByText('입력한 문자 원문과 사진')).toBeVisible()
  await page.getByRole('button', { name: '동의하고 자동 알림 켜기' }).click()
  await expect(page.getByText('자동 알림을 켰어요.')).toBeVisible()
  await analyze(page)
  await expect(page.getByText(/자동 알림이 켜져 있어 우리 딸 님에게/)).toBeVisible()

  // 보호자: 기록에 자동 알림으로 들어온다.
  await guardian.goto(`${BASE}/#family/records/received`)
  await expect(guardian.getByText(/자동 알림/).first()).toBeVisible({ timeout: 12_000 })
  await expect(guardian.getByRole('button', { name: /엄마 님이 요청/ })).toHaveCount(2)
  await guardianContext.close()
})

test('가족 보호를 쓰지 않은 기기는 기존 공유 창(앱 선택·복사)을 쓴다', async ({ page }) => {
  await analyze(page)
  await page.getByRole('button', { name: '가족에게 공유', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '공유할 내용' })).toBeVisible()
  expect(await page.evaluate(() => localStorage.length)).toBe(0)
})
