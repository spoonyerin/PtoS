import { expect, test } from '@playwright/test'

const dangerous = '은행 담당자입니다. 인증번호를 알려주세요.'
const cases = [
  { name: '정상적인 안내문', text: '도서관은 내일 휴무입니다.', label: '정보 부족', level: 'insufficient_information', evidence: false },
  { name: '부정 표현', text: '은행은 인증번호를 요구하지 않습니다. 링크를 클릭하지 마세요.', label: '정보 부족', level: 'insufficient_information', evidence: false },
  { name: '예방 교육 인용', text: '“은행입니다. 인증번호를 알려주세요.”는 사기 예시입니다.', label: '정보 부족', level: 'insufficient_information', evidence: false },
  { name: '단일 요구', text: '앱을 설치해주세요.', label: '의심', level: 'suspicious', evidence: true },
  { name: '결합된 요구', text: dangerous, label: '위험', level: 'dangerous', evidence: true },
  { name: '불충분한 입력', text: '그거 지금 처리', label: '정보 부족', level: 'insufficient_information', evidence: false },
]

for (const item of cases) {
  test(`${item.name}을 실제 FastAPI로 분석한다`, async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('radio', { name: 'URL 직접 입력' })).toHaveCount(1)
    await page.getByRole('textbox').fill(item.text)
    const response = page.waitForResponse(r => r.url().endsWith('/api/v1/analyses') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '분석하기' }).click()
    const api = await response
    const body = await api.json()
    expect(api.status()).toBe(200)
    expect(api.request().postDataJSON()).toEqual({ input_type: 'text', content: item.text })
    expect(body.risk_level).toBe(item.level)
    expect(body.confidence).toBeNull()
    expect(body.is_demo).toBe(false)
    expect(body.analysis_stages[1]).toEqual({ name: 'lightweight_model', status: 'not_connected' })
    expect(body.evidence.length > 0).toBe(item.evidence)
    await expect(page.getByRole('heading', { name: item.label, exact: true })).toBeVisible()
    await expect(page.getByText('규칙 기반 개발 버전', { exact: true })).toHaveCount(2)
    await expect(page.getByRole('heading', { name: '이렇게 행동하세요' })).toBeVisible()
    for (const evidence of body.evidence) {
      expect(Array.from(item.text).slice(evidence.start, evidence.end).join('')).toBe(evidence.snippet)
      await expect(page.locator('q').filter({ hasText: evidence.snippet })).toBeVisible()
    }
    expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([])
    if (item.level === 'dangerous') await page.screenshot({ path: 'test-results/dangerous-desktop.png', fullPage: true })
  })
}

test('빈 입력과 서버 오류에서 복구한다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('alert')).toContainText('문자 내용을 입력해주세요')
  await page.getByRole('textbox').fill(dangerous)
  await page.route('**/api/v1/analyses', route => route.fulfill({ status: 503, body: '{}' }))
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('alert')).toContainText('서버에서 분석을 완료하지 못했어요')
  await expect(page.getByRole('textbox')).toHaveValue(dangerous)
  await page.unroute('**/api/v1/analyses')
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  await page.getByRole('textbox').fill('새 문자')
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toHaveCount(0)
})

test('요청 중 중복 제출을 막는다', async ({ page }) => {
  let requests = 0
  await page.route('**/api/v1/analyses', async route => {
    requests++
    const response = await route.fetch()
    await new Promise(resolve => setTimeout(resolve, 500))
    await route.fulfill({ response })
  })
  await page.goto('/')
  await page.getByRole('textbox').fill(dangerous)
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('button', { name: '분석 요청 중…' })).toBeDisabled()
  await expect(page.getByRole('textbox')).toBeDisabled()
  await page.locator('form').dispatchEvent('submit')
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  expect(requests).toBe(1)
})

test('모바일 화면에서 가로 넘침 없이 결과를 확인한다', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  await page.getByRole('textbox').fill('그거 지금 처리')
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('heading', { name: '정보 부족', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/insufficient-mobile.png', fullPage: true })
})

test('이모지 뒤의 근거와 URL을 텍스트로 표시하고 직접 접속하지 않는다', async ({ page }) => {
  const external: string[] = []
  page.on('request', request => { if (request.url().includes('example.invalid')) external.push(request.url()) })
  await page.goto('/')
  await page.getByRole('textbox').fill('😀 은행입니다. https://example.invalid/test 에 접속하세요. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: '분석하기' }).click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  await expect(page.locator('q').filter({ hasText: 'https://example.invalid/test 에 접속하세요' })).toBeVisible()
  await expect(page.locator('.result-card a')).toHaveCount(0)
  expect(external).toEqual([])
})
