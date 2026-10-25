import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  // 회귀가 발생해도 테스트 중 사용자 URL에 실제로 연결하지 않는다.
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin !== 'http://127.0.0.1:5173') return route.abort()
    return route.continue()
  })
})

test('직접 IDN URL을 입력하고 형식/미연결을 비링크로 표시한다', async ({ page }) => {
  const external: string[] = []
  page.on('request', request => { if (new URL(request.url()).origin !== 'http://127.0.0.1:5173') external.push(request.url()) })
  await page.goto('/')
  await page.getByRole('radio', { name: 'URL 직접 입력' }).check()
  await page.getByRole('textbox', { name: 'URL 주소' }).fill('https://예시.한국/공지')
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/analyses') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '분석하기' }).click()
  const api = await response
  expect(api.request().postDataJSON().input_type).toBe('url')
  const body = await api.json()
  expect(body.urls[0].reputation.status).toBe('not_connected')
  await expect(page.getByRole('heading', { name: '정보 부족', exact: true })).toBeVisible()
  const section = page.getByRole('region', { name: 'URL 형식 및 평판' })
  await expect(section).toContainText('https://예시.한국/공지')
  await expect(section).toContainText('xn--vv4b11d.xn--3e0b707e')
  await expect(section).toContainText('평판 조회 미연결')
  await expect(section.locator('a, img, iframe')).toHaveCount(0)
  expect(external).toEqual([])
  await page.screenshot({ path: 'test-results/url-direct.png', fullPage: true })
})

test('메시지의 구두점과 중복을 처리하고 무효 후보를 구분한다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox').fill('😀 (HTTPS://EXAMPLE.INVALID:443), 다시 https://example.invalid/. 잘못된 https://-bad.invalid/ 주소입니다.')
  await page.getByRole('button', { name: '분석하기' }).click()
  const section = page.getByRole('region', { name: 'URL 형식 및 평판' })
  await expect(section).toContainText('같은 주소가 2회 등장했어요.')
  await expect(section).toContainText('문장 끝 구두점')
  await expect(section).toContainText('평판 조회 미연결')
  await expect(section).toContainText('형식 확인 필요')
  await expect(section).toContainText('평판 조회 안 함')
  await expect(page.getByRole('heading', { name: '정보 부족', exact: true })).toBeVisible()
  await expect(section.locator('a')).toHaveCount(0)
})

test('직접 잘못된 URL 오류 후 입력을 수정해 재시도한다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'URL 직접 입력' }).check()
  await page.getByRole('textbox').fill('ftp://example.invalid/')
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('alert')).toContainText('http:// 또는 https://')
  await expect(page.getByRole('textbox')).toHaveValue('ftp://example.invalid/')
  await page.getByRole('textbox').fill('https://example.invalid/')
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('region', { name: 'URL 형식 및 평판' })).toContainText('평판 조회 미연결')
})

test('최대 고유 URL 초과를 자르지 않고 안내한다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox').fill(Array.from({ length: 11 }, (_, i) => `https://example.invalid/${i}`).join(' '))
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('alert')).toContainText('10개 이하')
  await expect(page.getByRole('region', { name: 'URL 형식 및 평판' })).toHaveCount(0)
})
