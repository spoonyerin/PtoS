import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'
import { readFileSync } from 'node:fs'

const fixture = path.resolve('../backend/tests/fixtures/korean-message.png')
const fake = { request_id: '8c224149-d5c4-4f9a-a77b-55a058cb8c71', text: '가짜 OCR: 은행입니다. 인증번호를 알려주세요. https://example.invalid/O0l1', urls: [], warnings: ['가짜 OCR 테스트 응답입니다.'], engine: 'tesseract-5', ocr_confidence: null }

async function upload(page: Page) {
  await page.goto('/')
  await page.getByRole('radio', { name: '스크린샷' }).check()
  await page.getByLabel('스크린샷 선택').setInputFiles(fixture)
  await expect(page.getByAltText('선택한 스크린샷 미리보기')).toBeVisible()
}

test('실제 한국어 Tesseract: 미리보기 → OCR → 수정·명시적 확인 → 실제 분석', async ({ page }) => {
  const analysis: unknown[] = []
  page.on('request', request => { if (request.url().endsWith('/api/v1/analyses')) analysis.push(request.postDataJSON()) })
  await upload(page)
  expect(analysis).toHaveLength(0)
  const reply = page.waitForResponse(r => r.url().endsWith('/api/v1/ocr'))
  await page.getByRole('button', { name: '이미지에서 글자 읽기 (OCR)', exact: true }).click()
  expect((await reply).status()).toBe(200)
  const content = page.getByRole('textbox', { name: '추출한 문자와 URL (수정 가능)' })
  await expect(content).toHaveValue(/은행 담당자입니다/)
  await expect(content).toHaveValue(/인증번호를 알려주세요/)
  await expect(page.getByRole('region', { name: '수정한 내용의 URL 후보' })).toContainText('https://example.invalid/notice')
  expect(analysis).toHaveLength(0)
  const submit = page.getByRole('button', { name: '확인한 내용으로 분석하기' })
  await expect(submit).toBeDisabled()
  const checkbox = page.getByRole('checkbox')
  await checkbox.check()
  // 수정은 이전 확인을 무효화한다. 변경 후 URL 후보와 근거 좌표도 새 문자열을 사용한다.
  const edited = '😀 은행입니다. 인증번호를 알려주세요. https://example.invalid/corrected'
  await content.fill(edited)
  await expect(checkbox).not.toBeChecked()
  await expect(submit).toBeDisabled()
  const urls = page.getByRole('region', { name: '수정한 내용의 URL 후보' })
  await expect(urls).toContainText('/corrected')
  await expect(urls.locator('a')).toHaveCount(0)
  await checkbox.check()
  await page.screenshot({ path: 'test-results/ocr-review.png', fullPage: true })
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await submit.click()
  await expect(page.getByRole('heading', { name: '위험', exact: true })).toBeVisible()
  expect(analysis).toEqual([{ input_type: 'ocr_text', content: edited, ocr_confirmed: true }])
  await expect(page.getByRole('region', { name: 'URL 형식 및 평판' })).toContainText('평판 조회 미연결')
  // 분석 완료 후의 편집도 즉시 해제되어야 한다. URL 후보 응답은 일부러 보류한다.
  let resumeReview!: () => void
  let reviewStarted!: () => void
  const held = new Promise<void>(resolve => { resumeReview = resolve })
  const started = new Promise<void>(resolve => { reviewStarted = resolve })
  await page.route('**/api/v1/ocr/review', async route => {
    reviewStarted()
    await held
    await route.continue()
  })
  try {
    await content.fill(edited.replace('/corrected', '/after-edit'))
    const immediate = await page.evaluate(() => ({
      checked: (document.querySelector('input[type=checkbox]') as HTMLInputElement).checked,
      previousResult: !!document.querySelector('.result-card'),
      submitDisabled: (document.querySelector('#ocr-text')!.closest('form')!.querySelector('button[type=submit]') as HTMLButtonElement).disabled,
    }))
    expect(immediate).toEqual({ checked: false, previousResult: false, submitDisabled: true })
    await started
    await expect(checkbox).not.toBeChecked()
    await expect(page.getByRole('heading', { name: '위험', exact: true })).toHaveCount(0)
    expect(analysis).toHaveLength(1)
    await page.screenshot({ path: 'test-results/ocr-edit-reset.png', fullPage: true })
  } finally { resumeReview() }
  await expect(urls).toContainText('/after-edit')
  await expect(submit).toBeDisabled()
  expect(analysis).toHaveLength(1)
})

for (const [code, message] of [['OCR_NO_TEXT', '문자를 찾지 못했어요'], ['OCR_FAILED', 'OCR 처리에 실패'], ['OCR_TIMEOUT', '시간이 초과']]) {
  test(`가짜 OCR ${code}: 확인 단계·분석에 진입하지 않고 재업로드/직접 입력 안내`, async ({ page }) => {
    let calls = 0
    page.on('request', request => { if (request.url().endsWith('/api/v1/analyses')) calls++ })
    await page.route('**/api/v1/ocr', route => route.fulfill({ status: code === 'OCR_TIMEOUT' ? 504 : 422, json: { error: { code, message: 'SECRET stderr' } } }))
    await upload(page)
    await page.getByRole('button', { name: '이미지에서 글자 읽기 (OCR)', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(message)
    await expect(page.getByRole('alert')).toContainText('직접 입력')
    await expect(page.getByRole('textbox')).toHaveCount(0)
    expect(calls).toBe(0)
    await page.getByRole('radio', { name: '문자', exact: true }).check()
    await expect(page.getByRole('textbox', { name: '문자 내용' })).toBeVisible()
  })
}

test('가짜 OCR: 이미지 변경·취소 후 이전 확인과 결과를 제거한다', async ({ page }) => {
  await page.route('**/api/v1/ocr', route => route.fulfill({ json: fake }))
  await upload(page)
  await page.getByRole('button', { name: '이미지에서 글자 읽기 (OCR)', exact: true }).click()
  await expect(page.getByRole('region', { name: '수정한 내용의 URL 후보' })).toContainText('/O0l1')
  await page.getByRole('checkbox').check()
  await page.getByLabel('스크린샷 선택').setInputFiles({ name: 'replacement.png', mimeType: 'image/png', buffer: readFileSync(fixture) })
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await page.getByRole('button', { name: '이미지 지우기 / 취소' }).click()
  await expect(page.getByAltText('선택한 스크린샷 미리보기')).toHaveCount(0)
})

test('위장 파일은 미리보기/OCR 전에 차단한다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: '스크린샷' }).check()
  await page.getByLabel('스크린샷 선택').setInputFiles({ name: 'fake.png', mimeType: 'image/png', buffer: Buffer.from('<svg>SECRET</svg>') })
  await expect(page.getByRole('alert')).toContainText('실제 JPG·PNG 형식이 아니에요')
  await expect(page.getByAltText('선택한 스크린샷 미리보기')).toHaveCount(0)
})
