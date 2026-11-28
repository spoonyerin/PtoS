import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'
const hide = '.application-mode,.family-dev-panel,.preview-scenario{display:none!important}'
const errors = new WeakMap<Page, string[]>()
test.beforeEach(({ page }) => {
  const messages: string[] = []
  errors.set(page, messages)
  page.on('pageerror', error => messages.push(error.message))
  page.on('console', message => { if (message.type() === 'error') messages.push(message.text()) })
})
test.afterEach(({ page }) => { expect(errors.get(page)).toEqual([]) })
async function open(page: Page) {
  const calls: string[] = []
  await page.route('**/api/v1/**', route => { calls.push(route.request().url()); return route.abort() })
  await page.goto('/?mode=preview'); return calls
}
async function analyze(page: Page) {
  await page.getByRole('button', { name: '문자 확인하기', exact: true }).click()
  await page.getByRole('textbox', { name: '문자 내용' }).fill('UI 확인용이며 전송하지 않는 문장')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
}
async function shot(page: Page, name: string) { await page.screenshot({ path: `test-results/integrated-${name}.png`, fullPage: true, style: hide }) }
test('서버 없이 최신 UI: 홈·분석·공유·상태, API 호출과 저장 없음', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const calls = await open(page)
  await expect(page.locator('.home-header')).toHaveCSS('display','flex'); await shot(page,'home')
  await analyze(page); await expect(page.getByRole('heading',{name:'위험',exact:true})).toBeVisible(); await shot(page,'result')
  await page.getByRole('button',{name:'가족에게 공유',exact:true}).click(); await shot(page,'share')
  await page.getByRole('button',{name:'공유하기',exact:true}).click()
  await shot(page,'share-methods')
  await page.getByRole('button',{name:'공유할 앱 선택',exact:true}).click(); await shot(page,'status')
  expect(calls).toEqual([])
  expect(await page.evaluate(()=>[localStorage.length,sessionStorage.length])).toEqual([0,0])
})
test('시나리오 네 단계·큰 글씨는 입력 분류 없이 명시적 선택을 따른다', async ({page})=>{
  const calls=await open(page); await page.setViewportSize({width:320,height:640})
  for(const [value,label] of [['dangerous','위험'],['suspicious','의심'],['normal','정상'],['insufficient_information','정보 부족']]){
    await page.locator('.preview-scenario > summary').click(); await page.getByLabel('다음 분석 결과').selectOption(value); await page.locator('.preview-scenario > summary').click()
    await analyze(page); await expect(page.getByRole('heading',{name:label,exact:true})).toBeVisible()
    await page.locator('.app-shell').evaluate(el=>el.classList.add('large-text'))
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    await page.getByRole('button',{name:'홈으로',exact:true}).click()
  } expect(calls).toEqual([])
})
test('기록 → 보호자 의견·완료 팝업 → 기록 반영 → 공식 가이드', async ({page})=>{
  await page.setViewportSize({width:390,height:844}); const calls=await open(page)
  await page.getByText('개발용 미리보기',{exact:true}).click()
  await page.getByRole('combobox',{name:'가족 보호 기록 관점'}).selectOption('received')
  await page.getByRole('button',{name:'가족 보호 기록 보기',exact:true}).click()
  await page.getByText('개발용 미리보기',{exact:true}).click(); await shot(page,'records')
  await page.getByRole('button',{name:'택배 주소 재입력 요청 확인하기'}).click(); await shot(page,'guardian')
  await page.getByRole('button',{name:'의견 보내기',exact:true}).click()
  await expect(page.getByRole('dialog',{name:'의견 보내기'})).toBeVisible(); await page.getByRole('button',{name:'확인',exact:true}).click()
  await page.getByRole('button',{name:'가족 보호 기록 보기',exact:true}).click()
  await expect(page.locator('.history-my-reply-text').first()).toContainText('위험해 보여요')
  await page.getByRole('button',{name:'가족 보호로 돌아가기'}).click(); await page.getByRole('button',{name:/공식 확인 가이드/}).click(); await shot(page,'guide')
  expect(calls).toEqual([])
})
test('OCR 이미지는 업로드하지 않고 합성 글자를 보여준다',async({page})=>{
  const calls=await open(page)
  await page.getByRole('button',{name:'사진으로 확인하기',exact:true}).click()
  await page.getByLabel('스크린샷 선택').setInputFiles(path.resolve('../backend/tests/fixtures/korean-message.png'))
  await page.getByRole('button',{name:'사진 글자 읽기',exact:true}).click()
  await expect(page.getByRole('textbox',{name:'추출한 문자와 URL (수정 가능)'})).toHaveValue(/화면 확인용 예시/)
  await expect(page.getByRole('button',{name:'확인한 내용으로 분석하기'})).toBeDisabled()
  expect(calls).toEqual([])
})

test('가입 → 가족 초대·모의 수락 → 자동 알림 설정, API 호출 없음', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const calls = await open(page)
  const panel = page.locator('.family-dev-panel').filter({ has: page.locator('#family-preview-state') })
  await panel.locator('summary').click()
  await page.getByLabel('가족 보호 이용 상태').selectOption('free')
  await panel.locator('summary').click()
  await page.getByRole('button', { name: '가족 보호', exact: true }).click()
  await shot(page, 'premium')
  await page.getByRole('button', { name: '프리미엄 가입하기', exact: true }).click()
  await expect(page.getByText('프리미엄이 시작됐어요!', { exact: true })).toBeVisible()
  await shot(page, 'premium-active')
  await page.getByRole('button', { name: '지금 가족 연결하기', exact: true }).click()
  await shot(page, 'invite')
  await page.getByRole('button', { name: '연락처에서 고르기', exact: true }).click()
  await page.getByRole('button', { name: /우리 아들♥.*예시/ }).click()
  await page.getByRole('button', { name: '초대 보내기', exact: true }).click()
  await expect(page.getByText('수락 대기', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '수정하기', exact: true }).click()
  await page.getByRole('button', { name: '모의 수락', exact: true }).click()
  await page.getByRole('button', { name: '수정 완료', exact: true }).click()
  await page.getByRole('button', { name: /위험 메시지 자동 알림/ }).click()
  await expect(page.getByRole('button', { name: '동의하고 자동 알림 켜기' })).toBeDisabled()
  await page.getByRole('button', { name: '바꾸기', exact: true }).click()
  await page.getByRole('button', { name: '우리 아들♥ 자식' }).click()
  await page.getByRole('button', { name: '동의하고 자동 알림 켜기' }).click()
  await expect(page.locator('.auto-state')).toHaveText('ON')
  await shot(page, 'auto-alert')
  expect(calls).toEqual([])
})
