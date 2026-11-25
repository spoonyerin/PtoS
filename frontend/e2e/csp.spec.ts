import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'

// 발표 서버와 같은 보안 헤더(CSP)에서 화면이 깨지지 않는지 확인한다.
// CSP는 빌드한 화면(npx vite preview, deploy/oracle/Caddyfile)에만 붙으므로 개발 서버에서는 건너뛴다.
// 확인 방법: npm run build → npx vite preview를 띄운 뒤 npx playwright test e2e/csp.spec.ts

const fixture = path.resolve('../backend/tests/fixtures/korean-message.png')

function watchViolations(page: Page): string[] {
  const violations: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) violations.push(message.text())
  })
  return violations
}

test('보안 헤더(CSP)에서 문자 분석·사진 미리보기·가족 보호 화면이 동작한다', async ({ page }) => {
  const response = await page.goto('/')
  test.skip(!response?.headers()['content-security-policy'], '개발 서버에는 CSP가 없어요(빌드한 화면에서만 확인)')
  const violations = watchViolations(page)
  await page.reload()

  await expect(page.getByRole('button', { name: '사진으로 확인하기', exact: true })).toBeVisible()
  await page.goto('/#text')
  await page.getByRole('textbox').first().fill('은행 담당자입니다. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: /분석/ }).first().click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()

  await page.goto('/')
  await page.getByRole('button', { name: '사진으로 확인하기', exact: true }).click()
  await page.getByLabel('스크린샷 선택').setInputFiles(fixture)
  await expect(page.locator('img[src^="blob:"]')).toBeVisible()

  await page.goto('/')
  await page.getByRole('button', { name: /가족 보호.*프리미엄 이용권/ }).click()
  await page.getByRole('button', { name: '프리미엄 시작하기 (시연용)' }).click()
  await expect(page.getByText('프리미엄이 시작됐어요!')).toBeVisible()

  expect(violations).toEqual([])
})
